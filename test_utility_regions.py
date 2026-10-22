"""Regional simulation, takeovers, macroeconomic shocks and schema-1 upgrades."""

import contextlib
import copy
import io
import json
from pathlib import Path
import random
import tempfile
import unittest
from unittest.mock import patch

import utility as u
import utility_persistence as saves
import utility_reports as reports


class RegionalTests(unittest.TestCase):
    def setUp(self):
        rng = random.getstate()
        self.addCleanup(random.setstate, rng)
        output = contextlib.redirect_stdout(io.StringIO())
        output.__enter__()
        self.addCleanup(output.__exit__, None, None, None)
        random.seed(42)
        self.s = u.UtilityGameSession()
        self.p, self.e = self.s.player, self.s.economy
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'world.gridline.json'

    def fund_buyer(self):
        self.p.cash = 1e12
        self.s.financials.ending_cash = self.p.cash

    def close(self, session=None):
        s = session or self.s
        s.player.annual_dividend_per_share = max(s.player.annual_dividend_per_share,
                                                s.player.stock_price * .04)
        self.assertEqual(s.advance_month(), 'OK')

    def snapshot(self):
        return saves.encode_graph(self.s, self.s.save_classes())

    def test_ten_varied_regions_partition_the_map(self):
        regions = self.s.regions
        self.assertEqual(len(regions), 10)
        self.assertEqual(sum(r['owned'] for r in regions), 1)
        self.assertEqual(len({r['name'] for r in regions}), 10)
        self.assertAlmostEqual(sum(r['area_km2'] for r in regions), 500_000)
        self.assertGreater(max(r['area_km2'] for r in regions), min(r['area_km2'] for r in regions) * 1.5)
        for region in regions[1:]:
            c = region['operator']
            self.assertIs(c.player.economy, self.e)
            self.assertGreater(c.player.net_utility_plant(), 0)
            self.assertGreater(c.player.total_debt(), 0)

    def test_map_comparison_and_quotes_do_not_change_state_or_randomness(self):
        before, rng = self.snapshot(), random.getstate()
        self.assertEqual(len(self.s.competitor_rows()), 10)
        self.s.acquisition_quote(1)
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(random.getstate(), rng)

    def test_competitors_invest_borrow_and_reprice_over_time(self):
        before = self.s.competitor_rows()
        self.fund_buyer()
        for _ in range(24):
            self.close()
        after = self.s.competitor_rows()
        for a, b in zip(before[1:], after[1:]):
            for field in ('market_cap', 'assets', 'liabilities', 'demand'):
                self.assertNotEqual(a[field], b[field])
            c = self.s.regions[b['region_id']]['operator']
            self.assertAlmostEqual(c.player.total_asset_value(), c.player.total_debt() + c.player.book_equity())
        self.assertTrue(any(b['assets'] > a['assets'] for a, b in zip(before[1:], after[1:])))

    def test_takeovers_cost_a_substantial_premium_and_include_assumed_debt(self):
        quote = self.s.acquisition_quote(1)
        target = quote['region']['operator'].player
        self.assertGreaterEqual(quote['price'], target.company_value * 1.4)
        self.assertGreaterEqual(quote['price'], target.book_equity() * 1.15)
        self.assertAlmostEqual(quote['fees'], quote['price'] * .02)
        self.assertEqual(quote['assumed_debt'], target.total_debt())

    def test_rejected_acquisition_is_atomic(self):
        self.p.cash = 0
        before = self.snapshot()
        with self.assertRaises(ValueError):
            self.s.buy_utility(1)
        self.assertEqual(before, self.snapshot())
        for invalid in (float('nan'), -1, True, self.s.acquisition_quote(1)['financing_limit'] + 1):
            with self.assertRaises(ValueError):
                self.s.buy_utility(1, invalid)
            self.assertEqual(before, self.snapshot())

    def test_acquisition_transfers_complete_assets_contracts_and_liabilities(self):
        self.fund_buyer()
        target = self.s.regions[1]['operator']
        other = target.player
        other.cash += 2e9
        other.start_construction('solar')
        other.batteries.append(dict(max_capacity=400, current_capacity=350, max_power=100, stored_energy=123))
        other._add_plant_asset('battery', u.BATTERY_CONSTRUCTION_COST)
        other.wholesale_commitment_mw = 75
        other.pending_wholesale_commitment_mw = 90
        self.p.wholesale_commitment_mw = 25
        self.p.pending_wholesale_commitment_mw = 30
        expected_assets = len(self.p.plant_assets) + len(other.plant_assets)
        expected_plants = {k: self.p.power_plants[k] + other.power_plants[k] for k in self.p.power_plants}
        debt = self.p.total_debt() + other.total_debt()
        book_equity = self.p.book_equity()
        demand = self.p.expected_demand(self.s.game_state) + other.expected_demand(target.game_state)
        assets = copy.deepcopy(other.plant_assets)
        bonds = [(b.principal, b.annual_rate, b.months_remaining) for b in other.bonds]
        self.assertTrue(self.s.buy_utility(1))
        self.assertEqual(len(self.p.plant_assets), expected_assets)
        self.assertEqual(self.p.power_plants, expected_plants)
        self.assertEqual(self.p.total_debt(), debt)
        self.assertEqual(self.p.batteries[-1]['stored_energy'], 123)
        self.assertEqual(self.p.ongoing_constructions[-1]['type'], 'solar')
        self.assertEqual(self.p.wholesale_commitment_mw, 100)
        self.assertEqual(self.p.pending_wholesale_commitment_mw, 120)
        self.assertAlmostEqual(self.p.book_equity(), book_equity, delta=.01)
        self.assertAlmostEqual(self.p.expected_demand(self.s.game_state), demand)
        self.assertEqual(len({a.asset_id for a in self.p.plant_assets}), expected_assets)
        for before, after in zip(assets, self.p.plant_assets[-len(assets):]):
            self.assertEqual((before.original_cost, before.accumulated_depreciation, before.months_in_service),
                             (after.original_cost, after.accumulated_depreciation, after.months_in_service))
        self.assertEqual([(b.principal, b.annual_rate, b.months_remaining) for b in self.p.bonds[-len(bonds):]], bonds)
        self.assertEqual(other.bonds, [])
        self.assertEqual(other.plant_assets, [])
        self.assertEqual(other.cash, 0)
        self.assertTrue(target.acquired)
        with self.assertRaises(ValueError):
            self.s.buy_utility(1)

    def test_acquisition_must_cover_target_cash_shortfalls(self):
        target = self.s.regions[1]['operator'].player
        target.cash = -1e9
        quote = self.s.acquisition_quote(1)
        self.p.cash = quote['total']
        before = self.snapshot()
        with self.assertRaises(ValueError):
            self.s.buy_utility(1)
        self.assertEqual(before, self.snapshot())

    def test_acquisition_financing_is_additional_but_only_drawn_at_closing(self):
        self.fund_buyer()
        quote = max((self.s.acquisition_quote(i) for i in range(1, 10)), key=lambda q: q['financing_limit'])
        cap = self.p.remaining_borrowing_capacity()
        amount = quote['financing_limit']
        self.assertGreater(amount, cap)
        self.s.buy_utility(quote['region']['id'], amount)
        self.assertEqual(self.p.acquisition_debt_issued_since_close, amount)
        self.assertEqual(self.p.remaining_borrowing_capacity(), cap)
        self.assertEqual(self.p.debt_issued_since_close, amount)
        self.assertTrue(any(b.principal == amount and b.annual_rate == quote['rate'] for b in self.p.bonds))

    def test_recession_halves_ordinary_credit_and_blocks_special_financing(self):
        normal = self.p.remaining_borrowing_capacity()
        self.e.regime = 'recession'
        self.assertEqual(self.p.remaining_borrowing_capacity(), normal / 2)
        self.assertIsNone(self.p.issue_bond(normal / 2 + 1, self.e, '10yr', self.s.credit))
        self.assertIsNone(self.p.emergency_loan(normal / 2 + 1))
        self.assertEqual(self.s.acquisition_quote(1)['financing_limit'], 0)
        before = self.snapshot()
        with self.assertRaises(ValueError):
            self.s.buy_utility(1, 1)
        self.assertEqual(self.snapshot(), before)
        # Cash acquisitions are still allowed in a recession.
        self.fund_buyer()
        self.assertTrue(self.s.buy_utility(1, 0))

    def test_acquisition_cash_flow_reconciles_and_old_reports_stay_immutable(self):
        self.fund_buyer()
        old_reports = copy.deepcopy(self.s.financials.monthly_history)
        quote = self.s.acquisition_quote(1)
        self.s.buy_utility(1, quote['financing_limit'])
        self.assertEqual(self.s.financials.monthly_history, old_reports)
        self.close()
        f = self.s.financials
        self.assertAlmostEqual(f.acquisition_spending, quote['total'] - quote['acquired_cash'])
        self.assertEqual(f.debt_issuance, quote['financing_limit'])
        self.assertAlmostEqual(f.ending_cash - f.beginning_cash,
                               f.net_cash_from_operations + f.net_cash_from_investing + f.net_cash_from_financing, delta=.01)
        self.assertAlmostEqual(f.cash_reconciliation_adjustment, 0, delta=.01)
        balance = reports.balance_snapshot(self.p)
        self.assertEqual(balance['goodwill'], self.p.goodwill)
        self.assertAlmostEqual(balance['assets'], balance['cash'] + balance['net_plant']
                               + balance['construction'] + balance['goodwill'], delta=.01)

    def test_acquired_world_roundtrip_and_deterministic_continuation(self):
        self.fund_buyer()
        self.s.buy_utility(1)
        self.s.save_game(self.path)
        before = self.snapshot()
        self.close()
        expected = self.snapshot()
        loaded = u.UtilityGameSession.load_game(self.path)
        self.assertEqual(saves.encode_graph(loaded, loaded.save_classes()), before)
        self.close(loaded)
        self.assertEqual(saves.encode_graph(loaded, loaded.save_classes()), expected)

    def test_original_schema_one_fixture_migrates_without_rerolling_rng_or_assets(self):
        path = Path(__file__).parent / 'tests' / 'fixtures' / 'schema1_save.json'
        document = json.loads(path.read_text())
        records = document['graph']['objects']
        original = next(r['fields'] for r in records if r['type'] == 'PlayerState')
        expected_rng = saves.decode_graph(document['random_state'], u.UtilityGameSession.save_classes())
        loaded = u.UtilityGameSession.load_game(path)
        self.assertEqual(random.getstate(), expected_rng)
        self.assertEqual(loaded.player.cash, original['cash'])
        self.assertEqual(loaded.player.power_plants, original['power_plants'])
        self.assertEqual(len(loaded.regions), 10)
        self.assertEqual(loaded.regulator.current_retail_price, 150)
        self.assertEqual(loaded.player.goodwill, 0)
        loaded.save_game(self.path)
        self.assertEqual(json.loads(self.path.read_text())['schema_version'], saves.SCHEMA_VERSION)
        self.close(loaded)

    def test_migration_freezes_inflated_tariff_and_cancels_old_exports(self):
        path = Path(__file__).parent / 'tests' / 'fixtures' / 'schema1_save.json'
        document = json.loads(path.read_text())
        for record in document['graph']['objects']:
            if record['type'] == 'Economy':
                record['fields']['price_index'] = 1.4
            if record['type'] == 'PlayerState':
                record['fields']['wholesale_commitment_mw'] = -100
                record['fields']['pending_wholesale_commitment_mw'] = -200
        self.path.write_text(json.dumps(document))
        loaded = u.UtilityGameSession.load_game(self.path)
        self.assertEqual(loaded.regulator.current_retail_price, 210)
        loaded.economy.price_index = 1.6
        self.assertEqual(loaded.regulator.current_retail_price, 210)
        self.assertEqual(loaded.player.wholesale_commitment_mw, 0)
        self.assertEqual(loaded.player.pending_wholesale_commitment_mw, 0)

    def test_invalid_regional_save_does_not_change_running_random_state(self):
        self.s.save_game(self.path)
        document = json.loads(self.path.read_text())
        root = next(r for r in document['graph']['objects'] if r['type'] == 'UtilityGameSession')
        root['fields']['regions'][1]['id'] = 0
        self.path.write_text(json.dumps(document))
        rng = random.getstate()
        with self.assertRaises(saves.SaveError):
            u.UtilityGameSession.load_game(self.path)
        self.assertEqual(random.getstate(), rng)

    def test_long_rates_remember_a_sustained_high_rate_period(self):
        self.e.long_rate_anchor = .10
        self.e.interest_rate = .02
        self.e.regime = 'recession'
        with patch('utility.random.random', return_value=.5):
            self.e.update()
        self.assertGreater(self.e.bond_rate(20, 0), self.e.bond_rate(.5, 0) + .03)
        self.assertGreater(self.e.long_rate_anchor, .095)

    def test_deflation_is_rare_and_business_cycles_are_irregular(self):
        random.seed(90)
        e = u.Economy()
        deflationary = 0
        durations, duration, previous = [], 0, e.regime
        for _ in range(12000):
            e.update(advance_prices=False)
            deflationary += e.inflation < 0
            duration += 1
            if e.regime != previous:
                durations.append(duration)
                duration = 0
                previous = e.regime
        self.assertGreater(deflationary, 0)
        self.assertLess(deflationary / 12000, .04)
        self.assertGreater(len(set(durations)), 20)

    def test_deflation_reduces_prices_but_does_not_automatically_change_tariffs(self):
        self.e.deflation_months = 3
        self.e.update()
        self.assertLess(self.e.inflation, 0)
        self.assertLess(self.e.price_index, 1)
        self.assertEqual(self.s.regulator.current_retail_price, 150)

    def test_cycle_changes_equity_value_with_identical_earnings(self):
        prices = []
        for regime in ('recession', 'slowdown', 'recovery', 'expansion'):
            p = copy.deepcopy(self.p)
            self.e.regime = regime
            with patch('utility.random.uniform', return_value=0):
                p.update_stock_price(self.e, self.s.financials.ttm_net_income)
            prices.append(p.stock_price)
        self.assertEqual(prices, sorted(prices))
        self.assertGreater(prices[-1], prices[0])

    def test_small_recurring_profit_qualifies_but_retirement_loss_cannot(self):
        f, regulator = self.s.financials, self.s.regulator
        f.total_operating_revenue = 100
        f.interest_expense = 10
        f.operating_income = 15  # small positive recurring margin
        with patch('utility.random.random', return_value=0):
            self.assertTrue(regulator.request_increase(self.p, f, self.e, 1, .05))
        f.operating_income = 50
        f.net_profit = -1e9  # accounting loss from an asset retirement
        f.unusual_gain_loss = -1e9
        rate = regulator.current_retail_price
        with patch('utility.random.random', return_value=0):
            self.assertFalse(regulator.request_increase(self.p, f, self.e, 14, .05))
        self.assertEqual(regulator.current_retail_price, rate)

    def test_retirement_writeoff_does_not_worsen_credit_leverage(self):
        p, f, credit = self.p, self.s.financials, self.s.credit
        credit.update(p, f)
        leverage = credit.net_leverage
        equity = p.book_equity()
        kind = next(kind for kind, count in p.power_plants.items() if count)
        p.decommission_plant(kind)
        self.assertLess(p.book_equity(), equity)
        self.assertGreater(p.retirement_credit_adjustment, 0)
        credit.update(p, f)
        self.assertLessEqual(credit.net_leverage, leverage)

    def test_new_fleet_needs_capacity_for_seasonal_peak(self):
        for seed in range(30):
            random.seed(seed)
            p = u.PlayerState()
            firm = u.PowerGrid().firm_capacity(p)
            self.assertLessEqual(firm, p.base_territory_mw * 1.35)
            self.assertGreater(firm, p.base_territory_mw * 1.35 - 650)

    def test_all_new_plant_prices_are_doubled(self):
        expected = {'coal': 6e9, 'natural_gas': 2e9, 'nuclear': 18e9, 'solar': 1.2e9,
                    'wind': .9e9, 'hydro': 1.3e9, 'battery': .3e9}
        for kind, value in expected.items():
            self.assertEqual(self.p.construction_cost(kind), value)


if __name__ == '__main__':
    unittest.main()
