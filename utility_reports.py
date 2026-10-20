"""Immutable monthly accounting snapshots and complete calendar-period reports.

Snapshots contain values, never references to live accounts. Estimated pre-game
months are explicitly flagged and are replaced only by actual closes for that date.
"""

import copy


INCOME_LINES = (
    ('Electric revenue', 'monthly_electric_revenue', 1),
    ('Contract power sales', 'contract_sales_revenue', 1),
    ('Spot power sales', 'spot_sales_revenue', 1),
    ('Total operating revenue', 'total_operating_revenue', 1),
    ('Fuel and variable O&M', 'monthly_variable_operating_costs', -1),
    ('Contract power purchases', 'contract_purchase_cost', -1),
    ('Spot power purchases', 'spot_purchase_cost', -1),
    ('Carbon tax expense', 'monthly_carbon_tax_expense', -1),
    ('Cash operating expenses', 'cash_operating_expenses', -1),
    ('EBITDA', 'ebitda', 1),
    ('Depreciation and amortization', 'depreciation_expense', -1),
    ('Operating income (EBIT)', 'operating_income', 1),
    ('Retirement / debt gain (loss)', 'unusual_gain_loss', 1),
    ('Interest expense', 'interest_expense', -1),
    ('Income before tax', 'pretax_income', 1),
    ('Income tax expense', 'income_tax_expense', -1),
    ('Net income after interest', 'net_profit', 1),
    ('Weighted average shares', 'weighted_shares', 1),
    ('Basic earnings per share', 'eps', 1),
)

CASH_LINES = (
    ('Net income', 'net_profit', 1),
    ('Depreciation added back', 'depreciation_expense', 1),
    ('Gains / losses removed', 'unusual_gain_loss', -1),
    ('Net cash from operations', 'net_cash_from_operations', 1),
    ('Capital expenditures', 'capital_expenditures', -1),
    ('Asset retirement proceeds', 'asset_sale_proceeds', 1),
    ('Net cash from investing', 'net_cash_from_investing', 1),
    ('Debt issued', 'debt_issuance', 1),
    ('Debt repaid or repurchased', 'debt_repayments', -1),
    ('Stock issued', 'stock_issuance', 1),
    ('Stock repurchased', 'stock_buybacks', -1),
    ('Dividends paid', 'dividend_payments', -1),
    ('Net cash from financing', 'net_cash_from_financing', 1),
    ('Other / reconciliation', 'cash_reconciliation_adjustment', 1),
    ('Net change in cash', 'net_change_in_cash', 1),
    ('Beginning cash', 'beginning_cash', 1),
    ('Ending cash', 'ending_cash', 1),
)

BALANCE_LINES = (
    ('Cash and cash equivalents', 'cash', 1),
    ('Gross utility plant', 'gross_plant', 1),
    ('Accumulated depreciation', 'accumulated_depreciation', -1),
    ('Net utility plant', 'net_plant', 1),
    ('Construction work in progress', 'construction', 1),
    ('Total assets', 'assets', 1),
    ('Current portion of debt', 'current_debt', 1),
    ('Long-term debt', 'long_term_debt', 1),
    ('Total debt', 'debt', 1),
    ('Paid-in capital', 'paid_in_capital', 1),
    ('Treasury stock', 'treasury_stock', -1),
    ('Retained earnings', 'retained_earnings', 1),
    ('Total shareholders’ equity', 'equity', 1),
    ('Liabilities and equity', 'liabilities_equity', 1),
)


def balance_snapshot(player):
    current = player.debt + sum(b.principal for b in player.bonds if b.months_remaining <= 12)
    equity = player.book_equity()
    return dict(cash=player.cash, gross_plant=player.gross_utility_plant(),
                accumulated_depreciation=player.accumulated_depreciation(),
                net_plant=player.net_utility_plant(), construction=player.construction_work_in_progress(),
                assets=player.total_asset_value(), current_debt=current,
                long_term_debt=player.total_debt() - current, debt=player.total_debt(),
                paid_in_capital=player.paid_in_capital, treasury_stock=player.treasury_stock,
                retained_earnings=equity - player.paid_in_capital + player.treasury_stock,
                equity=equity, liabilities_equity=player.total_debt() + equity)


def capture(financials, player, year, month, estimated=False):
    income = {key: getattr(financials, key, 0.0) for _, key, _ in INCOME_LINES}
    income['weighted_shares'] = financials.monthly_weighted_shares or player.shares_outstanding
    income['eps'] = income['net_profit'] / income['weighted_shares']
    cash = {key: getattr(financials, key, 0.0) for _, key, _ in CASH_LINES}
    return dict(year=year, month=month, estimated=estimated, income=income,
                balance=balance_snapshot(player), cash_flow=cash)


def store_close(financials, player, state):
    record = capture(financials, player, state.year, state.current_month)
    financials.monthly_history = [r for r in financials.monthly_history
                                 if (r['year'], r['month']) != (state.year, state.current_month)]
    financials.monthly_history.append(record)
    financials.monthly_history.sort(key=lambda r: (r['year'], r['month']))


def _recompute_balance(balance):
    balance['net_plant'] = balance['gross_plant'] - balance['accumulated_depreciation']
    balance['assets'] = balance['cash'] + balance['net_plant'] + balance['construction']
    balance['equity'] = balance['assets'] - balance['debt']
    balance['retained_earnings'] = (balance['equity'] - balance['paid_in_capital']
                                  + balance['treasury_stock'])
    balance['liabilities_equity'] = balance['debt'] + balance['equity']


def seed_history(session):
    """Four full estimated years, with seasonal earnings and reconciling ledgers.

Assume a mature utility paid 35% of earnings and reinvested the rest plus its
depreciation charge. Cash and debt stay steady, while historical plant and
retained earnings roll forward exactly to today's opening balance sheet.
"""
    f, p, state = session.financials, session.player, session.game_state
    template = capture(f, p, state.year, state.current_month, estimated=True)
    balance = copy.deepcopy(template['balance'])
    records = []
    for back in range(49):
        serial = state.year * 12 + state.current_month - 1 - back
        year, month0 = divmod(serial, 12)
        month = month0 + 1
        factor = ((1.025 ** (-back / 12)) * state.seasonal_demand_multiplier(month)
                  / state.seasonal_demand_multiplier(state.current_month))
        income = copy.deepcopy(template['income'])
        for key in ('monthly_electric_revenue', 'contract_sales_revenue', 'spot_sales_revenue',
                    'monthly_variable_operating_costs', 'contract_purchase_cost',
                    'spot_purchase_cost', 'monthly_carbon_tax_expense'):
            income[key] *= factor
        income['total_operating_revenue'] = sum(income[k] for k in (
            'monthly_electric_revenue', 'contract_sales_revenue', 'spot_sales_revenue'))
        income['cash_operating_expenses'] = sum(income[k] for k in (
            'monthly_variable_operating_costs', 'contract_purchase_cost',
            'spot_purchase_cost', 'monthly_carbon_tax_expense'))
        income['ebitda'] = income['total_operating_revenue'] - income['cash_operating_expenses']
        income['operating_income'] = income['ebitda'] - income['depreciation_expense']
        income['unusual_gain_loss'] = 0.0
        income['pretax_income'] = income['operating_income'] - income['interest_expense']
        income['income_tax_expense'] = max(0, income['pretax_income'] * .21)
        income['net_profit'] = income['pretax_income'] - income['income_tax_expense']
        income['eps'] = income['net_profit'] / income['weighted_shares']
        # In an estimated loss month equity support funds the loss. It is shown,
        # not silently hidden in a cash-flow reconciliation plug.
        dividends = max(0, income['net_profit']) * .35
        support = max(0, -income['net_profit'])
        capex = max(0, income['net_profit']) - dividends + income['depreciation_expense']
        cash = {key: 0.0 for _, key, _ in CASH_LINES}
        cash.update(net_profit=income['net_profit'], depreciation_expense=income['depreciation_expense'],
                    net_cash_from_operations=income['net_profit'] + income['depreciation_expense'],
                    capital_expenditures=capex, net_cash_from_investing=-capex,
                    dividend_payments=dividends, stock_issuance=support,
                    net_cash_from_financing=support - dividends,
                    beginning_cash=p.cash, ending_cash=p.cash)
        records.append(dict(year=year, month=month, estimated=True, income=income,
                            balance=copy.deepcopy(balance), cash_flow=cash))
        balance['gross_plant'] -= capex
        balance['accumulated_depreciation'] -= income['depreciation_expense']
        balance['paid_in_capital'] -= support
        _recompute_balance(balance)
    records.reverse()
    f.monthly_history = records
    f.trailing_earnings = [r['income']['net_profit'] for r in records[-12:]]
    f.trailing_ebitda = [r['income']['ebitda'] for r in records[-12:]]
    f.trailing_share_counts = [r['income']['weighted_shares'] for r in records[-12:]]
    # January is also an explicitly estimated close, ending at the actual opening
    # balance. February's real close then continues from that same balance.


def periods(financials, state, frequency):
    """Last four complete calendar quarters/years, excluding the in-progress period."""
    if frequency not in ('quarterly', 'annual'):
        raise ValueError('Choose quarterly or annual statements.')
    months_per_period = 3 if frequency == 'quarterly' else 12
    serial_now = state.year * 12 + state.current_month - 1
    # The current month's results exist only after a real month close.
    last_closed = serial_now if financials.has_closed_month else serial_now - 1
    last_end = ((last_closed + 1) // months_per_period) * months_per_period - 1
    lookup = {r['year'] * 12 + r['month'] - 1: r for r in financials.monthly_history}
    result = []
    for ago in range(4):
        end = last_end - ago * months_per_period
        start = end - months_per_period + 1
        months = [lookup[i] for i in range(start, end + 1) if i in lookup]
        if len(months) != months_per_period:
            continue  # never silently report an incomplete period as a full one
        year, month0 = divmod(end, 12)
        label = f'Year {year}' if year >= 1 else f'Pre-game year {year}'
        if frequency == 'quarterly':
            label += f' Q{month0 // 3 + 1}'
        estimated_count = sum(r['estimated'] for r in months)
        label += ' (est.)' if estimated_count == len(months) else ' (mixed)' if estimated_count else ''
        income = {key: sum(r['income'][key] for r in months) for _, key, _ in INCOME_LINES}
        income['weighted_shares'] /= len(months)
        income['eps'] = income['net_profit'] / max(income['weighted_shares'], 1)
        cash = {key: sum(r['cash_flow'][key] for r in months) for _, key, _ in CASH_LINES}
        cash['beginning_cash'] = months[0]['cash_flow']['beginning_cash']
        cash['ending_cash'] = months[-1]['cash_flow']['ending_cash']
        result.append(dict(label=label, start=start, end=end, estimated_months=estimated_count,
                           income=income, cash_flow=cash, balance=copy.deepcopy(months[-1]['balance'])))
    return result
