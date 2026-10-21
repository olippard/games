"""Demand planning, reconciled plant costs, and earnings-led stock valuation."""

import contextlib
import io
import pickle
import random
import unittest
from unittest.mock import patch

import utility


class ForecastingTests(unittest.TestCase):
    def setUp(self):
        rng_state = random.getstate()
        self.addCleanup(random.setstate, rng_state)
        output = contextlib.redirect_stdout(io.StringIO())
        output.__enter__()
        self.addCleanup(output.__exit__, None, None, None)
        random.seed(42)
        self.session = utility.UtilityGameSession()
        self.player = self.session.player
        self.state = self.session.game_state
        self.financials = self.session.financials
        self.grid = self.session.grid

    def test_forecast_rollover_seasonality_growth_and_variation(self):
        self.state.current_month = 12
        self.state.year = 3
        self.state.climate = 'hot'
        rows = self.grid.forecast_demand(self.player, self.state)
        self.assertEqual(len(rows), 24)
        self.assertEqual((rows[0]['month'], rows[0]['year']), (1, 4))
        self.assertEqual((rows[-1]['month'], rows[-1]['year']), (12, 5))
        january = (self.player.base_territory_mw * self.state.demand_index
                   * (1 + utility.MONTHLY_DEMAND_GROWTH) * 0.65)
        self.assertAlmostEqual(rows[0]['expected'], january)
        self.assertGreater(rows[6]['expected'], rows[0]['expected'])
        self.assertAlmostEqual(rows[12]['expected'] / rows[0]['expected'], 1.02)
        for row in rows:
            self.assertAlmostEqual(row['low'], row['expected'] * 0.90)
            self.assertAlmostEqual(row['high'], row['expected'] * 1.10)
            self.assertAlmostEqual(row['reserve_margin'],
                                   (row['firm_supply'] - row['high']) / row['high'])
        self.state.climate = 'cold'
        cold = self.grid.forecast_demand(self.player, self.state)
        self.assertGreater(cold[0]['expected'], cold[6]['expected'])

    def test_forecast_matches_simulation_without_new_random_events(self):
        self.state.active_demand_events = [
            {'name': 'Known growth', 'months_left': 2, 'monthly_pressure': 0.03},
            {'name': 'Known slowdown', 'months_left': 1, 'monthly_pressure': -0.01},
        ]
        rows = self.grid.forecast_demand(self.player, self.state, months=4)
        with patch('utility.random.random', return_value=1), \
                patch('utility.random.uniform', return_value=0):
            for row in rows:
                self.state.advance_turn()
                demand = self.grid.calculate_demand(self.player, self.state)
                self.assertAlmostEqual(row['expected'], demand)

    def test_forecast_is_read_only_and_does_not_reveal_random_events(self):
        before = pickle.dumps((self.player, self.state, self.grid))
        rng_state = random.getstate()
        rows = self.grid.forecast_demand(self.player, self.state)
        self.assertEqual(rows, self.grid.forecast_demand(self.player, self.state))
        self.assertEqual(rng_state, random.getstate())
        self.assertEqual(before, pickle.dumps((self.player, self.state, self.grid)))

    def test_forecast_includes_projects_and_next_month_contract(self):
        firm = self.grid.firm_capacity(self.player)
        self.player.ongoing_constructions = [
            {'type': 'natural_gas', 'turns_remaining': 2},
            {'type': 'battery', 'turns_remaining': 3},
            {'type': 'nuclear', 'turns_remaining': 72},
        ]
        self.player.wholesale_commitment_mw = 200
        self.player.pending_wholesale_commitment_mw = -100
        rows = self.grid.forecast_demand(self.player, self.state, months=3)
        gas = utility.PLANT_NAMEPLATE_CAPACITY['natural_gas'] * utility.CAPACITY_CREDIT['natural_gas']
        battery = utility.PLANT_NAMEPLATE_CAPACITY['battery'] * utility.CAPACITY_CREDIT['battery']
        self.assertAlmostEqual(rows[0]['firm_supply'], firm - 100)
        self.assertAlmostEqual(rows[1]['firm_supply'], firm - 100 + gas)
        self.assertAlmostEqual(rows[2]['firm_supply'], firm - 100 + gas + battery)
        self.player.pending_wholesale_commitment_mw = 0  # cancellation, not no pending edit
        self.assertEqual(self.grid.forecast_demand(self.player, self.state)[0]['firm_supply'], firm)

    def test_cost_rows_reconcile_including_carbon_and_imports(self):
        self.state.carbon_tax = 50
        self.grid.gas_generation = 125
        self.grid.contract_imports_mw = 100
        self.grid.spot_imports_mw = 50
        self.financials.update_player_financials(
            self.player, self.state, self.grid, self.session.economy,
            self.session.regulator, valuation_only=True)
        f = self.financials
        rows = {row['source']: row for row in f.operating_cost_breakdown}
        self.assertEqual(len(rows), 9)
        self.assertAlmostEqual(sum(row['cash_cost'] for row in rows.values()),
                               f.cash_operating_expenses)
        self.assertAlmostEqual(sum(row['depreciation'] for row in rows.values()),
                               f.depreciation_expense)
        self.assertAlmostEqual(sum(row['carbon'] for row in rows.values()),
                               f.monthly_carbon_tax_expense)
        self.assertEqual(rows['contract_imports']['cash_cost'], f.contract_purchase_cost)
        self.assertEqual(rows['spot_imports']['cash_cost'], f.spot_purchase_cost)
        self.assertEqual(rows['natural_gas']['energy_mwh'], 125 * utility.HOURS_PER_MONTH)
        self.assertAlmostEqual(rows['natural_gas']['carbon'],
                               125 * utility.HOURS_PER_MONTH * 50
                               * utility.GAS_EMISSIONS_TONS_PER_MWH)
        self.assertTrue(all(rows[k]['carbon'] == 0 for k in ('nuclear', 'solar', 'battery')))

    def test_idle_peakers_have_no_fuel_cost_but_still_depreciate(self):
        self.grid.gas_generation = 0
        self.financials.update_player_financials(
            self.player, self.state, self.grid, self.session.economy,
            self.session.regulator, valuation_only=True)
        gas = next(row for row in self.financials.operating_cost_breakdown
                   if row['source'] == 'natural_gas')
        self.assertEqual(gas['cash_cost'], 0)
        self.assertGreater(gas['depreciation'], 0)

    def test_ttm_estimates_roll_off_after_twelve_actual_months(self):
        f = self.financials
        opening = f.trailing_earnings[:]
        self.assertEqual(len(opening), 12)
        self.assertEqual(f.ttm_coverage_description(), '0 actual / 12 pre-game estimated months')
        f.record_monthly_earnings(100)
        self.assertAlmostEqual(f.ttm_net_income, sum(opening[1:]) + 100, delta=0.01)
        self.assertEqual(f.ttm_coverage_description(), '1 actual / 11 pre-game estimated months')
        for income in range(2, 13):
            f.record_monthly_earnings(income)
        self.assertEqual(f.ttm_net_income, 100 + sum(range(2, 13)))
        self.assertEqual(f.ttm_coverage_description(), '12 completed months')
        f.record_monthly_earnings(-50)
        self.assertEqual(len(f.trailing_earnings), 12)
        self.assertEqual(f.ttm_net_income, sum(range(2, 13)) - 50)

    def test_actual_close_values_stock_using_statement_ttm_eps(self):
        initial = self.financials.trailing_earnings[:]
        self.session.advance_month()
        f = self.financials
        self.assertEqual(f.trailing_earnings, initial[1:] + [f.net_profit])
        self.assertEqual(f.actual_earnings_months, 1)
        self.assertEqual(self.player.valuation_eps, f.ttm_eps(self.player.shares_outstanding))
        self.assertEqual(self.player.earnings_price_target,
                         self.player.valuation_eps * self.player.valuation_pe)
        self.assertAlmostEqual(sum(row['depreciation'] for row in f.operating_cost_breakdown),
                               f.depreciation_expense)

    def test_valuation_preview_does_not_reset_ttm_history(self):
        self.financials.record_monthly_earnings(-1_000_000)
        before = self.financials.trailing_earnings[:]
        self.financials.update_player_financials(
            self.player, self.state, self.grid, self.session.economy,
            self.session.regulator, valuation_only=True)
        self.assertEqual(before, self.financials.trailing_earnings)
        self.assertEqual(self.financials.actual_earnings_months, 1)

    def test_stock_tracks_eps_with_seventy_percent_earnings_weight(self):
        p = self.player
        p.investor_confidence = 0.5
        quote = 100
        # Match required yield to remove the independent yield adjustment.
        p.annual_dividend_per_share = quote * (
            self.session.economy.interest_rate + utility.REQUIRED_RETURN_PREMIUM)
        prices = []
        with patch('utility.random.uniform', return_value=0):
            for eps in (-0.01, 0, 0.01, 1, 2):
                p.stock_price = quote
                p.update_stock_price(self.session.economy, eps * p.shares_outstanding)
                prices.append(p.stock_price)
        self.assertEqual(prices, sorted(prices))
        self.assertAlmostEqual(prices[-1] - prices[-2],
                               0.70 * p.valuation_pe * utility.STOCK_SMOOTHING)
        self.assertAlmostEqual(utility.BOOK_VALUE_WEIGHT + utility.EARNINGS_WEIGHT
                               + utility.DIVIDEND_WEIGHT, 1)

    def test_opening_stock_uses_ten_times_earnings(self):
        p = self.player
        p.investor_confidence = 0.5
        p.stock_price = 0
        with patch('utility.random.uniform', return_value=0):
            p.update_stock_price(self.session.economy, self.financials.ttm_net_income)
        self.assertAlmostEqual(p.stock_price, self.financials.ttm_eps(p.shares_outstanding) * 10)


if __name__ == '__main__':
    unittest.main()
