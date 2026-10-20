"""Cumulative inflation across prices, settlements, and historical accounting."""

import contextlib
import io
import math
import random
import unittest
from unittest.mock import patch

import utility


class InflationTests(unittest.TestCase):
    def setUp(self):
        rng_state = random.getstate()
        self.addCleanup(random.setstate, rng_state)
        output = contextlib.redirect_stdout(io.StringIO())
        output.__enter__()
        self.addCleanup(output.__exit__, None, None, None)
        random.seed(42)
        self.session = utility.UtilityGameSession()
        self.economy = self.session.economy
        self.player = self.session.player
        self.state = self.session.game_state
        self.financials = self.session.financials
        self.grid = self.session.grid

    def test_opening_prices_have_no_premature_month_of_inflation(self):
        self.assertEqual(self.economy.price_index, 1)
        self.assertEqual(self.economy.monthly_inflation_factor, 1)
        self.assertEqual(self.player.construction_cost('nuclear'), 9_000_000_000)
        self.assertEqual(self.session.regulator.current_retail_price, 150)
        self.assertEqual(self.state.natural_gas_price, 45)
        self.assertIs(self.player.economy, self.economy)
        self.assertIs(self.state.economy, self.economy)
        self.assertIs(self.session.regulator.economy, self.economy)

    def test_annual_rate_compounds_exactly_over_twelve_months(self):
        self.economy.inflation = 0.12
        for _ in range(12):
            self.economy.advance_price_level()
        self.assertAlmostEqual(self.economy.price_index, 1.12)
        self.assertAlmostEqual(self.player.construction_cost('nuclear'), 10_080_000_000,
                               delta=0.01)

    def test_changing_rates_preserve_the_actual_inflation_path(self):
        rates = [0.12] * 6 + [0.02] * 6
        for rate in rates:
            self.economy.inflation = rate
            self.economy.advance_price_level()
        expected = math.prod((1 + rate) ** (1 / 12) for rate in rates)
        self.assertAlmostEqual(self.economy.price_index, expected)
        self.assertGreater(self.economy.price_index, 1.02)

    def test_zero_inflation_and_deflation(self):
        self.economy.inflation = 0
        self.economy.advance_price_level()
        self.assertEqual(self.economy.price_index, 1)
        self.economy.inflation = -0.01
        for _ in range(12):
            self.economy.advance_price_level()
        self.assertAlmostEqual(self.economy.price_index, 0.99)
        self.assertAlmostEqual(self.player.construction_cost('solar'),
                               600_000_000 * .99 * self.economy.technology_cost_factor('solar'), delta=0.01)
        self.assertAlmostEqual(self.session.regulator.current_retail_price, 148.5)

    def test_month_close_advances_prices_once_using_displayed_annual_rate(self):
        before = self.economy.price_index
        self.session.advance_month()
        expected = before * (1 + self.economy.inflation) ** (1 / 12)
        self.assertAlmostEqual(self.economy.price_index, expected)
        for _ in range(3):
            self.player.construction_quote('solar', 3)
            utility.wholesale_market_price(self.economy)
            self.financials.calculate_revenue(self.grid, self.session.regulator, self.economy)
        self.assertEqual(self.economy.price_index, expected)

    def test_all_construction_quotes_match_amounts_charged(self):
        self.economy.price_index = 1.25
        self.player.cash = 1_000_000_000_000
        for kind, (_, base_cost, _) in utility.GUI_BUILD_INFO.items():
            with self.subTest(kind=kind):
                self.assertAlmostEqual(self.player.construction_cost(kind), base_cost * 1.25)
                quote = self.player.construction_quote(kind, 2)
                cash = self.player.cash
                self.assertTrue(self.player.start_construction(kind, 2))
                self.assertAlmostEqual(cash - self.player.cash, quote, delta=0.01)
                projects = self.player.ongoing_constructions[-2:]
                self.assertAlmostEqual(sum(project['cost_paid'] for project in projects), quote)
        hydro = [p for p in self.player.ongoing_constructions if p['type'] == 'hydro']
        self.assertGreater(hydro[1]['initial_cost'], hydro[0]['initial_cost'])
        self.assertAlmostEqual(hydro[1]['initial_cost'] / hydro[0]['initial_cost'], 1.18)

    def test_operating_costs_and_carbon_follow_index_without_double_counting(self):
        self.player.power_plants = dict.fromkeys(self.player.power_plants, 1)
        self.grid.gas_generation = 100
        self.grid.battery_discharged = 0
        self.state.carbon_tax = 40
        self.financials.calculate_operational_costs(self.player, self.state, self.grid, self.economy)
        before = {row['source']: row.copy() for row in self.financials.operating_cost_breakdown}
        self.economy.price_index = 1.3
        self.financials.calculate_operational_costs(self.player, self.state, self.grid, self.economy)
        for row in self.financials.operating_cost_breakdown:
            if row['source'] in self.player.power_plants:
                for key in ('fuel_om_power', 'carbon', 'cash_cost'):
                    self.assertAlmostEqual(row[key], before[row['source']][key] * 1.3, delta=0.01)

    def test_wholesale_buys_sales_and_retail_revenue_all_follow_index(self):
        self.grid.contract_imports_mw = 100
        self.grid.contract_exports_mw = 200
        self.grid.spot_imports_mw = 50
        self.grid.spot_exports_mw = 75
        f = self.financials
        f.calculate_revenue(self.grid, self.session.regulator, self.economy)
        keys = ('contract_purchase_cost', 'contract_sales_revenue', 'spot_purchase_cost',
                'spot_sales_revenue', 'monthly_electric_revenue')
        before = {key: getattr(f, key) for key in keys}
        market = utility.wholesale_market_price(self.economy)
        self.economy.price_index = 1.4
        self.assertAlmostEqual(utility.wholesale_market_price(self.economy), market * 1.4)
        f.calculate_revenue(self.grid, self.session.regulator, self.economy)
        for key in keys:
            self.assertAlmostEqual(getattr(f, key), before[key] * 1.4, delta=0.01)

    def test_rate_case_increase_is_preserved_above_inflation(self):
        regulator = self.session.regulator
        self.economy.price_index = 1.2
        self.assertEqual(regulator.current_retail_price, 180)
        with patch('utility.random.random', return_value=0):
            self.assertTrue(regulator.request_increase(
                self.player, self.financials, self.economy, self.state.turn, 0.10))
        self.assertAlmostEqual(regulator.current_retail_price, 198)
        self.economy.price_index = 1.32
        self.assertAlmostEqual(regulator.current_retail_price, 150 * 1.10 * 1.32)

    def test_gas_mean_reversion_and_price_caps_are_in_real_dollars(self):
        self.economy.price_index = 1.4
        with patch('utility.random.random', return_value=1), \
                patch('utility.random.uniform', return_value=0):
            self.state.update_gas_price()
            self.assertAlmostEqual(self.state.natural_gas_price, 45 * 1.4)
            self.state.natural_gas_price = 1000
            self.state.update_gas_price()
            self.assertAlmostEqual(self.state.natural_gas_price,
                                   utility.NATURAL_GAS_MAX_COST_PER_MWH * 1.4)

    def test_carbon_enactment_and_policy_escalator_also_include_inflation(self):
        self.economy.price_index = 1.5
        self.state._carbon_tax_start_turn = self.state.turn
        self.state._carbon_tax_initial = 40
        self.state._carbon_tax_annual_growth = 0.12
        self.state.update_carbon_policy()
        self.assertEqual(self.state.carbon_tax, 60)
        self.economy.price_index = 1.6
        self.state.update_carbon_policy()
        self.assertAlmostEqual(self.state.carbon_tax, 40 * 1.6 * 1.12 ** (1 / 12))

    def test_historical_accounts_and_prepaid_projects_are_not_revalued(self):
        p = self.player
        p.cash = 2_000_000_000
        p.start_construction('solar')
        accounts = (p.cash, p.total_debt(), p.book_equity(), p.gross_utility_plant(),
                    p.accumulated_depreciation(), p.monthly_depreciation(),
                    p.construction_work_in_progress(), p.annual_dividend_per_share,
                    tuple((b.principal, b.annual_rate, b.months_remaining) for b in p.bonds))
        self.economy.price_index = 2
        self.assertEqual(accounts, (p.cash, p.total_debt(), p.book_equity(), p.gross_utility_plant(),
                                    p.accumulated_depreciation(), p.monthly_depreciation(),
                                    p.construction_work_in_progress(), p.annual_dividend_per_share,
                                    tuple((b.principal, b.annual_rate, b.months_remaining) for b in p.bonds)))
        p.update_constructions()
        self.assertEqual(p.ongoing_constructions[0]['total_cost'], 600_000_000)

    def test_overrun_work_uses_current_prices_but_old_payments_stay_fixed(self):
        p = self.player
        p.cash = 20_000_000_000
        self.economy.price_index = 1.2
        p.start_construction('nuclear')
        project = p.ongoing_constructions[0]
        self.assertEqual(project['initial_cost'], 10_800_000_000)
        self.economy.price_index = 1.5
        cash = p.cash
        with patch('utility.random.random', return_value=0), \
                patch('utility.random.uniform', return_value=0.04):
            p.update_constructions()
        self.assertAlmostEqual(cash - p.cash, 540_000_000, delta=0.01)
        self.assertEqual(project['initial_cost'], 10_800_000_000)
        self.assertAlmostEqual(project['total_cost'], 11_340_000_000, delta=0.01)
        project['turns_remaining'] = 1
        p.update_constructions()
        asset = p.plant_assets[-1]
        self.assertAlmostEqual(asset.original_cost, 11_340_000_000, delta=0.01)
        self.assertAlmostEqual(asset.inflation_adjusted_cost(1.5), 14_040_000_000, delta=0.01)

    def test_retirement_inflates_salvage_and_teardown_not_removed_book_value(self):
        p = self.player
        asset = next(a for a in reversed(p.plant_assets) if a.plant_type == 'coal')
        self.economy.price_index = 1.5
        salvage, teardown = utility.DECOMMISSION_INFO['coal']
        expected = (asset.original_cost * salvage - teardown) * 1.5
        cash = p.cash
        p.decommission_plant('coal')
        self.assertAlmostEqual(p.cash - cash, expected, delta=0.01)
        self.assertAlmostEqual(p.disposal_gain_loss_since_close,
                               expected - asset.net_book_value, delta=0.01)

    def test_new_asset_salvage_does_not_inflate_its_purchase_price_twice(self):
        p = self.player
        self.economy.price_index = 1.5
        p.cash = 1_000_000_000
        p.start_construction('solar')
        p.ongoing_constructions[0]['turns_remaining'] = 1
        p.update_constructions()
        cash = p.cash
        p.decommission_plant('solar')
        self.assertAlmostEqual(p.cash - cash, 900_000_000 * 0.15 - 200_000 * 1.5, delta=0.01)
        self.economy.price_index = 1.2
        p.batteries.append({})
        p._add_plant_asset('battery', 180_000_000)
        self.economy.price_index = 1.5
        cash = p.cash
        p.decommission_battery()
        self.assertAlmostEqual(p.cash - cash, 22_500_000, delta=0.01)

    def test_inflated_activity_still_reconciles_cash_flow(self):
        p = self.player
        self.economy.price_index = 1.5
        p.issue_bond(p.monthly_borrowing_limit, self.economy, '10yr', self.session.credit)
        p.start_construction('solar')
        p.decommission_plant('coal')
        self.session.advance_month()
        f = self.financials
        self.assertAlmostEqual(f.ending_cash - f.beginning_cash,
                               f.net_cash_from_operations + f.net_cash_from_investing
                               + f.net_cash_from_financing, delta=0.01)

    def test_cli_uses_the_same_economy_for_every_price(self):
        calls = []
        def actions(player, economy, regulator, financials, credit, turn, state):
            calls.append(turn)
            self.assertIs(player.economy, economy)
            self.assertIs(state.economy, economy)
            self.assertIs(regulator.economy, economy)
            self.assertAlmostEqual(player.construction_cost('solar'),
                                   utility.SOLAR_CONSTRUCTION_COST * economy.price_index
                                   * economy.technology_cost_factor('solar'))
        with patch('utility.player_action_menu', side_effect=actions):
            utility.run_game(2)
        self.assertEqual(calls, [1, 2])


if __name__ == '__main__':
    unittest.main()
