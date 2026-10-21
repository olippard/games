"""Version 2: persistence, calendar statements, opening calibration and ownership."""

import contextlib
import copy
import io
import json
import math
import pathlib
import random
import tempfile
import unittest
from unittest.mock import patch

import utility
import utility_persistence as saves
import utility_reports as reports


class VersionTwoTests(unittest.TestCase):
    def setUp(self):
        rng = random.getstate()
        self.addCleanup(random.setstate, rng)
        stream = contextlib.redirect_stdout(io.StringIO())
        stream.__enter__()
        self.addCleanup(stream.__exit__, None, None, None)
        random.seed(42)
        self.s = utility.UtilityGameSession()
        self.p = self.s.player
        self.f = self.s.financials
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = pathlib.Path(self.temp.name) / 'test.gridline.json'

    def healthy_close(self, session=None):
        s = session or self.s
        s.player.annual_dividend_per_share = max(s.player.annual_dividend_per_share,
                                                s.player.stock_price * .035)
        result = s.advance_month()
        self.assertEqual(result, 'OK')

    def test_opening_calibration_across_company_sizes(self):
        for seed in range(40):
            random.seed(seed)
            s = utility.UtilityGameSession()
            p, f = s.player, s.financials
            self.assertAlmostEqual(p.total_debt() / p.book_equity(), 1.5)
            self.assertGreater(f.ttm_net_income, 0)
            self.assertTrue(9.79 <= p.stock_price / f.ttm_eps(p.shares_outstanding) <= 10.21)
            self.assertIn(s.credit.rating, ('BBB+', 'A-'))
            self.assertLess(s.economy.bond_rate(10, s.credit.spread), .08)
            self.assertEqual(s.regulator.current_retail_price, 150)
            self.assertTrue(all(r['balance']['net_plant'] > 0 for r in f.monthly_history))

    def test_saves_all_state_and_unknown_future_attributes(self):
        self.p.wholesale_trade(150, 'buy', self.s.economy)
        self.p.issue_bond(1_000_000, self.s.economy, '10yr', self.s.credit)
        self.p.future_feature = {'enabled': True, 'counter': 7, 'list': ['new', 2]}
        self.s.ui_state = {'history': [{'label': 'test', 'generation': 123}], 'event_log': 'history'}
        before = saves.encode_graph(self.s, self.s.save_classes())
        self.s.save_game(self.path)
        loaded = utility.UtilityGameSession.load_game(self.path)
        self.assertEqual(saves.encode_graph(loaded, loaded.save_classes()), before)
        self.assertIs(loaded.player.economy, loaded.economy)
        self.assertIs(loaded.game_state.economy, loaded.economy)
        self.assertEqual(loaded.player.future_feature, self.p.future_feature)
        self.assertEqual(loaded.player.pending_wholesale_commitment_mw, 150)

    def test_loading_continues_the_same_random_future(self):
        self.healthy_close()
        self.s.save_game(self.path)
        self.healthy_close()
        expected = saves.encode_graph(self.s, self.s.save_classes())
        loaded = utility.UtilityGameSession.load_game(self.path)
        self.healthy_close(loaded)
        self.assertEqual(saves.encode_graph(loaded, loaded.save_classes()), expected)

    def test_midgame_assets_policies_and_pending_ledgers_resume_together(self):
        self.p.cash = 30_000_000_000
        self.assertTrue(self.p.start_construction('battery'))
        self.p.ongoing_constructions[0]['turns_remaining'] = 1
        self.p.update_constructions()
        self.p.batteries[0]['stored_energy'] = 125
        self.p.batteries[0]['current_capacity'] = 350
        self.assertTrue(self.p.start_construction('nuclear'))
        self.p.ongoing_constructions[0]['turns_remaining'] = 37
        self.s.game_state.carbon_tax = 55
        self.p.shareholder_happiness = 48
        self.p.months_without_raise = 11
        self.p.trade_shares('issue', 1000, self.s.game_state)
        self.p.wholesale_trade(75, 'sell', self.s.economy)
        self.s.save_game(self.path)
        before = saves.encode_graph(self.s, self.s.save_classes())
        loaded = utility.UtilityGameSession.load_game(self.path)
        self.assertEqual(saves.encode_graph(loaded, loaded.save_classes()), before)
        self.assertEqual(loaded.player.batteries[0]['stored_energy'], 125)
        self.assertEqual(loaded.player.ongoing_constructions[0]['turns_remaining'], 37)
        self.healthy_close(loaded)
        expected = saves.encode_graph(loaded, loaded.save_classes())
        loaded_again = utility.UtilityGameSession.load_game(self.path)
        self.healthy_close(loaded_again)
        self.assertEqual(saves.encode_graph(loaded_again, loaded_again.save_classes()), expected)

    def test_infinity_ratios_roundtrip_as_valid_json(self):
        self.s.credit.interest_coverage = float('inf')
        self.s.save_game(self.path)
        self.assertNotIn('Infinity', self.path.read_text())
        loaded = utility.UtilityGameSession.load_game(self.path)
        self.assertEqual(loaded.credit.interest_coverage, float('inf'))

    def test_corrupt_or_future_save_does_not_change_random_state(self):
        self.s.save_game(self.path)
        original = json.loads(self.path.read_text())
        for invalid in ('future', 'bad-ref', 'missing-field', 'untrusted-type'):
            document = copy.deepcopy(original)
            if invalid == 'future':
                document['schema_version'] = 999
            elif invalid == 'bad-ref':
                document['graph']['root'] = {'$ref': -1}
            elif invalid == 'untrusted-type':
                document['graph']['objects'][0]['type'] = 'subprocess.Popen'
            else:
                record = next(r for r in document['graph']['objects'] if r['type'] == 'PlayerState')
                del record['fields']['cash']
            self.path.write_text(json.dumps(document))
            rng = random.getstate()
            with self.assertRaises(saves.SaveError):
                utility.UtilityGameSession.load_game(self.path)
            self.assertEqual(rng, random.getstate())

    def test_failed_atomic_replace_preserves_existing_save(self):
        self.s.save_game(self.path)
        original = self.path.read_bytes()
        with patch('utility_persistence.os.replace', side_effect=OSError('disk unavailable')):
            with self.assertRaises(OSError):
                self.s.save_game(self.path)
        self.assertEqual(original, self.path.read_bytes())
        self.assertEqual(list(self.path.parent.glob('*.tmp')), [])

    def test_four_full_years_and_quarters_are_available_at_start(self):
        for frequency in ('quarterly', 'annual'):
            periods = reports.periods(self.f, self.s.game_state, frequency)
            self.assertEqual(len(periods), 4)
            self.assertTrue(all('(est.)' in p['label'] for p in periods))
            self.assertEqual(periods[0]['end'], 11)  # December, pre-game year 0
            for report in periods:
                expected_months = 3 if frequency == 'quarterly' else 12
                self.assertEqual(report['end'] - report['start'] + 1, expected_months)

    def assert_statement_reconciles(self, record):
        i, b, c = record['income'], record['balance'], record['cash_flow']
        self.assertAlmostEqual(i['total_operating_revenue'] - i['cash_operating_expenses'], i['ebitda'], delta=.01)
        self.assertAlmostEqual(i['ebitda'] - i['depreciation_expense'], i['operating_income'], delta=.01)
        self.assertAlmostEqual(i['pretax_income'] - i['income_tax_expense'], i['net_profit'], delta=.01)
        self.assertAlmostEqual(b['assets'], b['debt'] + b['equity'], delta=.01)
        self.assertAlmostEqual(b['equity'], b['paid_in_capital'] + b['retained_earnings'] - b['treasury_stock'], delta=.01)
        self.assertAlmostEqual(c['ending_cash'] - c['beginning_cash'], c['net_cash_from_operations']
                               + c['net_cash_from_investing'] + c['net_cash_from_financing']
                               + c['cash_reconciliation_adjustment'], delta=.01)
        self.assertAlmostEqual(c['net_cash_from_operations'], c['net_profit'] + c['depreciation_expense']
                               - c['unusual_gain_loss'], delta=.01)

    def test_backfilled_ledgers_and_periods_reconcile(self):
        for record in self.f.monthly_history:
            self.assert_statement_reconciles(record)
        for frequency in ('quarterly', 'annual'):
            for record in reports.periods(self.f, self.s.game_state, frequency):
                self.assert_statement_reconciles(record)
        for before, after in zip(self.f.monthly_history, self.f.monthly_history[1:]):
            self.assertAlmostEqual(after['balance']['gross_plant'] - before['balance']['gross_plant'],
                                   after['cash_flow']['capital_expenditures'], delta=.01)
            self.assertAlmostEqual(after['balance']['equity'] - before['balance']['equity'],
                                   after['income']['net_profit'] - after['cash_flow']['dividend_payments']
                                   + after['cash_flow']['stock_issuance'], delta=.01)

    def test_periods_exclude_incomplete_quarters_and_use_closing_balances(self):
        self.healthy_close()  # February: Q1 incomplete
        self.assertEqual(reports.periods(self.f, self.s.game_state, 'quarterly')[0]['end'], 11)
        self.healthy_close()  # March: January estimate + February/March actual
        quarter = reports.periods(self.f, self.s.game_state, 'quarterly')[0]
        self.assertIn('Year 1 Q1 (mixed)', quarter['label'])
        self.assertEqual(quarter['estimated_months'], 1)
        months = [r for r in self.f.monthly_history if r['year'] == 1]
        self.assertAlmostEqual(quarter['income']['net_profit'], sum(r['income']['net_profit'] for r in months))
        self.assertEqual(quarter['balance']['cash'], self.p.cash)
        self.assertEqual(quarter['cash_flow']['beginning_cash'], months[0]['cash_flow']['beginning_cash'])
        self.assert_statement_reconciles(quarter)

    def test_last_four_full_years_roll_at_december_not_january(self):
        for _ in range(11):
            self.healthy_close()
        self.assertEqual(self.s.game_state.current_month, 12)
        annual = reports.periods(self.f, self.s.game_state, 'annual')
        self.assertIn('Year 1 (mixed)', annual[0]['label'])
        self.assertEqual(annual[0]['end'], 23)
        self.healthy_close()
        self.assertEqual(reports.periods(self.f, self.s.game_state, 'annual')[0]['end'], 23)

    def test_saved_history_is_immutable_when_live_accounts_change(self):
        self.healthy_close()
        before = copy.deepcopy(self.f.monthly_history[-1])
        self.p.cash += 100
        self.p.trade_shares('issue', 1000, self.s.game_state)
        self.assertEqual(self.f.monthly_history[-1], before)

    def test_share_trades_reconcile_and_change_shares_without_instant_price_gain(self):
        p = self.p
        p.cash = 10_000_000_000
        before = p.shares_outstanding, p.stock_price, p.paid_in_capital, p.cash
        self.assertTrue(p.trade_shares('issue', 1000, self.s.game_state))
        proceeds = 1000 * before[1] * .99
        self.assertEqual(p.shares_outstanding, before[0] + 1000)
        self.assertAlmostEqual(p.paid_in_capital, before[2] + proceeds, delta=.01)
        self.assertEqual(p.stock_price, before[1])
        self.assertTrue(p.trade_shares('buyback', 1000, self.s.game_state))
        cost = 1000 * before[1] * 1.01
        self.assertAlmostEqual(p.treasury_stock, cost)
        self.assertLess(p.cash, before[3])  # bid/ask spread prevents free round trips
        self.healthy_close()
        self.assertEqual(self.f.stock_issuance, proceeds)
        self.assertEqual(self.f.stock_buybacks, cost)
        self.assert_statement_reconciles(self.f.monthly_history[-1])

    def test_combined_annual_cap_cannot_be_recycled(self):
        p = self.p
        p.cash = 100_000_000_000
        cap = p.remaining_share_allowance()
        self.assertTrue(p.trade_shares('buyback', cap, self.s.game_state))
        self.assertEqual(p.remaining_share_allowance(), 0)
        self.assertFalse(p.trade_shares('issue', 1, self.s.game_state))
        p.reset_annual_share_allowance(1)
        self.assertEqual(p.remaining_share_allowance(), 0)
        p.reset_annual_share_allowance(2)
        self.assertGreater(p.remaining_share_allowance(), 0)
        self.assertLess(p.remaining_share_allowance() / p.shares_outstanding, .05)

    def test_share_trades_validate_cash_quantity_and_cap(self):
        p = self.p
        for quantity in (-1, 0, True, 1.2, float('nan'), p.remaining_share_allowance() + 1):
            self.assertFalse(p.trade_shares('issue', quantity, self.s.game_state))
        p.cash = 0
        self.assertFalse(p.trade_shares('buyback', 1, self.s.game_state))

    def test_weighted_shares_drive_period_and_ttm_eps(self):
        old_shares = self.p.shares_outstanding
        self.p.trade_shares('issue', 100_000, self.s.game_state)
        self.healthy_close()
        weighted = (old_shares * 11 + self.p.shares_outstanding) / 12
        self.assertAlmostEqual(self.f.ttm_eps(self.p.shares_outstanding), self.f.ttm_net_income / weighted)
        self.assertEqual(self.p.valuation_eps, self.f.ttm_eps(self.p.shares_outstanding))
        self.assertEqual(self.f.monthly_history[-1]['income']['weighted_shares'], self.p.shares_outstanding)

    def test_cut_penalty_cannot_be_undone_by_tanking_the_share_price(self):
        self.p.set_dividend(self.p.annual_dividend_per_share * .1)
        self.assertEqual(self.p.shareholder_happiness, 25)
        self.p.stock_price *= .01
        self.assertGreater(self.p.dividend_yield(), .03)
        self.p.review_dividend_policy(self.s.game_state)
        self.assertEqual(self.p.shareholder_happiness, 21)  # reference yield, not manipulated yield
        self.p.set_dividend(0)
        self.assertTrue(self.p.fired)
        turn = self.s.game_state.turn
        self.assertEqual(self.s.advance_month(), 'FIRED')
        self.assertEqual(self.s.game_state.turn, turn)

    def test_raise_rewards_are_monthly_not_button_click_rewards(self):
        before = self.p.shareholder_happiness
        for _ in range(10):
            self.p.set_dividend(self.p.annual_dividend_per_share * 1.001)
        self.assertEqual(self.p.shareholder_happiness, before)
        self.p.review_dividend_policy(self.s.game_state)
        self.assertLessEqual(self.p.shareholder_happiness, before + 4)

    def test_buyback_rewards_require_meaningful_size_and_stopping_has_no_penalty(self):
        p = self.p
        p.annual_dividend_per_share = 0
        p.stock_bought_since_close = p.share_trade_base_value * .002
        p.review_dividend_policy(self.s.game_state)
        self.assertEqual(p.shareholder_happiness, 72)  # -4 dividend +1 buyback
        p.stock_bought_since_close = 0
        self.s.game_state.turn += 1
        p.review_dividend_policy(self.s.game_state)
        self.assertEqual(p.shareholder_happiness, 68)  # only dividend penalty, no stopping penalty
        p.stock_bought_since_close = 1
        self.s.game_state.turn += 1
        p.review_dividend_policy(self.s.game_state)
        self.assertAlmostEqual(p.shareholder_happiness, 64, places=5)

    def test_repeated_issuance_is_unpopular_and_flat_dividends_slightly_hurt(self):
        p = self.p
        p.annual_dividend_per_share = 0
        p.stock_issued_since_close = p.share_trade_base_value * .002
        p.review_dividend_policy(self.s.game_state)
        self.assertEqual(p.shareholder_happiness, 68)
        self.s.game_state.turn += 1
        p.review_dividend_policy(self.s.game_state)
        self.assertEqual(p.shareholder_happiness, 60)
        p.stock_issued_since_close = 0
        p.months_without_raise = 12
        self.s.game_state.turn += 1
        p.review_dividend_policy(self.s.game_state)
        self.assertEqual(p.shareholder_happiness, 55.75)

    def test_learning_curve_reaches_target_after_ten_years_and_emits_news(self):
        e = self.s.economy
        e.inflation = 0
        news = []
        previous = self.p.construction_cost('solar')
        for month in range(1, 133):
            e.advance_price_level()
            quote = self.p.construction_cost('solar')
            self.assertLessEqual(quote, previous + .01)
            previous = quote
            if e.last_technology_event:
                news.append(month)
        self.assertEqual(news, list(range(12, 121, 12)))
        self.assertAlmostEqual(self.p.construction_cost('solar'), 330_000_000)
        self.assertAlmostEqual(self.p.construction_cost('wind'), 275_000_000)
        e.price_index = 1.5
        self.assertAlmostEqual(self.p.construction_cost('solar'), 495_000_000)


if __name__ == '__main__':
    unittest.main()
