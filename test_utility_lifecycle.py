"""Plant service limits, autonomous financing and unbiased opening utility sizes."""

import contextlib
import copy
import io
import json
import math
from pathlib import Path
import random
import tempfile
import unittest
from unittest.mock import patch

import utility as u
import utility_persistence as saves


class LifecycleTests(unittest.TestCase):
    def setUp(self):
        rng = random.getstate()
        self.addCleanup(random.setstate, rng)
        output = contextlib.redirect_stdout(io.StringIO())
        output.__enter__()
        self.addCleanup(output.__exit__, None, None, None)
        random.seed(42)
        self.s = u.UtilityGameSession(max_turns=2000)
        self.c = self.s.regions[1]['operator']
        self.p = self.s.player
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'lifecycle.gridline.json'

    def empty_fleet(self, player):
        player.power_plants = dict.fromkeys(player.power_plants, 0)
        player.plant_assets = []
        player.batteries = []
        player.ongoing_constructions = []
        player._sync_plant_book_values()

    def add_unit(self, player, kind, age=0):
        if kind == 'battery':
            player.batteries.append(dict(max_capacity=400, current_capacity=300,
                                        max_power=100, stored_energy=123))
        else:
            player.power_plants[kind] += 1
        return player._add_plant_asset(kind, player.construction_cost(kind), age)

    def assert_reconciled(self, company):
        f, p = company.financials, company.player
        self.assertGreaterEqual(p.cash, 0)
        self.assertAlmostEqual(f.cash_reconciliation_adjustment, 0, delta=.01)
        self.assertAlmostEqual(f.beginning_cash + f.net_cash_from_operations
                               + f.net_cash_from_investing + f.net_cash_from_financing,
                               p.cash, delta=.01)
        self.assertEqual(f.monthly_history[-1]['balance']['cash'], p.cash)
        self.assertEqual(f.monthly_history[-1]['balance']['debt'], p.total_debt())

    def test_operating_limits_are_distinct_from_depreciation_lives(self):
        expected = {'coal': 50, 'natural_gas': 50, 'nuclear': 100,
                    'solar': 35, 'wind': 35, 'hydro': 100, 'battery': 20}
        for kind, years in expected.items():
            asset = u.PlantAsset(1, kind, 1e9)
            self.assertEqual(asset.operating_life_months, years * 12)
            self.assertEqual(asset.monthly_depreciation, 1e9 / (u.ASSET_USEFUL_LIFE_YEARS[kind] * 12))

    def test_every_technology_expires_at_the_boundary_not_early(self):
        for kind, years in u.PLANT_OPERATING_LIFE_YEARS.items():
            with self.subTest(kind=kind):
                self.empty_fleet(self.p)
                old = self.add_unit(self.p, kind, years * 12 - 1)
                new = self.add_unit(self.p, kind)
                self.assertEqual(self.p.retire_expired_plants(), [])
                self.p.monthly_depreciation(post=True)
                self.assertNotIn(old, self.p.plant_assets)
                self.assertIn(new, self.p.plant_assets)
                self.assertEqual(new.months_in_service, 1)
                if kind == 'battery':
                    self.assertEqual(len(self.p.batteries), 1)
                else:
                    self.assertEqual(self.p.power_plants[kind], 1)

    def test_expired_battery_removes_matching_storage_not_newest(self):
        self.empty_fleet(self.p)
        self.add_unit(self.p, 'battery', 240)
        self.p.batteries[0]['stored_energy'] = 1
        self.add_unit(self.p, 'battery')
        self.p.batteries[1]['stored_energy'] = 234
        self.p.retire_expired_plants()
        self.assertEqual(self.p.batteries[0]['stored_energy'], 234)

    def test_forecast_removes_expired_capacity_and_is_read_only(self):
        self.empty_fleet(self.p)
        self.add_unit(self.p, 'natural_gas', 599)
        before = saves.encode_graph(self.s, self.s.save_classes())
        rows = self.s.grid.forecast_demand(self.p, self.s.game_state, 3)
        self.assertEqual([r['firm_supply'] for r in rows], [500, 0, 0])
        self.assertEqual(saves.encode_graph(self.s, self.s.save_classes()), before)

    def test_overage_units_do_not_generate_when_play_resumes(self):
        self.empty_fleet(self.p)
        self.add_unit(self.p, 'coal', 601)
        self.p.cash = self.s.financials.ending_cash = 1e12
        self.s.advance_month()
        self.assertEqual(self.s.grid.total_generation, 0)
        self.assertEqual(self.s.financials.coal_emissions_tons, 0)
        self.assertEqual(self.p.power_plants['coal'], 0)

    def test_final_service_month_retirement_reconciles_without_rewriting_history(self):
        self.empty_fleet(self.p)
        old = self.add_unit(self.p, 'coal', 599)
        self.p.cash = self.s.financials.ending_cash = 1e12
        history = copy.deepcopy(self.s.financials.monthly_history)
        self.s.advance_month()
        self.assertEqual(self.s.grid.total_generation, u.COAL_PLANT_CAPACITY)
        self.assertNotIn(old, self.p.plant_assets)
        self.assertEqual(self.s.financials.monthly_history[:-1], history)
        self.assert_reconciled(self.s)
        self.s.advance_month()
        self.assertEqual(self.s.grid.total_generation, 0)

    def test_end_of_life_warns_before_shutdown(self):
        self.empty_fleet(self.p)
        self.add_unit(self.p, 'nuclear', 1200 - 85)
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.p.monthly_depreciation(post=True)
        self.assertIn('84 months', output.getvalue())

    def test_high_carbon_retires_fossil_fleet_and_builds_clean_power(self):
        p = self.c.player
        self.empty_fleet(p)
        self.add_unit(p, 'coal')
        self.add_unit(p, 'natural_gas')
        p.cash = self.c.financials.ending_cash = 10e9
        p.reset_monthly_ledgers()
        self.s.game_state.carbon_tax = 1000
        self.c.advance_month(self.s.game_state)
        self.assertEqual(p.power_plants['coal'], 0)
        self.assertEqual(p.power_plants['natural_gas'], 0)
        self.assertGreater(len(p.ongoing_constructions), 0)
        self.assertTrue(all(project['type'] in ('solar', 'wind', 'hydro', 'nuclear')
                            for project in p.ongoing_constructions))
        self.assertEqual(self.c.financials.total_emissions_tons, 0)
        self.assert_reconciled(self.c)

    def test_competitor_plans_to_replace_units_before_they_expire(self):
        p = self.c.player
        self.empty_fleet(p)
        self.add_unit(p, 'nuclear', 1190)
        p.cash = 30e9
        self.c.plan_portfolio()
        self.assertGreater(len(p.ongoing_constructions), 0)

    def test_cash_funded_investment_does_not_require_a_good_rating(self):
        self.empty_fleet(self.c.player)
        self.c.player.cash = 30e9
        self.c.credit._set_rating('D')
        self.c.plan_portfolio()
        self.assertGreater(len(self.c.player.ongoing_constructions), 0)

    def test_weak_earnings_prevent_borrowing_for_more_construction(self):
        p = self.c.player
        self.empty_fleet(p)
        p.cash = 0
        p.bonds = [u.Bond(100e9, .10, 20, 0)]
        p.monthly_borrowing_limit = 100e9
        self.c.financials.trailing_ebitda = [1e6] * 12
        before = p.total_debt()
        self.c.plan_portfolio()
        self.assertEqual(p.total_debt(), before)
        self.assertEqual(p.ongoing_constructions, [])

    def test_construction_savings_must_cover_new_interest(self):
        p = self.c.player
        self.empty_fleet(p)
        p.cash = 0
        p.bonds = []
        p.monthly_borrowing_limit = 100e9
        self.c.financials.trailing_ebitda = [10e9] * 12
        with patch.object(self.s.economy, 'bond_rate', return_value=.30):
            self.c.plan_portfolio()
        self.assertEqual(p.bonds, [])
        self.assertEqual(p.ongoing_constructions, [])

    def test_essential_shortfall_is_borrowed_and_reconciles_even_in_credit_crunch(self):
        p = self.c.player
        p.cash = self.c.financials.ending_cash = 0
        p.monthly_borrowing_limit = 0
        self.c.credit._set_rating('D')
        self.s.economy.regime = 'recession'
        old = u.Bond(50e9, .06, 1, 0)
        old.months_remaining = 1
        p.bonds = [old]
        old_history = copy.deepcopy(self.c.financials.monthly_history)
        self.c.advance_month(self.s.game_state)
        self.assertNotIn(old, p.bonds)
        support = [b for b in p.bonds if getattr(b, 'purpose', '') == 'regional_liquidity']
        self.assertTrue(support)
        self.assertGreater(support[0].annual_rate, self.s.economy.interest_rate)
        self.assertEqual(self.c.financials.debt_issuance, sum(b.principal for b in support))
        self.assertEqual(self.c.financials.debt_repayments, 50e9)
        self.assertEqual(self.c.financials.monthly_history[:-1], old_history)
        self.assert_reconciled(self.c)

    def test_no_loan_or_balance_change_without_a_shortfall(self):
        before = saves.encode_graph(self.c, self.s.save_classes())
        self.assertEqual(self.c.ensure_liquidity(), 0)
        self.assertEqual(saves.encode_graph(self.c, self.s.save_classes()), before)
        self.assertFalse(hasattr(self.p, 'ensure_liquidity'))

    def test_ordinary_bonds_are_used_before_continuity_facility(self):
        p = self.c.player
        p.cash = -1e6
        before = p.total_debt()
        self.c.ensure_liquidity()
        self.assertEqual(p.cash, 0)
        self.assertEqual(p.total_debt(), before + 1e6)
        self.assertNotEqual(getattr(p.bonds[-1], 'purpose', ''), 'regional_liquidity')

    def test_multiyear_extreme_carbon_stress_keeps_finances_finite_and_cash_nonnegative(self):
        self.s.game_state.carbon_tax = 2000
        self.c.player.cash = self.c.financials.ending_cash = -5e9
        for month in range(240):
            self.s.economy.update()
            self.s.game_state.advance_turn()
            self.c.advance_month(self.s.game_state)
            self.assertTrue(math.isfinite(self.c.player.total_debt()))
            self.assertTrue(math.isfinite(self.c.player.company_value))
            self.assert_reconciled(self.c)
        self.assertEqual(self.c.player.power_plants['coal'], 0)
        self.assertLess(self.c.player.total_debt(), max(self.c.financials.ttm_ebitda, 1) * 12)
        self.assertGreater(sum(self.c.player.power_plants[k] for k in ('solar', 'wind', 'hydro', 'nuclear')), 0)

    def test_acquisition_inherits_continuity_debt_and_service_ages(self):
        self.c.player.cash = -10e9
        self.c.player.monthly_borrowing_limit = 0
        self.c.ensure_liquidity()
        support = self.c.player.bonds[-1]
        ages = [(a.months_in_service, a.operating_life_months) for a in self.c.player.plant_assets]
        self.p.cash = 1e13
        self.s.buy_utility(1)
        self.assertIn(support, self.p.bonds)
        self.assertEqual([(a.months_in_service, a.operating_life_months)
                          for a in self.p.plant_assets[-len(ages):]], ages)

    def test_roundtrip_preserves_lifetimes_and_deterministic_ai_financing(self):
        self.p.cash = self.s.financials.ending_cash = 1e12
        self.c.player.bonds[0].months_remaining = 1
        self.c.player.cash = 0
        self.c.financials.ending_cash = 0
        self.s.save_game(self.path)
        before = saves.encode_graph(self.s, self.s.save_classes())
        self.s.advance_month()
        after = saves.encode_graph(self.s, self.s.save_classes())
        loaded = u.UtilityGameSession.load_game(self.path)
        self.assertEqual(saves.encode_graph(loaded, loaded.save_classes()), before)
        loaded.advance_month()
        self.assertEqual(saves.encode_graph(loaded, loaded.save_classes()), after)

    def test_schema_two_migration_keeps_history_ages_and_repairs_cash_with_real_debt(self):
        self.s.save_game(self.path)
        doc = json.loads(self.path.read_text())
        doc['schema_version'] = 2
        objects = doc['graph']['objects']
        for record in objects:
            if record['type'] == 'PlantAsset':
                del record['fields']['operating_life_months']
        company = next(r['fields'] for r in objects if r['type'] == 'RegionalUtility')
        owner = objects[company['player']['$ref']]['fields']
        owner['cash'] = -10e9
        owner['monthly_borrowing_limit'] = 0
        financials = objects[company['financials']['$ref']]['fields']
        financials['ending_cash'] = -10e9
        self.path.write_text(json.dumps(doc))
        expected_rng = saves.decode_graph(doc['random_state'], self.s.save_classes())
        loaded = u.UtilityGameSession.load_game(self.path)
        rival = loaded.regions[1]['operator']
        self.assertEqual(random.getstate(), expected_rng)
        self.assertEqual(rival.player.cash, 0)
        self.assertEqual(rival.player.bonds[-1].principal, 10e9)
        self.assertEqual(rival.financials.monthly_history, self.c.financials.monthly_history)
        for old, new in zip(self.c.player.plant_assets, rival.player.plant_assets):
            self.assertEqual(vars(old), vars(new))
        rival.advance_month(loaded.game_state)
        self.assert_reconciled(rival)

    def test_invalid_service_limit_does_not_replace_rng(self):
        self.s.save_game(self.path)
        doc = json.loads(self.path.read_text())
        next(r for r in doc['graph']['objects'] if r['type'] == 'PlantAsset')['fields']['operating_life_months'] = -1
        self.path.write_text(json.dumps(doc))
        before = random.getstate()
        with self.assertRaises(saves.SaveError):
            u.UtilityGameSession.load_game(self.path)
        self.assertEqual(random.getstate(), before)

    def test_all_ten_sizes_use_the_same_distribution(self):
        with patch('utility.random.uniform', wraps=random.uniform) as draw:
            game = u.UtilityGameSession()
        scale_draws = [call for call in draw.call_args_list
                       if call.args == (u.MIN_COMPANY_SIZE, u.MAX_COMPANY_SIZE)]
        self.assertEqual(len(scale_draws), 10)
        for region in game.regions:
            self.assertGreaterEqual(region['base_mw'], 1000)
            self.assertLessEqual(region['base_mw'], 10000)

    def test_player_can_start_anywhere_in_the_size_range_not_fixed_in_middle(self):
        ranks = []
        for seed in range(50):
            random.seed(seed)
            game = u.UtilityGameSession()
            size = game.player.base_territory_mw
            ranks.append(1 + sum(r['base_mw'] > size for r in game.regions[1:]))
        self.assertEqual(min(ranks), 1)
        self.assertEqual(max(ranks), 10)
        self.assertGreater(sum(ranks) / len(ranks), 4)
        self.assertLess(sum(ranks) / len(ranks), 7)


if __name__ == '__main__':
    unittest.main()
