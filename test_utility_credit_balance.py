"""Credit calibration, aged opening plant, and nuclear investment costs."""

import contextlib
import io
import random
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import utility


class CreditBalanceTests(unittest.TestCase):
    def setUp(self):
        rng_state = random.getstate()
        self.addCleanup(random.setstate, rng_state)
        output = contextlib.redirect_stdout(io.StringIO())
        output.__enter__()
        self.addCleanup(output.__exit__, None, None, None)
        random.seed(42)

    def credit_profile(self, leverage, coverage):
        debt = 1_000_000_000
        cash = 100_000_000 if leverage > 0 else debt
        equity = (debt - cash) / leverage if leverage > 0 else debt
        p = SimpleNamespace(cash=cash, bonds=[utility.Bond(debt, 0.05, 10, 0)],
                            book_equity=lambda: equity,
                            net_debt=lambda: debt - p.cash, total_debt=lambda: debt)
        f = SimpleNamespace(revenue=debt * 0.05 * coverage, operational_costs=0)
        credit = utility.CreditRating()
        credit.update(p, f)  # opening B does not count as a completed month
        return p, f, credit

    def test_stable_profiles_span_all_nondefault_grades(self):
        profiles = ((0.1, 10, 'AAA'), (0.5, 5, 'AA'), (1, 3, 'A'),
                    (1.8, 2.5, 'BBB'), (3, 1.5, 'BB-'), (4, 1, 'B'), (8, 0.5, 'CCC'))
        for leverage, coverage, expected in profiles:
            with self.subTest(expected=expected):
                p, f, credit = self.credit_profile(leverage, coverage)
                for _ in range(240):
                    credit.update(p, f)
                self.assertEqual(credit.rating, expected)
                self.assertGreaterEqual(credit._score, 0)
                self.assertLessEqual(credit._score, 100)

    def test_aaa_needs_twelve_strong_closes_not_just_a_high_score(self):
        p, f, credit = self.credit_profile(0.1, 10)
        credit._score = 100
        for _ in range(utility.CREDIT_AAA_QUALIFYING_MONTHS - 1):
            credit.update(p, f)
            self.assertEqual(credit.rating, 'AA+')
        credit.update(p, f)
        self.assertEqual(credit.rating, 'AAA')
        f.revenue = 1_000_000_000 * 0.05 * 3
        credit.update(p, f)
        self.assertNotEqual(credit.rating, 'AAA')
        self.assertEqual(credit.strong_months, 0)

    def test_extreme_leverage_and_losses_alone_are_not_default(self):
        p, f, credit = self.credit_profile(1_000_000, -1000)
        for _ in range(120):
            credit.update(p, f)
        self.assertEqual(credit.rating, 'CCC-')
        self.assertTrue(credit.can_borrow)
        self.assertGreaterEqual(credit._score, 0)

    def test_default_requires_persistent_shortfall_and_recovery_takes_time(self):
        p, f, credit = self.credit_profile(3, 0.5)
        p.cash = -100
        for _ in range(utility.CREDIT_DEFAULT_SHORTFALL_MONTHS - 1):
            credit.update(p, f)
            self.assertNotEqual(credit.rating, 'D')
        credit.update(p, f)
        self.assertEqual(credit.rating, 'D')
        self.assertFalse(credit.can_borrow)
        p.cash = 100_000_000
        for _ in range(utility.CREDIT_DEFAULT_RECOVERY_MONTHS - 1):
            credit.update(p, f)
            self.assertEqual(credit.rating, 'D')
        credit.update(p, f)
        self.assertEqual(credit.rating, 'CCC')
        self.assertTrue(credit.can_borrow)
        self.assertEqual(credit.distress_months, 0)

    def test_shortfall_counter_resets_when_cash_is_repaired(self):
        p, f, credit = self.credit_profile(2, 2)
        for _ in range(6):
            p.cash = -100
            credit.update(p, f)
            p.cash = 100
            credit.update(p, f)
        self.assertNotEqual(credit.rating, 'D')
        self.assertEqual(credit.distress_months, 0)

    def test_recovery_remains_slower_than_deterioration(self):
        p, f, credit = self.credit_profile(8, 0.5)
        credit._score = 90
        credit.update(p, f)
        downgrade = 90 - credit._score
        p.cash = p.total_debt()  # net debt is now zero
        f.revenue = 1_000_000_000
        before = credit._score
        credit.update(p, f)
        self.assertGreater(downgrade, credit._score - before)

    def test_coverage_uses_ttm_ebitda_not_a_single_month(self):
        p, f, credit = self.credit_profile(1, 0)
        f.ttm_ebitda = 250_000_000
        credit.update(p, f)
        self.assertEqual(credit.interest_coverage, 5)

    def test_opening_plants_have_consistent_age_cost_and_depreciation(self):
        for seed in range(40):
            random.seed(seed)
            p = utility.PlayerState()
            for asset in p.plant_assets:
                life = utility.ASSET_USEFUL_LIFE_YEARS[asset.plant_type] * 12
                fraction = asset.months_in_service / life
                self.assertGreaterEqual(fraction, 0.20)
                self.assertLessEqual(fraction, 0.65)
                self.assertAlmostEqual(asset.accumulated_depreciation,
                                       asset.original_cost * fraction, delta=0.01)
                self.assertGreater(asset.net_book_value, 0)
            self.assertGreater(p.book_equity(), 0)
            self.assertAlmostEqual(p.total_asset_value(), p.total_debt() + p.paid_in_capital,
                                   delta=0.01)
            self.assertEqual(p.capital_expenditures_since_close, 0)
            self.assertAlmostEqual(p.total_debt(), 2 * p.baseline_starting_debt, delta=0.01)

    def test_opening_debt_targets_aged_book_equity(self):
        p = utility.PlayerState()
        self.assertAlmostEqual(p.total_debt() / p.book_equity(), 1.5)
        self.assertGreaterEqual(p.book_equity(), utility.MIN_OPENING_BOOK_EQUITY - 0.01)
        self.assertGreater(p.accumulated_depreciation(), 0)
        self.assertAlmostEqual(p.gross_utility_plant() - p.accumulated_depreciation(),
                               p.net_utility_plant(), delta=0.01)

    def test_new_nuclear_costs_eighteen_billion_and_is_not_predepreciated(self):
        p = utility.PlayerState()
        self.assertEqual(p.construction_cost('nuclear'), 18_000_000_000)
        self.assertEqual(utility.GUI_BUILD_INFO['nuclear'][1], 18_000_000_000)
        p.cash = 21_000_000_000
        self.assertTrue(p.start_construction('nuclear'))
        self.assertEqual(p.cash, 3_000_000_000)
        self.assertEqual(p.ongoing_constructions[-1]['turns_remaining'], 72)
        p.ongoing_constructions[-1]['turns_remaining'] = 1
        p.update_constructions()
        asset = p.plant_assets[-1]
        self.assertEqual(asset.plant_type, 'nuclear')
        self.assertEqual(asset.original_cost, 18_000_000_000)
        self.assertEqual(asset.months_in_service, 0)
        self.assertEqual(asset.accumulated_depreciation, 0)
        self.assertAlmostEqual(asset.monthly_depreciation, 18_000_000_000 / 720)

    def test_inherited_depreciation_is_not_charged_again_at_first_close(self):
        s = utility.UtilityGameSession()
        p, f = s.player, s.financials
        opening_dep = p.accumulated_depreciation()
        monthly_dep = p.monthly_depreciation()
        opening_ebitda = f.trailing_ebitda[:]
        self.assertEqual(len(opening_ebitda), 12)
        s.advance_month()
        self.assertAlmostEqual(p.accumulated_depreciation(), opening_dep + monthly_dep,
                               delta=0.01)
        self.assertAlmostEqual(f.depreciation_expense, monthly_dep)
        self.assertEqual(f.trailing_ebitda, opening_ebitda[1:] + [f.ebitda])
        self.assertAlmostEqual(f.net_cash_from_operations + f.net_cash_from_investing
                               + f.net_cash_from_financing,
                               f.ending_cash - f.beginning_cash, delta=0.01)

    def test_ttm_operating_earnings_replace_estimates_and_stay_at_twelve(self):
        s = utility.UtilityGameSession()
        observed = []
        for _ in range(13):
            s.player.set_dividend(max(s.player.annual_dividend_per_share, s.player.stock_price * 0.03))
            self.assertEqual(s.advance_month(), 'OK')
            observed.append(s.financials.ebitda)
        self.assertEqual(s.financials.trailing_ebitda, observed[-12:])
        self.assertEqual(s.financials.ttm_ebitda, sum(observed[-12:]))


if __name__ == '__main__':
    unittest.main()
