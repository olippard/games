"""Contracts, shareholder dismissal, and individual plant accounting."""

import contextlib
import io
import random
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import utility


class OperationsTests(unittest.TestCase):
    def setUp(self):
        rng_state = random.getstate()
        self.addCleanup(random.setstate, rng_state)
        output = contextlib.redirect_stdout(io.StringIO())
        output.__enter__()
        self.addCleanup(output.__exit__, None, None, None)
        random.seed(42)
        self.session = utility.UtilityGameSession()
        self.player = self.session.player

    def dispatch(self, commitment=0, demand=800, solar=0):
        plants = dict.fromkeys(utility.PLANT_BUILD_COST, 0)
        plants.update(coal=1, natural_gas=2, solar=solar)
        player = SimpleNamespace(power_plants=plants, batteries=[],
                                 battery_dispatch_mode='after_gas',
                                 wholesale_commitment_mw=commitment)
        state = SimpleNamespace(region_sunlight_level=0.25, region_wind_level=0.5)
        grid = utility.PowerGrid()
        grid.total_demand = demand
        with patch.object(grid, 'calculate_demand'):
            grid.update_grid_status(player, state)
        return grid

    def settlement(self, grid):
        financials = utility.Financials()
        financials.calculate_revenue(grid, utility.RateRegulator(),
                                     SimpleNamespace(sentiment=0))
        return financials

    def test_contract_edits_replace_pending_amount_without_cash_or_grid_changes(self):
        p = self.player
        before = p.cash, self.session.grid.total_generation
        self.assertTrue(p.wholesale_trade(100, 'sell', self.session.economy))
        self.assertTrue(p.wholesale_trade(200, 'buy', self.session.economy))
        self.assertEqual(p.wholesale_commitment_mw, 0)
        self.assertEqual(p.pending_wholesale_commitment_mw, 200)
        self.assertEqual((p.cash, self.session.grid.total_generation), before)
        self.session.advance_month()
        self.assertEqual(self.session.grid.contract_imports_mw, 200)
        self.assertIsNone(p.pending_wholesale_commitment_mw)

    def test_contract_recurs_and_cancellation_only_applies_next_month(self):
        p = self.player
        p.wholesale_trade(100, 'sell', self.session.economy)
        for _ in range(2):
            self.session.advance_month()
            self.assertEqual(self.session.grid.contract_exports_mw, 100)
            f = self.session.financials
            expected = (100 * utility.HOURS_PER_MONTH
                        * utility.wholesale_market_price(self.session.economy)
                        * utility.CONTRACT_SELL_FACTOR)
            self.assertAlmostEqual(f.contract_sales_revenue, expected)
            self.assertAlmostEqual(f.ending_cash - f.beginning_cash,
                                   f.net_cash_from_operations + f.net_cash_from_investing
                                   + f.net_cash_from_financing, delta=0.01)
        p.wholesale_trade(0, 'sell', self.session.economy)
        self.assertEqual(p.wholesale_commitment_mw, -100)
        self.session.advance_month()
        self.assertEqual(p.wholesale_commitment_mw, 0)
        self.assertEqual(self.session.financials.contract_sales_revenue, 0)

    def test_invalid_contracts_leave_pending_plan_unchanged(self):
        p = self.player
        p.wholesale_trade(100, 'buy', self.session.economy)
        for amount, direction in ((-1, 'buy'), (float('nan'), 'sell'),
                                  (float('inf'), 'sell'), (100, 'oops')):
            self.assertFalse(p.wholesale_trade(amount, direction, self.session.economy))
            self.assertEqual(p.pending_wholesale_commitment_mw, 100)

    def test_exports_dispatch_peakers_and_imports_displace_them(self):
        ordinary, exporting, importing = self.dispatch(), self.dispatch(-300), self.dispatch(200)
        self.assertEqual(ordinary.gas_generation, 200)
        self.assertEqual(exporting.gas_generation, 500)
        self.assertEqual(importing.gas_generation, 0)
        for grid in (ordinary, exporting, importing):
            self.assertEqual(grid.available_for_customers, 800)
            self.assertEqual(grid.current_surplus_deficit, 0)
            self.assertLessEqual(grid.total_generation, grid.maximum_generation)

    def test_exports_reduce_surplus_and_are_not_sold_twice(self):
        grid = self.dispatch(-100, demand=200)
        self.assertEqual(grid.total_generation, 600)
        self.assertEqual(grid.available_for_customers, 500)
        self.assertEqual(grid.spot_exports_mw, 300)
        f = self.settlement(grid)
        self.assertEqual(f.contract_sales_revenue, 100 * 730 * 40 * 0.95)
        self.assertEqual(f.spot_sales_revenue, 300 * 730 * 40 * 0.85)
        self.assertEqual(f.purchased_power_costs, 0)

    def test_unsupported_exports_must_be_purchased_at_a_loss(self):
        large, larger = self.dispatch(-2000), self.dispatch(-3000)
        self.assertEqual(large.spot_imports_mw, 1200)
        f1, f2 = self.settlement(large), self.settlement(larger)
        net1 = f1.total_operating_revenue - f1.purchased_power_costs / 12
        net2 = f2.total_operating_revenue - f2.purchased_power_costs / 12
        self.assertLess(net2, net1)

    def test_excess_imports_cannot_be_resold_for_a_free_profit(self):
        f1 = self.settlement(self.dispatch(1000))
        f2 = self.settlement(self.dispatch(2000))
        self.assertLess(f2.total_operating_revenue - f2.purchased_power_costs / 12,
                        f1.total_operating_revenue - f1.purchased_power_costs / 12)

    def test_maximum_generation_includes_idle_peakers_and_weather(self):
        grid = self.dispatch(demand=200, solar=2)
        self.assertEqual(grid.gas_generation, 0)
        self.assertEqual(grid.total_generation, 700)
        self.assertEqual(grid.maximum_generation, 1700)
        app = utility.UtilityGameGUI.__new__(utility.UtilityGameGUI)
        app.session = SimpleNamespace(grid=grid, game_state=self.session.game_state)
        app.history = []
        app._record_history()
        self.assertEqual(app.history[0]['maximum_generation'], 1700)

    def test_dividend_cut_and_zero_payments_deplete_happiness_then_fire(self):
        p = self.player
        p.set_dividend(0)
        self.assertIn('WARNING', p.shareholder_status())
        self.assertEqual(p.shareholder_happiness, 25)
        for month in range(4):
            result = self.session.advance_month()
            if month < 3:
                self.assertEqual(result, 'OK')
                self.assertFalse(self.session.game_over)
            else:
                self.assertEqual(result, 'FIRED')
        self.assertTrue(self.session.game_over)
        turn = self.session.game_state.turn
        self.assertEqual(self.session.advance_month(), 'GAME_OVER')
        self.assertEqual(self.session.game_state.turn, turn)

    def test_happiness_yield_boundaries_and_no_duplicate_review(self):
        p = self.player
        p.stock_price = 100
        p.dividend_reference_price = 100
        p.annual_dividend_per_share = p.dividend_high_water = 2
        p.review_dividend_policy(SimpleNamespace(turn=2))
        self.assertEqual(p.shareholder_happiness, 71)
        p.review_dividend_policy(SimpleNamespace(turn=2))
        self.assertEqual(p.shareholder_happiness, 71)
        p.set_dividend(3)
        p.review_dividend_policy(SimpleNamespace(turn=3))
        self.assertEqual(p.shareholder_happiness, 75)
        p.set_dividend(2)
        self.assertEqual(p.shareholder_happiness, 25)
        self.assertFalse(p.fired)

    def test_opening_asset_register_and_depreciation_reconcile(self):
        p = self.player
        self.assertEqual(len(p.plant_assets), sum(p.power_plants.values()))
        self.assertEqual(len({asset.asset_id for asset in p.plant_assets}), len(p.plant_assets))
        gross = sum(asset.original_cost for asset in p.plant_assets)
        self.assertEqual(p.gross_utility_plant(), gross)
        forecast = p.monthly_depreciation()
        opening_depreciation = p.accumulated_depreciation()
        self.assertGreater(opening_depreciation, 0)
        self.assertTrue(all(asset.months_in_service > 0 for asset in p.plant_assets))
        posted = p.monthly_depreciation(post=True)
        self.assertAlmostEqual(forecast, posted)
        self.assertAlmostEqual(p.accumulated_depreciation(), opening_depreciation + posted,
                               delta=0.01)
        self.assertAlmostEqual(sum(asset.net_book_value for asset in p.plant_assets),
                               p.net_utility_plant(), delta=0.01)

    def test_each_new_unit_keeps_its_own_cost_and_depreciation_life(self):
        p = self.player
        old = p._add_plant_asset('solar', 300_000_000)
        old.accumulated_depreciation = old.original_cost
        new = p._add_plant_asset('solar', 600_000_000)
        p.monthly_depreciation(post=True)
        self.assertEqual(old.last_month_depreciation, 0)
        self.assertEqual(new.last_month_depreciation, 600_000_000 / 360)
        self.assertEqual(new.months_in_service, 1)

    def test_project_completion_capitalizes_actual_cost_and_retirement_removes_unit(self):
        p = self.player
        p.issue_bond(p.monthly_borrowing_limit, self.session.economy, '10yr', self.session.credit)
        self.assertTrue(p.start_construction('hydro', 2))
        costs = [project['total_cost'] for project in p.ongoing_constructions]
        self.assertLess(costs[0], costs[1])
        self.assertFalse(any(asset.plant_type == 'hydro' for asset in p.plant_assets))
        for project in p.ongoing_constructions:
            project['turns_remaining'] = 1
        p.update_constructions()
        assets = [asset for asset in p.plant_assets if asset.plant_type == 'hydro']
        self.assertEqual([asset.original_cost for asset in assets], costs)
        self.assertEqual(p.construction_work_in_progress(), 0)
        p.monthly_depreciation(post=True)
        old_net = p.net_utility_plant()
        retired_net = assets[-1].net_book_value
        self.assertTrue(p.decommission_plant('hydro'))
        self.assertNotIn(assets[-1], p.plant_assets)
        self.assertIn(assets[0], p.plant_assets)
        self.assertAlmostEqual(p.net_utility_plant(), old_net - retired_net, delta=0.01)


if __name__ == '__main__':
    unittest.main()
