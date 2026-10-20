"""Regression checks for borrowing limits and the borrow/downgrade/buyback loop."""

import contextlib
import copy
import io
import random
import unittest
from types import SimpleNamespace

import utility


class FinancingTests(unittest.TestCase):
    def setUp(self):
        rng_state = random.getstate()
        self.addCleanup(random.setstate, rng_state)
        self.output = contextlib.redirect_stdout(io.StringIO())
        self.output.__enter__()
        self.addCleanup(self.output.__exit__, None, None, None)
        random.seed(42)
        self.session = utility.UtilityGameSession()
        self.player = self.session.player
        self.credit = self.session.credit
        self.economy = self.session.economy

    def issue(self, amount):
        return self.player.issue_bond(amount, self.economy, '10yr', self.credit)

    def test_initial_allowance_excludes_cash_and_inherited_bonds(self):
        p = self.player
        self.assertGreater(p.total_debt(), 0)
        self.assertGreater(p.cash, 0)
        self.assertEqual(p.debt_issued_since_close, 0)
        expected = round((p.net_utility_plant() + p.construction_work_in_progress())
                         * utility.MONTHLY_BORROWING_ASSET_FRACTION, 2)
        self.assertEqual(p.remaining_borrowing_capacity(), expected)

    def test_multiple_bonds_and_emergency_loans_share_one_cap(self):
        p = self.player
        cap = p.monthly_borrowing_limit
        self.assertIsNotNone(self.issue(cap * 0.4))
        self.assertIsNotNone(p.emergency_loan(cap * 0.2))
        self.assertIsNotNone(self.issue(p.remaining_borrowing_capacity()))
        cash, debt = p.cash, p.total_debt()
        self.assertEqual(p.remaining_borrowing_capacity(), 0)
        self.assertIsNone(self.issue(1))
        self.assertIsNone(p.emergency_loan(1))
        self.assertEqual((p.cash, p.total_debt()), (cash, debt))

    def test_invalid_or_oversized_requests_do_not_mutate_accounts(self):
        p = self.player
        before = (p.cash, p.total_debt(), p.remaining_borrowing_capacity())
        invalid = (0, -1, float('nan'), float('inf'), -float('inf'),
                   p.monthly_borrowing_limit + 1, '1000', True)
        for amount in invalid:
            with self.subTest(amount=amount):
                self.assertIsNone(self.issue(amount))
                self.assertIsNone(p.emergency_loan(amount))
                self.assertEqual(
                    (p.cash, p.total_debt(), p.remaining_borrowing_capacity()), before
                )

    def test_borrowed_cash_and_new_projects_cannot_expand_current_cap(self):
        p = self.player
        original_cap = p.monthly_borrowing_limit
        original_base = p.borrowing_asset_base
        self.assertIsNotNone(self.issue(original_cap / 2))
        self.assertTrue(p.start_construction('solar'))
        self.assertGreater(p.construction_work_in_progress(), 0)
        self.assertEqual(p.monthly_borrowing_limit, original_cap)
        self.assertEqual(p.borrowing_asset_base, original_base)
        self.assertEqual(p.remaining_borrowing_capacity(), original_cap / 2)

    def test_buyback_does_not_replenish_allowance(self):
        p = self.player
        bond = self.issue(p.monthly_borrowing_limit)
        self.assertTrue(p.buy_back_bond(bond, self.economy, self.credit))
        self.assertEqual(p.remaining_borrowing_capacity(), 0)
        self.assertIsNone(self.issue(1))
        self.assertIsNone(p.emergency_loan(1))

    def test_maturity_does_not_replenish_allowance_before_month_close(self):
        p = self.player
        bond = self.issue(p.monthly_borrowing_limit)
        bond.months_remaining = 1
        p.process_bonds()
        self.assertNotIn(bond, p.bonds)
        self.assertEqual(p.remaining_borrowing_capacity(), 0)

    def test_month_close_renews_cap_and_preserves_cash_flow_reporting(self):
        p = self.player
        issued = p.monthly_borrowing_limit
        self.issue(issued)
        self.session.advance_month()
        f = self.session.financials
        self.assertEqual(f.debt_issuance, issued)
        self.assertEqual(p.debt_issued_since_close, 0)
        expected = round((p.net_utility_plant() + p.construction_work_in_progress())
                         * utility.MONTHLY_BORROWING_ASSET_FRACTION, 2)
        self.assertEqual(p.remaining_borrowing_capacity(), expected)
        self.assertLess(expected, issued)  # depreciation, no growth from borrowed cash
        self.assertAlmostEqual(f.net_cash_from_operations + f.net_cash_from_investing
                               + f.net_cash_from_financing,
                               f.ending_cash - f.beginning_cash, delta=0.01)

    def test_borrowing_keeps_net_debt_and_book_equity_unchanged(self):
        p = self.player
        net_debt, equity = p.net_debt(), p.book_equity()
        self.issue(p.monthly_borrowing_limit)
        self.assertAlmostEqual(p.net_debt(), net_debt, delta=0.01)
        self.assertAlmostEqual(p.book_equity(), equity, delta=0.01)

    def test_rating_uses_cash_and_book_equity_instead_of_market_cap(self):
        # Isolate leverage from coverage and the initial forced B rating.
        p = self.player
        p.plant_assets = []
        p._add_plant_asset('coal', 1_000_000_000)
        p.bonds = [utility.Bond(950_000_000, 0.05, 10, 0)]
        p.cash = 900_000_000
        financials = SimpleNamespace(revenue=1_000_000_000, operational_costs=0)
        liquid_credit = copy.deepcopy(self.credit)
        liquid_credit.update(p, financials)
        p.company_value = 1  # a stock-price crash must not alter the credit ratio
        market_crash_credit = copy.deepcopy(self.credit)
        market_crash_credit.update(p, financials)
        self.assertEqual(liquid_credit._score, market_crash_credit._score)
        p.cash = 0
        spent_cash_credit = copy.deepcopy(self.credit)
        spent_cash_credit.update(p, financials)
        self.assertLess(spent_cash_credit._score, liquid_credit._score)
        self.assertTrue(spent_cash_credit.can_borrow)  # leverage alone is not default

    def test_borrowing_at_aaa_cannot_create_a_default_buyback_discount(self):
        p = self.player
        self.credit.rating, self.credit.spread = utility.CREDIT_RATINGS[0]
        self.credit._score = 100
        self.credit.strong_months = 12
        self.credit.can_borrow = True
        equity, net_debt = p.book_equity(), p.net_debt()
        unborrowed_player = copy.deepcopy(p)
        unborrowed_credit = copy.deepcopy(self.credit)
        bond = self.issue(p.monthly_borrowing_limit)
        # Actual coverage is intentionally still assessed, but cash-backed
        # gross debt alone must not drive the issuer toward default.
        financials = SimpleNamespace(revenue=0, operational_costs=1)
        for _ in range(120):
            self.credit.update(p, financials)
            unborrowed_credit.update(unborrowed_player, financials)
        self.assertNotEqual(self.credit.rating, 'D')
        self.assertAlmostEqual(p.book_equity(), equity, delta=0.01)
        self.assertAlmostEqual(p.net_debt(), net_debt, delta=0.01)
        # Sustained losses can lower credit, but borrowing and retaining cash
        # must not create an extra default discount relative to the control.
        self.assertEqual(self.credit.rating, unborrowed_credit.rating)
        self.assertAlmostEqual(p.bond_buyback_quote(bond, self.economy, self.credit)[2],
                               p.bond_buyback_quote(bond, self.economy, unborrowed_credit)[2])

    def test_market_rate_and_remaining_duration_still_affect_buyback_prices(self):
        bond = utility.Bond(100_000_000, 0.05, 10, 0)
        original_quote = self.player.bond_buyback_quote(bond, self.economy, self.credit)[2]
        self.economy.interest_rate += 0.03
        higher_rate_quote = self.player.bond_buyback_quote(bond, self.economy, self.credit)[2]
        self.assertLess(higher_rate_quote, original_quote)
        bond.months_remaining = 1
        near_maturity_quote = self.player.bond_buyback_quote(bond, self.economy, self.credit)[2]
        self.assertLess(abs(near_maturity_quote - bond.principal),
                        abs(higher_rate_quote - bond.principal))

    def test_bankruptcy_does_not_assume_unlimited_credit(self):
        p = self.player
        p.power_plants = dict.fromkeys(p.power_plants, 0)
        p.cash = -100
        p.debt_issued_since_close = p.monthly_borrowing_limit
        self.assertTrue(self.credit.can_borrow)
        self.assertTrue(utility.check_bankruptcy(p, self.credit))
        p.debt_issued_since_close -= 100
        self.assertFalse(utility.check_bankruptcy(p, self.credit))


if __name__ == '__main__':
    unittest.main()
