import argparse
import contextlib
import io
import math
import random
from dataclasses import dataclass
import utility_reports
import utility_persistence

try:
    import tkinter as tk
    from tkinter import filedialog, messagebox, simpledialog, ttk
except ImportError:  # The simulation and CLI can still run without Tk.
    tk = None
    filedialog = messagebox = simpledialog = ttk = None

GAME_VERSION = '2.0'

# --- Game Constants ---

MONTH_NAMES = [
    "JANUARY", "FEBRUARY", "MARCH", "APRIL", "MAY", "JUNE",
    "JULY", "AUGUST", "SEPTEMBER", "OCTOBER", "NOVEMBER", "DECEMBER"
]

# Power Plant capacities (MW)
COAL_PLANT_CAPACITY = 600         # was 100 — real coal units are 500-800 MW
NATURAL_GAS_PLANT_CAPACITY = 500   # was 80  — combined-cycle gas ~500 MW
NUCLEAR_PLANT_CAPACITY = 1200      # representative modern large reactor
SOLAR_PLANT_CAPACITY = 200         # was 50  — utility-scale solar farm
WIND_PLANT_CAPACITY = 150          # was 30  — a wind farm, not one turbine
HYDRO_PLANT_CAPACITY = 200         # a medium conventional hydro project
BATTERY_POWER_CAPACITY = 100       # MW of instantaneous output
BATTERY_ENERGY_CAPACITY = 400      # MWh: a four-hour grid battery

PLANT_NAMEPLATE_CAPACITY = {
    'coal': COAL_PLANT_CAPACITY,
    'natural_gas': NATURAL_GAS_PLANT_CAPACITY,
    'nuclear': NUCLEAR_PLANT_CAPACITY,
    'solar': SOLAR_PLANT_CAPACITY,
    'wind': WIND_PLANT_CAPACITY,
    'hydro': HYDRO_PLANT_CAPACITY,
    'battery': BATTERY_POWER_CAPACITY,
}

# Costs and Revenues (opening $/MWh; current prices use the cumulative price index)
COAL_COST_PER_MWH = 30
NATURAL_GAS_COST_PER_MWH = 45  # pricier fuel, but faster/cleaner to run
NUCLEAR_COST_PER_MWH = 15
SOLAR_COST_PER_MWH = 5
WIND_COST_PER_MWH = 8
HYDRO_COST_PER_MWH = 10
HYDRO_OUTPUT_FACTOR = 0.75
BATTERY_DEGRADATION_PER_CYCLE = 0.01
WHOLESALE_PRICE_PER_MWH = 40
RETAIL_PRICE_PER_MWH = 150

# Recurring firm trades receive better prices than automatic spot balancing.
# A bid/ask spread prevents buying power merely to resell it for free profit.
CONTRACT_BUY_FACTOR = 1.05
CONTRACT_SELL_FACTOR = 0.95
SPOT_BUY_FACTOR = 1.15
SPOT_SELL_FACTOR = 0.85

# Natural gas price dynamics
NATURAL_GAS_BASE_COST_PER_MWH = 45   # long-run "normal" gas price
NATURAL_GAS_MIN_COST_PER_MWH = 20    # price floor
NATURAL_GAS_MAX_COST_PER_MWH = 140   # price ceiling (severe crisis)
GAS_PRICE_MEAN_REVERSION = 0.15      # how fast price drifts back to base each month
GAS_PRICE_MONTHLY_VOLATILITY = 0.04  # baseline random monthly wiggle (fraction)

# Battery operation
BATTERY_ROUND_TRIP_EFFICIENCY = 0.90  # 90% of stored energy is recoverable
BATTERY_MIN_CAPACITY_FRACTION = 0.20  # battery is "dead" below 20% of original max

# Construction Costs (opening dollars; future quotes follow cumulative inflation)
COAL_CONSTRUCTION_COST = 3_000_000_000       # ~$3B for 600 MW
NATURAL_GAS_CONSTRUCTION_COST = 1_000_000_000 # ~$1B for 500 MW CCGT
NUCLEAR_CONSTRUCTION_COST = 9_000_000_000     # $7,500/kW for a 1,200 MW unit
SOLAR_CONSTRUCTION_COST = 600_000_000         # early technology; learning reduces real cost
WIND_CONSTRUCTION_COST = 450_000_000
RENEWABLE_MATURE_COST = {'solar': 330_000_000, 'wind': 275_000_000}
RENEWABLE_LEARNING_MONTHS = 120
HYDRO_BASE_CONSTRUCTION_COST = 650_000_000    # ~$3,250/kW at the best remaining site
HYDRO_SITE_COST_ESCALATION = 0.18             # progressively less economic rivers
BATTERY_CONSTRUCTION_COST = 150_000_000       # ~$1,500/kW for 100 MW / 400 MWh

DECOMMISSION_INFO = {
    'coal':        (0.10, 1_000_000),
    'natural_gas': (0.12, 800_000),
    'nuclear':     (0.03, 500_000_000),  # long, specialized decommissioning program
    'solar':       (0.15, 200_000),
    'wind':        (0.15, 300_000),
    'hydro':       (0.20, 2_000_000),
}
PLANT_BUILD_COST = {
    'coal': COAL_CONSTRUCTION_COST,
    'natural_gas': NATURAL_GAS_CONSTRUCTION_COST,
    'nuclear': NUCLEAR_CONSTRUCTION_COST,
    'solar': SOLAR_CONSTRUCTION_COST,
    'wind': WIND_CONSTRUCTION_COST,
    'hydro': HYDRO_BASE_CONSTRUCTION_COST,
}

# Construction Times (in months)
COAL_CONSTRUCTION_TIME = 6
NATURAL_GAS_CONSTRUCTION_TIME = 4       # gas plants build faster
NUCLEAR_CONSTRUCTION_TIME = 72          # 6 years
SOLAR_CONSTRUCTION_TIME = 3
WIND_CONSTRUCTION_TIME = 9
HYDRO_CONSTRUCTION_TIME = 48
BATTERY_CONSTRUCTION_TIME = 12


# Financials
STARTING_DIVIDEND_RATE = 0.05  # 5% of net profit
MIN_COMPANY_SIZE = 1_000_000_000    # $3B
MAX_COMPANY_SIZE = 10_000_000_000   # $15B

# Morningstar's historical utility-sector median since 2007 is 1.75x book.
# This remains a secondary valuation anchor. The opening quote targets 10x
# trailing earnings; later prices blend earnings, book value and dividends.
UTILITY_TARGET_PRICE_TO_BOOK = 1.75
BOOK_VALUE_WEIGHT = 0.20
EARNINGS_WEIGHT = 0.70
DIVIDEND_WEIGHT = 0.10
CORPORATE_TAX_RATE = 0.21
MIN_OPENING_BOOK_EQUITY = 250_000_000
MIN_DIVIDEND_YIELD = 0.02
HAPPY_DIVIDEND_YIELD = 0.03
SHAREHOLDER_MAX_HAPPINESS = 100.0
SHAREHOLDER_FIRING_THRESHOLD = 10.0
ANNUAL_SHARE_TRADE_LIMIT = 0.049  # combined issues + buybacks; cannot recycle the allowance
SHARE_TRADE_SPREAD = 0.01
OPENING_TARGET_DEBT_EQUITY = 1.5
OPENING_TARGET_PE = 10.0

# Straight-line useful lives for the regulated utility plant ledger.
ASSET_USEFUL_LIFE_YEARS = {
    'coal': 40,
    'natural_gas': 30,
    'nuclear': 60,
    'solar': 30,
    'wind': 25,
    'hydro': 80,
    'battery': 15,
}
OPENING_PLANT_AGE_FRACTION_RANGE = (0.20, 0.65)

# Add near the equity constants
STOCK_SMOOTHING = 0.45        # monthly move toward fair value (0=frozen, 1=instant)
STOCK_MONTHLY_NOISE = 0.02    # +/- 2% random market wiggle
REQUIRED_RETURN_PREMIUM = 0.03  # equity risk premium over the risk-free rate

# Debt: real electric utilities average a D/E ratio of ~2.35 (range 1.3-2.97)
MIN_DE_RATIO = 1.3
MAX_DE_RATIO = 2.97
STARTING_DEBT_MULTIPLIER = 2.0
LEGACY_BOND_RATE_RANGE = (0.03, 0.07)  # historical rates the old bonds were issued at
BOND_BUYBACK_TRANSACTION_COST = 0.005  # dealer spread / execution cost
MONTHLY_BORROWING_ASSET_FRACTION = 0.10  # shared by bonds and emergency loans

# Credit trouble should arrive quickly but take much longer to repair. These
# are monthly weights applied to the newest financial result.
CREDIT_UPGRADE_SMOOTHING = 0.04
CREDIT_DOWNGRADE_SMOOTHING = 0.30
CREDIT_AAA_QUALIFYING_MONTHS = 12
CREDIT_DEFAULT_SHORTFALL_MONTHS = 3
CREDIT_DEFAULT_RECOVERY_MONTHS = 3

# The earlier low-carbon starting-fleet model averaged about 0.75 reactors per
# 1,000 MW of territory. The hard opening scenario deliberately halves that.
STARTING_NUCLEAR_UNITS_PER_1000_MW = 0.375

# Carbon policy. Enactment occurs at a hidden random month and then compounds.
CARBON_TAX_START_MONTH_RANGE = (18, 120)
CARBON_TAX_INITIAL_RANGE = (20.0, 45.0)       # dollars per metric ton CO2
CARBON_TAX_ANNUAL_GROWTH_RANGE = (0.05, 0.10)
COAL_EMISSIONS_TONS_PER_MWH = 0.95
GAS_EMISSIONS_TONS_PER_MWH = 0.40



# Game turns
TURNS_PER_YEAR = 12       # each turn is 1 month
HOURS_PER_YEAR = 8760     # 365 * 24, for converting MW -> MWh/year
HOURS_PER_MONTH = HOURS_PER_YEAR / TURNS_PER_YEAR


def wholesale_market_price(economy):
    return (WHOLESALE_PRICE_PER_MWH * getattr(economy, 'price_index', 1.0)
            * (1 + 0.1 * economy.sentiment))


def power_contract_description(net_import_mw):
    if net_import_mw == 0:
        return 'None'
    direction = 'Buy' if net_import_mw > 0 else 'Sell'
    return f'{direction} {abs(net_import_mw):,.0f} MW'


@dataclass
class PlantAsset:
    """Individual in-service asset, kept at its own original cost and age."""

    asset_id: int
    plant_type: str
    original_cost: float
    accumulated_depreciation: float = 0.0
    months_in_service: int = 0
    last_month_depreciation: float = 0.0
    purchase_price_index: float = 1.0

    def inflation_adjusted_cost(self, current_price_index):
        """Today's dollar equivalent for salvage, not an accounting revaluation."""
        return self.original_cost * current_price_index / self.purchase_price_index

    @property
    def net_book_value(self):
        return max(0.0, self.original_cost - self.accumulated_depreciation)

    @property
    def monthly_depreciation(self):
        return min(self.net_book_value, self.original_cost
                   / (ASSET_USEFUL_LIFE_YEARS[self.plant_type] * 12))

# Geopolitical / market events affecting natural gas prices.
# 'shock' is a multiplier applied to the current gas price when triggered.
# 'duration' is how many months the ongoing monthly pressure lasts.
GAS_EVENTS = [
    {"name": "Major pipeline sabotage disrupts supply",      "shock": 1.60, "duration": 8},
    {"name": "War breaks out in a gas-exporting region",     "shock": 1.45, "duration": 12},
    {"name": "Unusually harsh winter spikes heating demand", "shock": 1.30, "duration": 3},
    {"name": "Export terminal outage tightens supply",       "shock": 1.20, "duration": 4},
    {"name": "OPEC+ style production cut announced",          "shock": 1.25, "duration": 6},
    {"name": "New shale field comes online (supply glut)",   "shock": 0.75, "duration": 10},
    {"name": "New pipeline capacity opens",                  "shock": 0.85, "duration": 8},
    {"name": "Mild weather collapses demand",                "shock": 0.80, "duration": 3},
    {"name": "Trade deal eases import restrictions",         "shock": 0.88, "duration": 6},
]

GAS_EVENT_MONTHLY_CHANCE = 0.10  # 10% chance of a new event each month


# Demand growth
ANNUAL_DEMAND_GROWTH = 0.02          # ~2% per year baseline
MONTHLY_DEMAND_GROWTH = (1 + ANNUAL_DEMAND_GROWTH) ** (1/12) - 1  # compounded monthly
DEMAND_MONTHLY_VARIATION = 0.10
DEMAND_FORECAST_MONTHS = 24

# Economic / demand events. 'shock' is a one-time multiplier to the demand
# growth index; 'monthly_pressure' is spread over the duration.
DEMAND_EVENTS = [
    {"name": "Major data center cluster breaks ground", "shock": 1.06, "duration": 18},
    {"name": "New EV factory opens in the region",       "shock": 1.04, "duration": 12},
    {"name": "Population boom / housing development",     "shock": 1.03, "duration": 24},
    {"name": "Crypto mining operation moves in",          "shock": 1.05, "duration": 8},
    {"name": "Recession hits the region",                 "shock": 0.93, "duration": 12},
    {"name": "Major factory shuts down",                  "shock": 0.95, "duration": 15},
    {"name": "Aggressive efficiency mandates enacted",    "shock": 0.97, "duration": 24},
    {"name": "Large employer relocates away",             "shock": 0.96, "duration": 18},
]

DEMAND_EVENT_MONTHLY_CHANCE = 0.08   # 8% chance of a new demand event each month


# --- Macroeconomic constants ---
BASE_INFLATION = 0.025          # 2.5% annual target
BASE_INTEREST_RATE = 0.045      # 4.5% central-bank-ish baseline
MARKET_BASE_PE = 18.0           # baseline market P/E ratio

class Economy:
    """Tracks the business cycle: inflation, interest rates, market sentiment."""
    def __init__(self):
        # cycle_phase runs 0..2pi; sin() gives boom/bust sentiment.
        self.cycle_phase = random.uniform(0, 2 * math.pi)
        self.cycle_speed = 2 * math.pi / random.uniform(60, 120)  # 5-10 yr cycles
        self.inflation = BASE_INFLATION
        self.interest_rate = BASE_INTEREST_RATE
        self.market_pe = MARKET_BASE_PE
        self.sentiment = 0.0  # -1 (recession) .. +1 (boom)
        self.price_index = 1.0  # opening dollars; compounds actual monthly inflation
        self.monthly_inflation_factor = 1.0
        self.elapsed_months = 0
        self.last_technology_event = None
        self.update(advance_prices=False)

    def update(self, advance_prices=True):
        self.cycle_phase += self.cycle_speed
        self.sentiment = math.sin(self.cycle_phase)

        # Inflation rises in booms, falls in busts, plus noise.
        self.inflation = max(-0.01, BASE_INFLATION
                             + 0.02 * self.sentiment
                             + random.uniform(-0.005, 0.005))

        # Central bank raises rates to fight inflation (Taylor-rule-ish).
        target_rate = BASE_INTEREST_RATE + 1.2 * (self.inflation - BASE_INFLATION) \
                      + 0.5 * self.sentiment * 0.02
        # Rates move gradually toward target.
        self.interest_rate += (target_rate - self.interest_rate) * 0.2
        self.interest_rate = max(0.005, self.interest_rate)

        # Market P/E expands in booms, contracts in busts.
        self.market_pe = max(8.0, MARKET_BASE_PE + 6.0 * self.sentiment
                             + random.uniform(-1.0, 1.0))
        if advance_prices:
            self.advance_price_level()

    def advance_price_level(self):
        """Apply one month's share of the displayed annual rate, including deflation."""
        self.monthly_inflation_factor = (1 + self.inflation) ** (1 / TURNS_PER_YEAR)
        self.price_index *= self.monthly_inflation_factor
        self.elapsed_months += 1
        self.last_technology_event = None
        if self.elapsed_months <= RENEWABLE_LEARNING_MONTHS and self.elapsed_months % 12 == 0:
            self.last_technology_event = (
                f'CLEAN ENERGY LEARNING: year {self.elapsed_months // 12} milestone. '
                f'Solar real build cost ${SOLAR_CONSTRUCTION_COST * self.technology_cost_factor("solar") / 1e6:,.0f}M; '
                f'wind ${WIND_CONSTRUCTION_COST * self.technology_cost_factor("wind") / 1e6:,.0f}M '
                '(opening dollars; current quotes also include inflation).')
            print(self.last_technology_event)

    def technology_cost_factor(self, plant_type):
        if plant_type not in RENEWABLE_MATURE_COST:
            return 1.0
        base = SOLAR_CONSTRUCTION_COST if plant_type == 'solar' else WIND_CONSTRUCTION_COST
        progress = min(1.0, self.elapsed_months / RENEWABLE_LEARNING_MONTHS)
        return (RENEWABLE_MATURE_COST[plant_type] / base) ** progress

    def display(self):
        mood = ("BOOM" if self.sentiment > 0.4 else
                "RECESSION" if self.sentiment < -0.4 else "STABLE")
        print("\n--- Economy ---")
        print(f"Cycle: {mood} (sentiment {self.sentiment:+.2f})")
        print(f"Inflation: {self.inflation * 100:.2f}%   "
              f"Interest Rate: {self.interest_rate * 100:.2f}%   "
              f"Market P/E: {self.market_pe:.1f}")
        print(f"Price index: {self.price_index * 100:.2f} (opening = 100; "
              f"{self.price_index - 1:+.1%} cumulative inflation)")

    # Economy
    def bond_rate(self, term_years, credit_spread):
        term_premium = 0.0015 * math.log1p(term_years)
        return self.interest_rate + term_premium + credit_spread

# Bond terms available (in months) and labels.
BOND_TERMS = {
    '6mo':  0.5,
    '1yr':  1,
    '2yr':  2,
    '5yr':  5,
    '10yr': 10,
    '20yr': 20,
}

# Add to the constants section near the top of the file:
CAPACITY_CREDIT = {
    'coal': 1.0,
    'natural_gas': 1.0,
    'nuclear': 1.0,
    'solar': 0.15,
    'wind': 0.20,
    'hydro': 0.90,
    'battery': 0.85,
}
TARGET_RESERVE_MARGIN = 0.15

class Bond:
    def __init__(self, principal, annual_rate, term_years, issued_turn):
        self.principal = principal
        self.annual_rate = annual_rate       # locked in at issuance
        self.months_remaining = int(round(term_years * 12))
        self.issued_turn = issued_turn

    def monthly_interest(self):
        return self.principal * (self.annual_rate / 12)

    def market_value(self, current_annual_yield):
        """Present value of remaining coupons and principal at today's yield."""
        months = max(0, self.months_remaining)
        if months == 0:
            return self.principal
        monthly_yield = max(0.0, current_annual_yield) / 12
        coupon = self.monthly_interest()
        if monthly_yield < 1e-9:
            return self.principal + coupon * months
        discount = (1 + monthly_yield) ** months
        coupon_value = coupon * (1 - 1 / discount) / monthly_yield
        return coupon_value + self.principal / discount

    


def generate_random_plant_mix():
    plants = {
        'coal': 1 if random.random() < 0.35 else 0,
        'natural_gas': 1,
        'nuclear': 0,
        'solar': 0,
        'wind': 0,
        'hydro': 0,
    }
    if plants['coal'] + plants['natural_gas'] + plants['nuclear'] == 0:
        plants['natural_gas'] = 1
    return plants


# Rate regulation
FAIRNESS_MARGIN_CAP = 0.12      # regulator tolerates up to ~12% net margin
RATE_REQUEST_COOLDOWN = 12      # months before requests stop being "frequent"

class RateRegulator:
    def __init__(self, economy=None):
        self.economy = economy
        self._real_retail_price = RETAIL_PRICE_PER_MWH
        self.last_request_turn = -999
        self.recent_requests = 0

    @property
    def current_retail_price(self):
        return self._real_retail_price * getattr(self.economy, 'price_index', 1.0)

    @current_retail_price.setter
    def current_retail_price(self, nominal_price):
        self._real_retail_price = nominal_price / getattr(self.economy, 'price_index', 1.0)

    def request_increase(self, player_state, financials, economy, current_turn, pct):
        """Ask for an increase above the tariff's automatic inflation adjustment."""
        # Estimate current net margin.
        rev = max(financials.revenue, 1)
        margin = (financials.net_profit * 12) / rev

        # Base approval probability shrinks as margin nears the cap.
        headroom = max(0.0, FAIRNESS_MARGIN_CAP - margin)
        base_prob = min(0.9, headroom / FAIRNESS_MARGIN_CAP)

        # Inflation is already passed through automatically, so it does not
        # independently justify an additional real-price rate increase.

        # Frequency penalty.
        months_since = current_turn - self.last_request_turn
        if months_since < RATE_REQUEST_COOLDOWN:
            base_prob -= 0.25 * (1 - months_since / RATE_REQUEST_COOLDOWN)
            base_prob -= 0.1 * self.recent_requests

        # Larger asks are harder to get approved.
        base_prob -= pct * 2.0

        # Reputation helps.
        base_prob += (player_state.reputation - 0.5) * 0.2

        approve_prob = max(0.02, min(0.95, base_prob))
        approved = random.random() < approve_prob

        self.last_request_turn = current_turn
        if months_since < RATE_REQUEST_COOLDOWN:
            self.recent_requests += 1
        else:
            self.recent_requests = 1

        if approved:
            self.current_retail_price *= (1 + pct)
            player_state.reputation = max(0.0, player_state.reputation - 0.03)  # public grumbles
            print(f"APPROVED: retail rate raised {pct*100:.1f}% "
                  f"to ${self.current_retail_price:.2f}/MWh (odds were {approve_prob*100:.0f}%).")
        else:
            player_state.reputation = min(1.0, player_state.reputation + 0.01)
            print(f"REJECTED: rate increase denied (odds were {approve_prob*100:.0f}%). "
                  f"Margin too high, asking too often, or ask too large.")
        return approved

# Credit ratings from best to worst, each with a borrowing spread over base.
CREDIT_RATINGS = [
    ('AAA', .004), ('AA+', .005), ('AA', .006), ('AA-', .007),
    ('A+', .008), ('A', .009), ('A-', .010),
    ('BBB+', .012), ('BBB', .014), ('BBB-', .018),
    ('BB+', .025), ('BB', .032), ('BB-', .040),
    ('B+', .050), ('B', .060), ('B-', .075),
    ('CCC+', .090), ('CCC', .110), ('CCC-', .140), ('D', None),
]
# Bounded 0–100 credit score. D is a persistent liquidity failure, not a score band.
CREDIT_SCORE_BANDS = (
    (95, 'AAA'), (91, 'AA+'), (87, 'AA'), (83, 'AA-'),
    (79, 'A+'), (75, 'A'), (71, 'A-'), (67, 'BBB+'), (63, 'BBB'), (59, 'BBB-'),
    (53, 'BB+'), (47, 'BB'), (41, 'BB-'), (35, 'B+'), (29, 'B'), (23, 'B-'),
    (17, 'CCC+'), (11, 'CCC'), (0, 'CCC-'),
)

class CreditRating:
    def __init__(self):
        self.rating = 'BBB+'
        self.spread = dict(CREDIT_RATINGS)[self.rating]
        self.can_borrow = True
        self._score = 69.0
        self._forced_start = True
        self.net_leverage = 0.0
        self.interest_coverage = 0.0
        self.strong_months = 0
        self.distress_months = 0
        self._recovery_months = 0

    @staticmethod
    def _metric_score(value, points):
        """Piecewise-linear points avoid cliffs and unbounded leverage penalties."""
        if value <= points[0][0]:
            return points[0][1]
        for (low, low_score), (high, high_score) in zip(points, points[1:]):
            if value <= high:
                return low_score + (high_score - low_score) * (value - low) / (high - low)
        return points[-1][1]

    def _set_rating(self, rating):
        self.rating = rating
        self.spread = dict(CREDIT_RATINGS)[rating]
        self.can_borrow = self.spread is not None

    def update(self, player_state, financials):
        # Borrowing and keeping the proceeds leaves net debt and book equity
        # unchanged; market-price swings must not create a downgrade spiral.
        equity = player_state.book_equity()
        net_debt = max(0.0, player_state.net_debt())
        self.net_leverage = net_debt / equity if equity > 0 else float('inf')
        annual_interest = sum(b.monthly_interest() for b in player_state.bonds) * 12
        # Rolling operating earnings damp seasonal spikes. Legacy callers that
        # supply only annual revenue/costs still use the same cash-profit measure.
        operating_profit = getattr(financials, 'ttm_ebitda',
                                   financials.revenue - financials.operational_costs)
        self.interest_coverage = (operating_profit / annual_interest if annual_interest > 0
                                  else float('inf') if operating_profit > 0 else 0.0)
        if self._forced_start:
            # Established utilities start near investment-grade BBB+/A-.
            self._forced_start = False
            rating = 'A-' if self.interest_coverage >= 3.5 else 'BBB+'
            self._score = 73.0 if rating == 'A-' else 69.0
            self._set_rating(rating)
            return

        leverage_score = self._metric_score(self.net_leverage, (
            (0, 100), (0.25, 95), (0.5, 90), (1, 80), (1.5, 65),
            (2.5, 50), (4, 35), (6, 20), (10, 0),
        ))
        coverage_score = self._metric_score(self.interest_coverage, (
            (0, 0), (0.5, 15), (1, 30), (1.5, 45), (2, 60),
            (3, 75), (4, 85), (6, 95), (8, 100),
        ))
        score = 0.55 * leverage_score + 0.45 * coverage_score
        if equity <= 0:
            score = min(score, 42)  # negative book equity is speculative, not automatic default
        if player_state.cash < 0:
            score -= 15
        score = max(0.0, min(100.0, score))

        qualifies = (equity > 0 and self.net_leverage <= 0.35
                     and self.interest_coverage >= 6 and player_state.cash >= 0)
        self.strong_months = self.strong_months + 1 if qualifies else 0
        shortfall = player_state.cash < 0 and player_state.total_debt() > 0
        self.distress_months = self.distress_months + 1 if shortfall else 0
        if self.distress_months == 1 and self.rating != 'D':
            print("Credit warning: negative cash at month close. Repair the shortfall; "
                  f"{CREDIT_DEFAULT_SHORTFALL_MONTHS} consecutive negative-cash closes "
                  "with debt outstanding trigger a D rating.")

        smoothing = (CREDIT_UPGRADE_SMOOTHING
                     if score > self._score else CREDIT_DOWNGRADE_SMOOTHING)
        self._score += (score - self._score) * smoothing

        if self.rating == 'D':
            self._recovery_months = self._recovery_months + 1 if player_state.cash >= 0 else 0
            self._score = min(self._score, 12)
            if self._recovery_months < CREDIT_DEFAULT_RECOVERY_MONTHS:
                return  # keep D until liquidity has been repaired for three closes
            print("Credit restored to CCC after sustained liquidity recovery; "
                  "further upgrades will take time.")
        elif self.distress_months >= CREDIT_DEFAULT_SHORTFALL_MONTHS:
            self._score = min(self._score, 12)
            self._recovery_months = 0
            self._set_rating('D')
            print("Credit downgraded to D: the cash shortfall has persisted for "
                  f"{CREDIT_DEFAULT_SHORTFALL_MONTHS} months.")
            return

        rating = next(label for threshold, label in CREDIT_SCORE_BANDS
                      if self._score >= threshold)
        if rating == 'AAA' and self.strong_months < CREDIT_AAA_QUALIFYING_MONTHS:
            rating = 'AA+'
        self._set_rating(rating)
        

    def display(self):
        spread_txt = f"{self.spread*100:.1f}% spread" if self.can_borrow else "NO LENDERS"
        print(f"Credit Rating: {self.rating} ({spread_txt})")


class GameState:
    def __init__(self, economy=None):
        self.economy = economy
        self.turn = 1
        self.current_month = 1
        self.year = 1

        self.latitude = random.uniform(20, 65)
        if self.latitude < 33:
            self.climate = "hot"
        elif self.latitude > 50:
            self.climate = "cold"
        else:
            self.climate = "temperate"

        # Dynamic natural gas price and any ongoing geopolitical events.
        self._real_natural_gas_price = NATURAL_GAS_BASE_COST_PER_MWH
        self.active_gas_events = []  # each: {'name', 'months_left', 'monthly_pressure'}
        self.last_gas_event_msg = None

        self.region_sunlight_level = 0.0
        self.region_wind_level = 0.0
        self.demand_multiplier = 1.0
        self.update_seasonal_conditions()
        # Demand growth: an index that starts at 1.0 and compounds ~2%/yr plus events.
        self.demand_index = 1.0
        self.active_demand_events = []   # each: {'name', 'months_left', 'monthly_pressure'}
        self.last_demand_event_msg = None

        # Carbon regulation arrives at an unknown future date. Once enacted,
        # its price rises every month at a fixed real policy escalator.
        self._real_carbon_tax = 0.0
        self._carbon_tax_start_turn = random.randint(*CARBON_TAX_START_MONTH_RANGE)
        self._carbon_tax_initial = random.uniform(*CARBON_TAX_INITIAL_RANGE)
        self._carbon_tax_annual_growth = random.uniform(*CARBON_TAX_ANNUAL_GROWTH_RANGE)
        self.last_carbon_event_msg = None
        

    @property
    def price_index(self):
        return getattr(self.economy, 'price_index', 1.0)

    @property
    def natural_gas_price(self):
        return self._real_natural_gas_price * self.price_index

    @natural_gas_price.setter
    def natural_gas_price(self, nominal_price):
        self._real_natural_gas_price = nominal_price / self.price_index

    @property
    def carbon_tax(self):
        return self._real_carbon_tax * self.price_index

    @carbon_tax.setter
    def carbon_tax(self, nominal_price):
        self._real_carbon_tax = nominal_price / self.price_index

    def _summer_factor(self):
        month_angle = 2 * math.pi * (self.current_month - 1) / 12
        return math.cos(month_angle - 2 * math.pi * 6 / 12)

    def seasonal_demand_multiplier(self, month):
        """Shared deterministic seasonality for dispatch and planning forecasts."""
        summer = math.cos(2 * math.pi * (month - 1) / 12 - math.pi)
        if self.climate == 'hot':
            return 1.0 + 0.35 * summer
        if self.climate == 'cold':
            return 1.0 - 0.35 * summer
        return 1.0 + 0.20 * abs(summer)

    def update_seasonal_conditions(self):
        summer = self._summer_factor()

        lat_frac = self.latitude / 65.0
        solar_amplitude = 0.35 * lat_frac
        solar_baseline = 0.65 - 0.25 * lat_frac
        self.region_sunlight_level = max(0.05, min(1.0,
            solar_baseline + solar_amplitude * summer + random.uniform(-0.05, 0.05)))

        self.region_wind_level = max(0.05, min(1.0,
            0.5 - 0.2 * summer + random.uniform(-0.1, 0.1)))

        self.demand_multiplier = self.seasonal_demand_multiplier(self.current_month)

    def update_gas_price(self):
        """Move the real gas price; the quoted nominal price also follows inflation."""
        self.last_gas_event_msg = None

        # 1. Maybe trigger a new geopolitical event.
        if random.random() < GAS_EVENT_MONTHLY_CHANCE:
            event = random.choice(GAS_EVENTS)
            # Apply an immediate one-time shock to the price.
            self._real_natural_gas_price *= event["shock"]
            # Spread residual monthly pressure over the event's duration.
            # shock > 1 => upward pressure; shock < 1 => downward.
            monthly_pressure = (event["shock"] - 1.0) * 0.15
            self.active_gas_events.append({
                "name": event["name"],
                "months_left": event["duration"],
                "monthly_pressure": monthly_pressure,
            })
            self.last_gas_event_msg = f"GEOPOLITICAL EVENT: {event['name']}"

        # 2. Apply ongoing pressure from active events, then age them out.
        still_active = []
        for ev in self.active_gas_events:
            self._real_natural_gas_price *= (1.0 + ev["monthly_pressure"])
            ev["months_left"] -= 1
            if ev["months_left"] > 0:
                still_active.append(ev)
        self.active_gas_events = still_active

        # 3. Mean reversion toward the base price.
        self._real_natural_gas_price += (
            (NATURAL_GAS_BASE_COST_PER_MWH - self._real_natural_gas_price)
            * GAS_PRICE_MEAN_REVERSION
        )

        # 4. Baseline random noise.
        self._real_natural_gas_price *= (1.0 + random.uniform(
            -GAS_PRICE_MONTHLY_VOLATILITY, GAS_PRICE_MONTHLY_VOLATILITY))

        # 5. Clamp to sane bounds.
        self._real_natural_gas_price = max(NATURAL_GAS_MIN_COST_PER_MWH,
                                          min(NATURAL_GAS_MAX_COST_PER_MWH,
                                              self._real_natural_gas_price))

    def update_demand_growth(self):
        """Advance the long-run demand index: baseline growth + economic events."""
        self.last_demand_event_msg = None

        # Baseline compounding growth.
        self.demand_index *= (1 + MONTHLY_DEMAND_GROWTH)

        # Maybe trigger a new economic event.
        if random.random() < DEMAND_EVENT_MONTHLY_CHANCE:
            event = random.choice(DEMAND_EVENTS)
            self.demand_index *= event["shock"]  # immediate step change
            monthly_pressure = (event["shock"] - 1.0) * 0.10  # residual drift
            self.active_demand_events.append({
                "name": event["name"],
                "months_left": event["duration"],
                "monthly_pressure": monthly_pressure,
            })
            self.last_demand_event_msg = f"ECONOMIC EVENT: {event['name']}"

        # Apply ongoing pressure from active events, then age them out.
        still_active = []
        for ev in self.active_demand_events:
            self.demand_index *= (1 + ev["monthly_pressure"])
            ev["months_left"] -= 1
            if ev["months_left"] > 0:
                still_active.append(ev)
        self.active_demand_events = still_active

    def update_carbon_policy(self):
        """Enact the carbon tax at a hidden date and escalate it thereafter."""
        self.last_carbon_event_msg = None
        if self._real_carbon_tax <= 0 and self.turn >= self._carbon_tax_start_turn:
            self._real_carbon_tax = self._carbon_tax_initial
            self.last_carbon_event_msg = (
                f"CARBON POLICY ENACTED: ${self.carbon_tax:.2f}/metric ton CO2; "
                f"scheduled to rise {self._carbon_tax_annual_growth * 100:.1f}% annually "
                "plus inflation"
            )
            return
        if self._real_carbon_tax > 0:
            monthly_growth = (1 + self._carbon_tax_annual_growth) ** (1 / 12) - 1
            self._real_carbon_tax *= 1 + monthly_growth
            if self.current_month == 1:
                self.last_carbon_event_msg = (
                    f"CARBON TAX ESCALATOR: tax is now ${self.carbon_tax:.2f}/metric ton CO2"
                )

    def advance_turn(self):
        self.turn += 1
        self.current_month += 1
        if self.current_month > TURNS_PER_YEAR:
            self.current_month = 1
            self.year += 1
        self.update_seasonal_conditions()
        self.update_gas_price()
        self.update_demand_growth()
        self.update_carbon_policy()

    def display_env_status(self):
        print(f"--- Environmental Conditions "
              f"({MONTH_NAMES[self.current_month - 1]}, YEAR {self.year}) ---")
        print(f"Location: Latitude {self.latitude:.1f}°N  |  Climate: {self.climate.upper()}")
        print(f"Sunlight Level: {self.region_sunlight_level:.2f} (0.0-1.0)")
        print(f"Wind Level: {self.region_wind_level:.2f} (0.0-1.0)")
        print(f"Seasonal Demand Multiplier: {self.demand_multiplier:.2f}")
        print(f"Natural Gas Price: ${self.natural_gas_price:.2f}/MWh "
              f"(inflation-adjusted base ${NATURAL_GAS_BASE_COST_PER_MWH * self.price_index:.2f})")
        if self.carbon_tax > 0:
            print(f"Carbon Tax: ${self.carbon_tax:.2f}/metric ton CO2")
        else:
            print("Carbon Tax: not yet enacted")
        if self.last_carbon_event_msg:
            print(f"  >>> {self.last_carbon_event_msg} <<<")
        if self.last_gas_event_msg:
            print(f"  >>> {self.last_gas_event_msg} <<<")
        if self.active_gas_events:
            print("  Ongoing gas-market events:")
            for ev in self.active_gas_events:
                print(f"    - {ev['name']} ({ev['months_left']} months left)")
        print(f"Demand Growth Index: {self.demand_index:.3f} "
              f"({(self.demand_index - 1) * 100:+.1f}% vs. start)")
        if self.last_demand_event_msg:
            print(f"  >>> {self.last_demand_event_msg} <<<")
        if self.active_demand_events:
            print("  Ongoing economic events:")
            for ev in self.active_demand_events:
                print(f"    - {ev['name']} ({ev['months_left']} months left)")


class PlayerState:
    def __init__(self, economy=None):
        self.economy = economy
        # Company scale determines territory and the inherited financing package.
        scale_value = random.uniform(MIN_COMPANY_SIZE, MAX_COMPANY_SIZE)
        self.company_value = scale_value
        self.cash = scale_value * random.uniform(0.03, 0.06)
        self.base_territory_mw = scale_value / 1_000_000
        self._dividend_initialized = False
        self.dividends_paid = 0
        self.reputation = 0.5
        self.approved_rate_increase = False

        self.power_plants = {
            'coal': 0,
            'natural_gas': 0,
            'nuclear': 0,
            'solar': 0,
            'wind': 0,
            'hydro': 0,
        }
        self.batteries = []
        self.ongoing_constructions = []
        self.hydro_sites_developed = 0
        self.plant_assets = []
        self._next_asset_id = 1
        self.wholesale_commitment_mw = 0.0  # positive = import; negative = export
        self.pending_wholesale_commitment_mw = None

        self._initialize_random_plants()
        self.battery_dispatch_mode = "after_gas"  # or "before_gas"

        self.debt = 0.0            # no more flat legacy debt; it's all bonds now
        self.bonds = []

        # Inherited plants carry original cost AND pre-game depreciation.
        # Size the debt ladder from their remaining book value to start at
        # the target debt/equity ratio, rather than inflating their cost basis.
        self.plant_gross_book_value = {plant: 0.0 for plant in self.power_plants}
        self.plant_accumulated_depreciation = {
            plant: 0.0 for plant in self.power_plants
        }
        self.battery_gross_book_value = 0.0
        self.battery_accumulated_depreciation = 0.0
        self._initialize_book_values()
        target_debt = self.total_asset_value() * OPENING_TARGET_DEBT_EQUITY / (1 + OPENING_TARGET_DEBT_EQUITY)
        self.baseline_starting_debt = target_debt / STARTING_DEBT_MULTIPLIER
        self._initialize_debt_ladder(target_debt)

        opening_book_equity = self.book_equity()
        self.paid_in_capital = opening_book_equity
        self.treasury_stock = 0.0
        self.de_ratio = target_debt / max(opening_book_equity, 1)

        # Use the book benchmark to choose a familiar share-count scale.
        # Once estimated TTM earnings are available, the opening market
        # capitalization is reset to the 10x earnings target.
        opening_market_cap = opening_book_equity * UTILITY_TARGET_PRICE_TO_BOOK
        target_initial_price = random.uniform(25, 55)
        self.shares_outstanding = max(1_000_000,
                                      int(opening_market_cap / target_initial_price))
        self.company_value = opening_market_cap
        self.equity = opening_market_cap
        self.annual_dividend_per_share = 0.0   # set after we know share price
        self.stock_price = 0.0                  # computed each turn

        self.investor_confidence = 0.5   # 0..1, starts neutral
        self.last_dividend_per_share = None  # to detect raises/cuts
        self.consecutive_maintained = 0      # streak of holding-or-raising
        self.shareholder_happiness = 75.0
        self.dividend_reference_price = 0.0
        self.dividend_high_water = 0.0
        self.months_without_raise = 0
        self.share_issuance_streak = 0
        self.share_buyback_streak = 0
        self.share_trade_year = 1
        self.share_trade_base_shares = self.shares_outstanding
        self.share_trade_base_value = 0.0
        self.shares_traded_this_year = 0
        self.share_notional_this_year = 0.0
        self.fired = False
        self._last_dividend_review_turn = None

        # The inherited ladder does not consume the first month's allowance.
        self.reset_monthly_ledgers()
        
    def _initialize_debt_ladder(self, target_debt):
        """Split starting debt into a ladder weighted toward longer maturities."""
        # Weight heavily toward long-dated debt (like a real utility's balance sheet).
        term_weights = {
            '6mo': 0.5,
            '1yr': 1.0,
            '2yr': 2.0,
            '5yr': 4.0,
            '10yr': 5.0,
            '20yr': 4.0,
        }
        total_w = sum(term_weights.values())

        for term_key, w in term_weights.items():
            portion = target_debt * (w / total_w)
            if portion < 1_000_000:
                continue
            term_years = BOND_TERMS[term_key]
            rate = random.uniform(*LEGACY_BOND_RATE_RANGE)
            bond = Bond(portion, rate, term_years, 0)

            # Age the bond only slightly, and never past ~40% of its life,
            # so long bonds keep most of their term remaining.
            max_age = int(bond.months_remaining * 0.4)
            if max_age > 0:
                bond.months_remaining -= random.randint(0, max_age)

            self.bonds.append(bond)

        print(f"Starting debt ladder: {len(self.bonds)} bonds "
              f"totaling ${self.total_bond_debt():,.0f}.")
        
    def _initialize_book_values(self):
        inherited = []
        for plant_type, count in self.power_plants.items():
            life_months = ASSET_USEFUL_LIFE_YEARS[plant_type] * 12
            for _ in range(count):
                age = random.randint(*(int(life_months * fraction)
                                       for fraction in OPENING_PLANT_AGE_FRACTION_RANGE))
                inherited.append((plant_type, age))
        raw_plant_cost = sum(
            count * PLANT_BUILD_COST.get(plant_type, 0)
            for plant_type, count in self.power_plants.items()
        )
        raw_net_plant = sum(
            PLANT_BUILD_COST[kind] * (1 - age / (ASSET_USEFUL_LIFE_YEARS[kind] * 12))
            for kind, age in inherited
        )
        minimum_equity = max(MIN_OPENING_BOOK_EQUITY, raw_plant_cost * 0.05)
        required_plant_basis = self.total_debt() + minimum_equity - self.cash
        self.opening_asset_cost_scale = max(
            1.0, required_plant_basis / max(raw_net_plant, 1)
        )
        for plant_type, age in inherited:
            self._add_plant_asset(plant_type, PLANT_BUILD_COST[plant_type]
                                  * self.opening_asset_cost_scale, months_in_service=age)
        if self.opening_asset_cost_scale > 1.0001:
            print("Opening plant purchase basis was increased "
                  f"{(self.opening_asset_cost_scale - 1) * 100:.1f}% so book equity "
                  "remains positive after inherited depreciation and debt.")

    @property
    def price_index(self):
        return getattr(self.economy, 'price_index', 1.0)

    def _add_plant_asset(self, plant_type, cost, months_in_service=0,
                         purchase_price_index=None):
        life_months = ASSET_USEFUL_LIFE_YEARS[plant_type] * 12
        accumulated = cost * min(1.0, months_in_service / life_months)
        asset = PlantAsset(self._next_asset_id, plant_type, cost,
                           accumulated_depreciation=accumulated,
                           months_in_service=months_in_service,
                           purchase_price_index=(self.price_index if purchase_price_index is None
                                                 else purchase_price_index))
        self._next_asset_id += 1
        self.plant_assets.append(asset)
        self._sync_plant_book_values()
        return asset

    def _sync_plant_book_values(self):
        """Keep aggregate balance-sheet totals in sync with the unit register."""
        self.plant_gross_book_value = dict.fromkeys(self.power_plants, 0.0)
        self.plant_accumulated_depreciation = dict.fromkeys(self.power_plants, 0.0)
        self.battery_gross_book_value = 0.0
        self.battery_accumulated_depreciation = 0.0
        for asset in self.plant_assets:
            if asset.plant_type == 'battery':
                self.battery_gross_book_value += asset.original_cost
                self.battery_accumulated_depreciation += asset.accumulated_depreciation
            else:
                self.plant_gross_book_value[asset.plant_type] += asset.original_cost
                self.plant_accumulated_depreciation[asset.plant_type] += asset.accumulated_depreciation

    def gross_utility_plant(self):
        return sum(self.plant_gross_book_value.values()) + self.battery_gross_book_value

    def accumulated_depreciation(self):
        return (sum(self.plant_accumulated_depreciation.values())
                + self.battery_accumulated_depreciation)

    def net_utility_plant(self):
        return max(0.0, self.gross_utility_plant() - self.accumulated_depreciation())

    def construction_work_in_progress(self):
        return sum(project.get('cost_paid', 0.0)
                   for project in self.ongoing_constructions)

    def total_asset_value(self):
        return self.cash + self.net_utility_plant() + self.construction_work_in_progress()

    def book_equity(self):
        """Accounting equity: assets at purchase cost, less debt."""
        return self.total_asset_value() - self.total_debt()

    def monthly_depreciation(self, post=False):
        """Depreciate each unit separately; old units cannot write down new ones."""
        total = 0.0
        for asset in self.plant_assets:
            expense = asset.monthly_depreciation
            total += expense
            if post:
                asset.accumulated_depreciation += expense
                asset.months_in_service += 1
                asset.last_month_depreciation = expense
        if post:
            self._sync_plant_book_values()
        return total

    def reset_monthly_ledgers(self):
        self.capital_expenditures_since_close = 0.0
        self.asset_sale_proceeds_since_close = 0.0
        self.debt_issued_since_close = 0.0
        self.debt_repaid_since_close = 0.0
        self.dividends_since_close = 0.0
        self.disposal_gain_loss_since_close = 0.0
        self.debt_gain_loss_since_close = 0.0
        self.stock_issued_since_close = 0.0
        self.stock_bought_since_close = 0.0
        # Fix the allowance for the coming month using non-cash book assets.
        # Cash from borrowing never enlarges it, even at the next month close.
        self.borrowing_asset_base = max(
            0.0, self.net_utility_plant() + self.construction_work_in_progress()
        )
        self.monthly_borrowing_limit = round(
            self.borrowing_asset_base * MONTHLY_BORROWING_ASSET_FRACTION, 2
        )

    def remaining_borrowing_capacity(self):
        """Unused gross issuance allowance; repayments do not replenish it."""
        return max(0.0, self.monthly_borrowing_limit - self.debt_issued_since_close)

    def _borrowing_request_allowed(self, amount):
        if (not isinstance(amount, (int, float)) or isinstance(amount, bool)
                or not math.isfinite(amount) or amount <= 0):
            print("Borrowing failed: enter a finite, positive dollar amount.")
            return False
        remaining = self.remaining_borrowing_capacity()
        if amount > remaining:
            print(f"Borrowing failed: only ${remaining:,.2f} remains of this month's "
                  f"${self.monthly_borrowing_limit:,.2f} limit. Bonds and emergency "
                  "loans share the limit; repayments do not restore it.")
            return False
        return True

    def emergency_loan(self, amount):
        """Last-resort loan, subject to the same monthly cap as ordinary bonds."""
        if not self._borrowing_request_allowed(amount):
            return None
        rate = 0.18  # punishing 18% APR
        bond = Bond(amount, rate, 1, 0)  # 1-year term
        self.bonds.append(bond)
        self.cash += amount
        self.debt_issued_since_close += amount
        print(f"!!! EMERGENCY LOAN: borrowed ${amount:,.0f} at {rate*100:.0f}% APR. "
              f"This will hurt. !!!")
        return bond

    def update_stock_price(self, economy, trailing_annual_earnings, trailing_eps=None):
        # --- 1. Earnings-based value (P/E) ---
        eps = (trailing_annual_earnings / max(self.shares_outstanding, 1)
               if trailing_eps is None else trailing_eps)
        utility_pe = max(6.0, economy.market_pe * 0.85)
        # Signed earnings keep valuation monotonic through zero: losses must
        # not suddenly receive the old, more generous book-value fallback.
        earnings_value = eps * utility_pe
        self.valuation_eps = eps
        self.valuation_pe = utility_pe
        self.earnings_price_target = earnings_value

        # --- 2. Book-value anchor ---
        book_equity = max(1.0, self.book_equity())
        book_value_per_share = book_equity / max(self.shares_outstanding, 1)
        price_to_book_value = book_value_per_share * UTILITY_TARGET_PRICE_TO_BOOK

        # --- 3. Dividend Discount Model value ---
        # price = D / (r - g). r = required return, g = assumed dividend growth.
        required_return = economy.interest_rate + REQUIRED_RETURN_PREMIUM
        div_growth = 0.02  # assume ~2% long-run dividend growth
        denom = max(0.01, required_return - div_growth)
        if self.annual_dividend_per_share > 0:
            dividend_value = self.annual_dividend_per_share / denom
        else:
            dividend_value = 0.0  # no dividend -> no DDM contribution

        # --- 4. Blend the three into a fair value ---
        fair_value = (
            BOOK_VALUE_WEIGHT * price_to_book_value
            + EARNINGS_WEIGHT * earnings_value
            + DIVIDEND_WEIGHT * dividend_value
        )
            
        # --- Investor confidence premium/discount (-15% to +15%) ---
        confidence_adj = 1.0 + (self.investor_confidence - 0.5) * 0.30
        fair_value *= confidence_adj
        
        # --- 5. Yield sanity: reward/punish vs. prevailing bond yields ---
        if self.stock_price > 0:
            current_yield = self.annual_dividend_per_share / self.stock_price
            yield_gap = current_yield - required_return
            fair_value *= (1 + max(-0.15, min(0.15, yield_gap * 1.5)))

        fair_value = max(0.50, fair_value)
        self.fair_stock_price = fair_value

        # --- 6. Smooth toward fair value instead of snapping ---
        if self.stock_price <= 0:
            self.stock_price = max(0.50, eps * OPENING_TARGET_PE)
        else:
            self.stock_price += (fair_value - self.stock_price) * STOCK_SMOOTHING

        # --- 7. Market noise ---
        self.stock_price *= (1 + random.uniform(-STOCK_MONTHLY_NOISE, STOCK_MONTHLY_NOISE))
        self.stock_price = max(0.50, self.stock_price)

        self.company_value = self.stock_price * self.shares_outstanding

        if not self._dividend_initialized:
            self.annual_dividend_per_share = self.stock_price * 0.035
            self._dividend_initialized = True
            self.dividend_reference_price = self.stock_price
            self.dividend_high_water = self.annual_dividend_per_share
            self.last_dividend_per_share = self.annual_dividend_per_share
            self.share_trade_base_value = self.company_value

    # Decommissioning: (salvage_fraction, teardown_cost) — nuclear is expensive to retire.

    def decommission_plant(self, plant_type, quantity=1):
        quantity = int(quantity)
        owned = self.power_plants.get(plant_type, 0)
        if quantity < 1:
            print("Retirement quantity must be at least one.")
            return False
        if owned < quantity:
            print(f"Cannot retire {quantity} {plant_type} plants; only {owned} are owned.")
            return False
        salvage_frac, teardown = DECOMMISSION_INFO[plant_type]
        # Retire newest units first, consistently with battery retirement.
        retired = [asset for asset in self.plant_assets
                   if asset.plant_type == plant_type][-quantity:]
        net = sum(asset.inflation_adjusted_cost(self.price_index) * salvage_frac
                  - teardown * self.price_index for asset in retired)
        net_book_removed = sum(asset.net_book_value for asset in retired)
        for asset in retired:
            self.plant_assets.remove(asset)
        self._sync_plant_book_values()
        self.power_plants[plant_type] -= quantity
        self.cash += net
        self.asset_sale_proceeds_since_close += net
        self.disposal_gain_loss_since_close += net - net_book_removed
        noun = "plant" if quantity == 1 else "plants"
        if net >= 0:
            print(f"Decommissioned {quantity} {plant_type} {noun}. Net proceeds: ${net:,.0f} "
                  f"(salvage less teardown).")
        else:
            print(f"Decommissioned {quantity} {plant_type} {noun}. Net cost: ${-net:,.0f} "
                  f"(teardown less salvage).")
        return True

    def decommission_battery(self, quantity=1):
        quantity = int(quantity)
        if quantity < 1:
            print("Retirement quantity must be at least one.")
            return False
        if len(self.batteries) < quantity:
            print(f"Cannot retire {quantity} batteries; only {len(self.batteries)} are owned.")
            return False
        retired = [asset for asset in self.plant_assets
                   if asset.plant_type == 'battery'][-quantity:]
        net_book_removed = sum(asset.net_book_value for asset in retired)
        for _ in range(quantity):
            self.batteries.pop()
        salvage = sum(asset.inflation_adjusted_cost(self.price_index) * 0.10 for asset in retired)
        for asset in retired:
            self.plant_assets.remove(asset)
        self._sync_plant_book_values()
        self.cash += salvage
        self.asset_sale_proceeds_since_close += salvage
        self.disposal_gain_loss_since_close += salvage - net_book_removed
        noun = "unit" if quantity == 1 else "units"
        print(f"Decommissioned {quantity} battery {noun}. Salvage: ${salvage:,.0f}.")
        return True

    def wholesale_trade(self, mw, direction, economy):
        """Replace the recurring net contract, effective starting next month."""
        if (direction not in ('buy', 'sell') or not isinstance(mw, (int, float))
                or isinstance(mw, bool) or not math.isfinite(mw) or mw < 0):
            print("Power contract failed: choose buy or sell and a finite, nonnegative MW amount.")
            return False
        self.pending_wholesale_commitment_mw = mw if direction == 'buy' else -mw
        if mw == 0:
            print("Recurring power contract will stop next month.")
        else:
            factor = CONTRACT_BUY_FACTOR if direction == 'buy' else CONTRACT_SELL_FACTOR
            price = wholesale_market_price(economy) * factor
            amount = mw * HOURS_PER_MONTH * price
            print(f"Starting next month: {direction.upper()} {mw:,.0f} MW every month "
                  f"until changed. Estimated monthly {'cost' if direction == 'buy' else 'revenue'}: "
                  f"${amount:,.0f} ({HOURS_PER_MONTH:.0f} hours at ${price:.2f}/MWh). "
                  "Price follows the market each month; this replaces the previous commitment.")
        return True

    def activate_power_contract(self):
        if self.pending_wholesale_commitment_mw is not None:
            self.wholesale_commitment_mw = self.pending_wholesale_commitment_mw
            self.pending_wholesale_commitment_mw = None

    def dividend_yield(self):
        return self.annual_dividend_per_share / max(self.stock_price, 0.01)

    def shareholder_status(self):
        if self.fired:
            return 'FIRED: shareholder confidence in your leadership has collapsed.'
        warning = 'WARNING — ' if self.shareholder_happiness < 35 else ''
        return (f'{warning}Shareholder happiness {self.shareholder_happiness:.0f}/100; '
                f'dividend yield {self.dividend_yield():.2%}. '
                'Cuts cost 50 points; 10 or less means dismissal.')

    def _change_happiness(self, change):
        self.shareholder_happiness = max(0.0, min(SHAREHOLDER_MAX_HAPPINESS,
                                                 self.shareholder_happiness + change))
        if self.shareholder_happiness <= SHAREHOLDER_FIRING_THRESHOLD:
            self.fired = True

    def review_dividend_policy(self, game_state):
        """Review once per close; dividend cuts cannot be undone by a lower stock quote."""
        if self.fired or self._last_dividend_review_turn == game_state.turn:
            return
        self._last_dividend_review_turn = game_state.turn
        # The opening reference protects against deliberately crashing the price
        # to make a tiny dividend appear generous. Inflation preserves its real value.
        reference = max(self.stock_price, self.dividend_reference_price * self.price_index, .01)
        policy_yield = self.annual_dividend_per_share / reference
        change = max(-4.0, min(2.0, -4 + 6 * (policy_yield - .02) / .01))
        if self.annual_dividend_per_share > self.dividend_high_water * 1.005:
            self.months_without_raise = 0
            self.dividend_high_water = self.annual_dividend_per_share
            change += 2.0  # only one qualifying raise reward per monthly close
        else:
            self.months_without_raise += 1
            if self.months_without_raise >= 12:
                change -= .25
        if self.stock_issued_since_close > 0:
            self.share_issuance_streak += 1
            self.share_buyback_streak = 0
            size = min(1.0, self.stock_issued_since_close / max(self.share_trade_base_value * .002, 1))
            change -= (2 + min(3, self.share_issuance_streak)) * size
        elif self.stock_bought_since_close > 0:
            self.share_buyback_streak += 1
            self.share_issuance_streak = 0
            size = min(1.0, self.stock_bought_since_close / max(self.share_trade_base_value * .002, 1))
            change += min(3, self.share_buyback_streak) * size
        else:
            self.share_issuance_streak = self.share_buyback_streak = 0
        self._change_happiness(change)
        if self.shareholder_happiness < 35:
            print(self.shareholder_status())

    def reset_annual_share_allowance(self, year):
        if year != self.share_trade_year:
            self.share_trade_year = year
            self.share_trade_base_shares = self.shares_outstanding
            self.share_trade_base_value = self.company_value
            self.shares_traded_this_year = 0
            self.share_notional_this_year = 0.0

    def remaining_share_allowance(self):
        share_cap = int(self.share_trade_base_shares * ANNUAL_SHARE_TRADE_LIMIT)
        value_left = max(0, self.share_trade_base_value * ANNUAL_SHARE_TRADE_LIMIT
                         - self.share_notional_this_year)
        return max(0, min(share_cap - self.shares_traded_this_year,
                          int(value_left / max(self.stock_price, .01))))

    def trade_shares(self, action, quantity, game_state):
        if (self.fired or action not in ('issue', 'buyback') or isinstance(quantity, bool)
                or not isinstance(quantity, int) or quantity <= 0):
            print('Stock transaction rejected: enter a positive whole number of shares.')
            return False
        self.reset_annual_share_allowance(game_state.year)
        if quantity > self.remaining_share_allowance():
            print('Stock transaction exceeds the combined 4.9% annual share/value allowance.')
            return False
        notional = quantity * self.stock_price
        if action == 'buyback':
            cost = notional * (1 + SHARE_TRADE_SPREAD)
            if self.cash < cost or quantity >= self.shares_outstanding:
                print('Stock buyback rejected: insufficient cash or shares.')
                return False
            self.cash -= cost
            self.shares_outstanding -= quantity
            self.treasury_stock += cost
            self.stock_bought_since_close += cost
        else:
            proceeds = notional * (1 - SHARE_TRADE_SPREAD)
            self.cash += proceeds
            self.shares_outstanding += quantity
            self.paid_in_capital += proceeds
            self.stock_issued_since_close += proceeds
        self.shares_traded_this_year += quantity
        self.share_notional_this_year += notional
        self.company_value = self.stock_price * self.shares_outstanding
        self.equity = self.company_value
        print(f'Stock {action}: {quantity:,} shares at ${self.stock_price:.2f}, '
              'with a 1% execution spread. Annual allowance is shared by issues and buybacks.')
        return True

    def pay_quarterly_dividend(self, game_state):
        if game_state.current_month in (3, 6, 9, 12):
            quarterly = self.annual_dividend_per_share / 4 * self.shares_outstanding
            self.cash -= quarterly
            self.dividends_paid += quarterly
            self.dividends_since_close += quarterly
            print(f"Paid quarterly dividend: ${quarterly:,.0f} "
                  f"(${self.annual_dividend_per_share/4:.3f}/share).")
        self.reward_dividend_consistency(game_state)  # update confidence streak

    def set_dividend(self, new_annual_per_share):
        if not math.isfinite(new_annual_per_share) or new_annual_per_share < 0:
            print('Dividend change failed: enter a finite, nonnegative amount.')
            return False
        new_div = max(0.0, new_annual_per_share)
        old_div = self.annual_dividend_per_share

        if old_div > 0:
            change = (new_div - old_div) / old_div
            if new_div < old_div:
                self._change_happiness(-SHAREHOLDER_MAX_HAPPINESS / 2)
                print('Dividend cut: shareholder happiness loses 50 points.')
            if new_div == 0:
                # Suspending the dividend is severely punished.
                self.investor_confidence = max(0.0, self.investor_confidence - 0.35)
                self.consecutive_maintained = 0
                print("!!! Dividend SUSPENDED — investors flee. Confidence crashes. !!!")
            elif change < -0.001:
                # A cut hurts, scaled by how deep the cut is.
                self.investor_confidence = max(0.0, self.investor_confidence + change * 0.8)
                self.consecutive_maintained = 0
                print(f"Dividend CUT by {-change*100:.1f}% — investor confidence drops.")
            elif change > 0.001:
                # A raise is rewarded modestly.
                self.investor_confidence = min(1.0, self.investor_confidence + min(0.08, change * 0.5))
                print(f"Dividend RAISED by {change*100:.1f}% — investors pleased.")
            # (holding steady is handled per-turn in reward_dividend_consistency)

        self.annual_dividend_per_share = new_div
        yield_pct = new_div / max(self.stock_price, 0.01) * 100
        print(f"Annual dividend set to ${new_div:.3f}/share (yield ~{yield_pct:.2f}%).")
        if self.shareholder_happiness < 35:
            print(self.shareholder_status())
        return True

    def reward_dividend_consistency(self, game_state):
        """Called each quarter: reward holding/growing the dividend over time."""
        if game_state.current_month in (3, 6, 9, 12):
            if self.last_dividend_per_share is not None:
                if self.annual_dividend_per_share > self.last_dividend_per_share:
                    self.consecutive_maintained += 1
                    # Slow confidence build for a reliable payer.
                    self.investor_confidence = min(1.0, self.investor_confidence + 0.02
                                                   + min(0.03, self.consecutive_maintained * 0.002))
                else:
                    self.consecutive_maintained = 0
            self.last_dividend_per_share = self.annual_dividend_per_share

    def display_equity(self):
        yield_pct = (self.annual_dividend_per_share / max(self.stock_price, 0.01)) * 100
        print("\n--- Equity ---")
        print(f"Stock Price: ${self.stock_price:,.2f}")
        print(f"Shares Outstanding: {self.shares_outstanding:,}")
        print(f"Market Cap: ${self.company_value:,.0f}")
        print(f"Dividend: ${self.annual_dividend_per_share:.3f}/share/yr "
              f"(yield {yield_pct:.2f}%)")
        print(f"Investor Confidence: {self.investor_confidence:.2f} "
              f"({self.consecutive_maintained} quarters of steady/growing dividend)")
        
    def total_bond_debt(self):
        return sum(b.principal for b in self.bonds)

    def total_debt(self):
        return self.debt + self.total_bond_debt()

    def net_debt(self):
        """Outstanding principal less cash (negative means a net cash position)."""
        return self.total_debt() - self.cash

    # PlayerState.issue_bond
    def issue_bond(self, principal, economy, term_key, credit):
        if not credit.can_borrow:
            print("Bond issuance FAILED: your credit rating is 'D' — no one will lend to you.")
            return None
        if term_key not in BOND_TERMS:
            print("Bond issuance failed: invalid bond term.")
            return None
        if not self._borrowing_request_allowed(principal):
            return None
        term_years = BOND_TERMS[term_key]
        rate = economy.bond_rate(term_years, credit.spread)
        bond = Bond(principal, rate, term_years, 0)
        self.bonds.append(bond)
        self.cash += principal
        self.debt_issued_since_close += principal
        print(f"Issued ${principal:,.0f} {term_key} bond at {rate*100:.2f}% APR "
              f"(rating {credit.rating}).")
        return bond

    def bond_market_yield(self, bond, economy, credit):
        """Yield investors would demand today for this bond's remaining term."""
        spread = credit.spread if credit.spread is not None else 0.20
        remaining_years = max(1 / 12, bond.months_remaining / 12)
        return economy.bond_rate(remaining_years, spread)

    def bond_buyback_quote(self, bond, economy, credit):
        market_yield = self.bond_market_yield(bond, economy, credit)
        clean_value = bond.market_value(market_yield)
        settlement = clean_value * (1 + BOND_BUYBACK_TRANSACTION_COST)
        return settlement, market_yield, clean_value

    def buy_back_bond(self, bond, economy, credit):
        if bond not in self.bonds:
            print("Bond buyback failed: that bond is no longer outstanding.")
            return False
        settlement, market_yield, clean_value = self.bond_buyback_quote(
            bond, economy, credit
        )
        if self.cash < settlement:
            print(f"Bond buyback failed: settlement costs ${settlement:,.0f}, "
                  f"but cash is only ${self.cash:,.0f}.")
            return False
        self.cash -= settlement
        self.bonds.remove(bond)
        self.debt_repaid_since_close += settlement
        self.debt_gain_loss_since_close += bond.principal - settlement
        premium_discount = clean_value - bond.principal
        relation = "premium" if premium_discount >= 0 else "discount"
        print(f"Bought back ${bond.principal:,.0f} principal for ${settlement:,.0f} "
              f"at a {market_yield * 100:.2f}% market yield "
              f"(${abs(premium_discount):,.0f} {relation} to par before fees).")
        return True

    def process_bonds(self):
        """Pay monthly interest and retire matured bonds. Returns interest paid."""
        interest_paid = 0
        matured = []
        for b in self.bonds:
            interest_paid += b.monthly_interest()
            b.months_remaining -= 1
            if b.months_remaining <= 0:
                matured.append(b)
        self.cash -= interest_paid
        for b in matured:
            self.cash -= b.principal  # repay principal at maturity
            self.debt_repaid_since_close += b.principal
            self.bonds.remove(b)
            print(f"Bond matured: repaid ${b.principal:,.0f} principal.")
        return interest_paid

    def _initialize_random_plants(self):
        self.power_plants = generate_random_plant_mix()

        # Hard-mode opening: the inherited fleet has no renewable generation,
        # and its nuclear fleet is about half the size of the prior scenario.
        nuclear_units = int(round(
            (self.base_territory_mw / 1000) * STARTING_NUCLEAR_UNITS_PER_1000_MW
        ))
        self.power_plants['nuclear'] = max(0, nuclear_units)

        def firm_fleet_capacity():
            firm = 0
            firm += self.power_plants['coal'] * COAL_PLANT_CAPACITY * CAPACITY_CREDIT['coal']
            firm += self.power_plants['natural_gas'] * NATURAL_GAS_PLANT_CAPACITY * CAPACITY_CREDIT['natural_gas']
            firm += self.power_plants['nuclear'] * NUCLEAR_PLANT_CAPACITY * CAPACITY_CREDIT['nuclear']
            firm += self.power_plants['solar'] * SOLAR_PLANT_CAPACITY * CAPACITY_CREDIT['solar']
            firm += self.power_plants['wind'] * WIND_PLANT_CAPACITY * CAPACITY_CREDIT['wind']
            firm += self.power_plants['hydro'] * HYDRO_PLANT_CAPACITY * CAPACITY_CREDIT['hydro']
            return firm

        # Target: cover PEAK demand plus the reserve margin, using FIRM capacity.
        # Peak = territory * worst-case seasonal multiplier (~1.35 in hot/cold climates).
        peak_demand = self.base_territory_mw * 1.35
        target = peak_demand * (1 + TARGET_RESERVE_MARGIN)  # ~15% cushion above peak

        # Fill the inherited reliability requirement only with fossil units.
        # Clean generation must be developed by the player after game start.
        build_weights = {'coal': 38, 'natural_gas': 62}
        types = list(build_weights.keys())
        weights = list(build_weights.values())

        max_additions = 200
        additions = 0
        while firm_fleet_capacity() < target and additions < max_additions:
            choice = random.choices(types, weights=weights, k=1)[0]
            self.power_plants[choice] += 1
            additions += 1

    def construction_cost(self, plant_type, additional_hydro_sites=0):
        if plant_type == 'hydro':
            developed = self.hydro_sites_developed
            developed += sum(1 for project in self.ongoing_constructions
                             if project['type'] == 'hydro')
            site_number = developed + additional_hydro_sites
            return HYDRO_BASE_CONSTRUCTION_COST * self.price_index * (
                1 + HYDRO_SITE_COST_ESCALATION * (site_number ** 1.25)
            )
        cost_map = {
            'coal': COAL_CONSTRUCTION_COST,
            'natural_gas': NATURAL_GAS_CONSTRUCTION_COST,
            'nuclear': NUCLEAR_CONSTRUCTION_COST,
            'solar': SOLAR_CONSTRUCTION_COST,
            'wind': WIND_CONSTRUCTION_COST,
            'battery': BATTERY_CONSTRUCTION_COST,
        }
        base_cost = cost_map.get(plant_type)
        learning = self.economy.technology_cost_factor(plant_type) if self.economy else 1.0
        return None if base_cost is None else base_cost * learning * self.price_index

    def construction_quote(self, plant_type, quantity=1):
        quantity = int(quantity)
        if quantity < 1:
            return 0
        if plant_type == 'hydro':
            return sum(self.construction_cost('hydro', offset) for offset in range(quantity))
        unit_cost = self.construction_cost(plant_type)
        return None if unit_cost is None else unit_cost * quantity

    def start_construction(self, plant_type, quantity=1):
        quantity = int(quantity)
        time_map = {
            'coal': COAL_CONSTRUCTION_TIME,
            'natural_gas': NATURAL_GAS_CONSTRUCTION_TIME,
            'nuclear': NUCLEAR_CONSTRUCTION_TIME,
            'solar': SOLAR_CONSTRUCTION_TIME,
            'wind': WIND_CONSTRUCTION_TIME,
            'battery': BATTERY_CONSTRUCTION_TIME,
            'hydro': HYDRO_CONSTRUCTION_TIME,
        }

        if plant_type not in time_map:
            print(f"Invalid plant type: {plant_type}")
            return False
        if quantity < 1:
            print("Construction quantity must be at least one.")
            return False

        individual_costs = ([self.construction_cost('hydro', offset)
                             for offset in range(quantity)]
                            if plant_type == 'hydro'
                            else [self.construction_cost(plant_type)] * quantity)
        construction_cost = sum(individual_costs)
        construction_time = time_map[plant_type]

        if self.cash < construction_cost:
            print(f"Insufficient funds to start {plant_type} construction. "
                  f"Need ${construction_cost:,.2f}, have ${self.cash:,.2f}.")
            return False

        self.cash -= construction_cost
        self.capital_expenditures_since_close += construction_cost
        for unit_cost in individual_costs:
            self.ongoing_constructions.append({
                'type': plant_type,
                'turns_remaining': construction_time,
                'cost_paid': unit_cost,
                'total_cost': unit_cost,
                'initial_cost': unit_cost,
                'price_index_at_start': self.price_index,
                'real_cost_basis': unit_cost / self.price_index,
            })
        noun = "project" if quantity == 1 else "projects"
        print(f"Started {quantity} {plant_type} {noun}. Total cost: "
              f"${construction_cost:,.2f}; completion in {construction_time} months.")
        return True

    def update_constructions(self):
        completed_projects = []
        for project in self.ongoing_constructions:
            project['turns_remaining'] -= 1

            # Cost overruns, especially for long projects like nuclear.
            if project['type'] == 'nuclear' and project['turns_remaining'] > 0 and random.random() < 0.05:
                # Prepaid construction stays at its contracted nominal price.
                # New overrun work is priced in today's dollars, not start-date dollars.
                overrun_amount = (project['initial_cost'] * random.uniform(0.01, 0.05)
                                  * self.price_index / project.get('price_index_at_start', 1.0))
                real_basis = project.get('real_cost_basis', project['total_cost']
                                         / project.get('price_index_at_start', 1.0))
                project['real_cost_basis'] = real_basis + overrun_amount / self.price_index
                project['total_cost'] += overrun_amount
                project['cost_paid'] += overrun_amount
                self.cash -= overrun_amount
                self.capital_expenditures_since_close += overrun_amount
                print(f"Cost overrun detected for {project['type']} plant! "
                      f"New total cost: ${project['total_cost']:,.2f} (+${overrun_amount:,.2f}).")

            if project['turns_remaining'] <= 0:
                completed_projects.append(project)

        completion_counts = {}
        for project in completed_projects:
            self.ongoing_constructions.remove(project)
            if project['type'] == 'battery':
                self.batteries.append({
                    'max_capacity': BATTERY_ENERGY_CAPACITY,
                    'current_capacity': BATTERY_ENERGY_CAPACITY,
                    'max_power': BATTERY_POWER_CAPACITY,
                    'stored_energy': 0.0,
                })
            else:
                self.power_plants[project['type']] += 1
                if project['type'] == 'hydro':
                    self.hydro_sites_developed += 1
            real_basis = project.get('real_cost_basis', project['total_cost'] / self.price_index)
            self._add_plant_asset(project['type'], project['total_cost'],
                                  purchase_price_index=project['total_cost'] / real_basis)
            completion_counts[project['type']] = completion_counts.get(project['type'], 0) + 1
        for plant_type, count in completion_counts.items():
            noun = "unit" if count == 1 else "units"
            print(f"Construction complete! {count} new {plant_type} {noun} added.")

    def display_player_status(self):
        print("\n--- Player Financials ---")
        print(f"Cash: ${self.cash:,.2f}")
        print(f"Debt: ${self.total_debt():,.2f}")
        print(f"Company Value: ${self.company_value:,.2f}")
        print(f"Debt-to-Equity Ratio: {self.total_debt() / max(self.equity, 1):.2f}")
        print(f"Reputation: {self.reputation:.2f} (0.0-1.0)")
        print("\n--- Player Assets ---")
        label_map = {
            'coal': 'Coal',
            'natural_gas': 'Natural Gas',
            'nuclear': 'Nuclear',
            'solar': 'Solar',
            'wind': 'Wind',
            'hydro': 'Hydro',
        }
        for plant_type, count in self.power_plants.items():
            if count > 0:
                print(f"{label_map[plant_type]} Plants: {count}")
        total_batt = sum(b.get('max_power', BATTERY_POWER_CAPACITY)
                         for b in self.batteries) if self.batteries else 0
        print(f"Batteries: {len(self.batteries)} units "
              f"(total power: {total_batt:.2f} MW)")

        if self.ongoing_constructions:
            print("\n--- Ongoing Constructions ---")
            for project in self.ongoing_constructions:
                print(f"  - {label_map.get(project['type'], project['type'].capitalize())} Plant: "
                      f"{project['turns_remaining']} months remaining "
                      f"(Cost Paid: ${project['cost_paid']:,.2f} / Total: ${project['total_cost']:,.2f})")

        if self.batteries:
            total_stored = sum(b['stored_energy'] for b in self.batteries)
            total_usable = sum(b['current_capacity'] for b in self.batteries)
            total_nameplate = sum(b['max_capacity'] for b in self.batteries)
            health = (total_usable / total_nameplate * 100) if total_nameplate else 0
            print(f"Batteries: {len(self.batteries)} units | "
                  f"stored {total_stored:.1f} MWh / usable {total_usable:.1f} MWh "
                  f"({health:.0f}% health)")
        else:
            print("Batteries: 0 units")


class PowerGrid:
    def __init__(self):
        self.total_generation = 0
        self.maximum_generation = 0
        self.total_demand = 0
        self.contract_imports_mw = 0.0
        self.contract_exports_mw = 0.0
        self.available_for_customers = 0.0
        self.spot_imports_mw = 0.0
        self.spot_exports_mw = 0.0
        self.current_surplus_deficit = 0
        self.gas_generation = 0
        self.battery_discharged = 0
        self.battery_charged = 0

    def _baseload(self, player_state, game_state):
        b = 0
        b += player_state.power_plants['nuclear'] * NUCLEAR_PLANT_CAPACITY
        b += player_state.power_plants['coal'] * COAL_PLANT_CAPACITY
        b += player_state.power_plants['solar'] * SOLAR_PLANT_CAPACITY * game_state.region_sunlight_level
        b += player_state.power_plants['wind'] * WIND_PLANT_CAPACITY * game_state.region_wind_level
        b += player_state.power_plants['hydro'] * HYDRO_PLANT_CAPACITY * HYDRO_OUTPUT_FACTOR
        return b

    def _discharge(self, player_state, needed):
        """Discharge batteries up to `needed` MW. Returns MW actually delivered."""
        delivered_total = 0
        for bat in player_state.batteries:
            if needed <= 0:
                break
            available = min(bat['stored_energy'],
                            bat.get('max_power', BATTERY_POWER_CAPACITY))
            if available <= 0:
                continue
            delivered = min(available, needed)
            bat['stored_energy'] -= delivered
            delivered_total += delivered
            needed -= delivered
            self._degrade_battery(bat, delivered)
        return delivered_total

    def _charge(self, player_state, surplus):
        """Charge batteries from `surplus` MW. Returns MW actually drawn from grid."""
        drawn_total = 0
        for bat in player_state.batteries:
            if surplus <= 0:
                break
            headroom = bat['current_capacity'] - bat['stored_energy']
            if headroom <= 0:
                continue
            drawn = min(surplus, bat.get('max_power', BATTERY_POWER_CAPACITY),
                        headroom / BATTERY_ROUND_TRIP_EFFICIENCY)
            stored = drawn * BATTERY_ROUND_TRIP_EFFICIENCY
            bat['stored_energy'] += stored
            drawn_total += drawn
            surplus -= drawn
            self._degrade_battery(bat, stored)
        return drawn_total

    def _degrade_battery(self, battery, energy_moved):
        if battery['max_capacity'] <= 0:
            return
        cycle_fraction = energy_moved / battery['max_capacity']
        loss = battery['max_capacity'] * BATTERY_DEGRADATION_PER_CYCLE * cycle_fraction
        battery['current_capacity'] = max(
            battery['max_capacity'] * BATTERY_MIN_CAPACITY_FRACTION,
            battery['current_capacity'] - loss
        )
        battery['stored_energy'] = min(battery['stored_energy'], battery['current_capacity'])

    def calculate_demand(self, player_state, game_state):
        fluctuation = random.uniform(-DEMAND_MONTHLY_VARIATION, DEMAND_MONTHLY_VARIATION)
        self.total_demand = (player_state.base_territory_mw
                             * (1 + fluctuation)
                             * game_state.demand_multiplier
                             * game_state.demand_index)
        return self.total_demand

    def forecast_demand(self, player_state, game_state, months=DEMAND_FORECAST_MONTHS):
        """Read-only forecast; no future random events are sampled or revealed."""
        forecast = []
        demand_index = game_state.demand_index
        current_firm = self.firm_capacity(player_state)
        contract = (player_state.pending_wholesale_commitment_mw
                    if player_state.pending_wholesale_commitment_mw is not None
                    else player_state.wholesale_commitment_mw)
        for step in range(1, months + 1):
            demand_index *= 1 + MONTHLY_DEMAND_GROWTH
            for event in game_state.active_demand_events:
                if event['months_left'] >= step:
                    demand_index *= 1 + event['monthly_pressure']
            year_offset, month_index = divmod(game_state.current_month - 1 + step, 12)
            month = month_index + 1
            year = game_state.year + year_offset
            expected = (player_state.base_territory_mw * demand_index
                        * game_state.seasonal_demand_multiplier(month))
            low = expected * (1 - DEMAND_MONTHLY_VARIATION)
            high = expected * (1 + DEMAND_MONTHLY_VARIATION)
            completed_capacity = sum(
                PLANT_NAMEPLATE_CAPACITY[project['type']] * CAPACITY_CREDIT[project['type']]
                for project in player_state.ongoing_constructions
                if project['turns_remaining'] <= step
            )
            firm_supply = current_firm + completed_capacity + contract
            forecast.append({
                'month': month, 'year': year,
                'label': f'{MONTH_NAMES[month - 1][:3].title()} {year}',
                'expected': expected, 'low': low, 'high': high,
                'firm_supply': firm_supply,
                'reserve_margin': (firm_supply - high) / max(high, 1),
            })
        return forecast

    def nameplate_capacity(self, player_state):
        """Total installed capacity ignoring intermittency (MW)."""
        return (
            player_state.power_plants['coal'] * COAL_PLANT_CAPACITY
            + player_state.power_plants['natural_gas'] * NATURAL_GAS_PLANT_CAPACITY
            + player_state.power_plants['nuclear'] * NUCLEAR_PLANT_CAPACITY
            + player_state.power_plants['solar'] * SOLAR_PLANT_CAPACITY
            + player_state.power_plants['wind'] * WIND_PLANT_CAPACITY
            + player_state.power_plants['hydro'] * HYDRO_PLANT_CAPACITY
        )

    def firm_capacity(self, player_state):
        """Dependable capacity at peak, de-rating intermittent renewables."""
        firm = 0
        firm += player_state.power_plants['coal'] * COAL_PLANT_CAPACITY * CAPACITY_CREDIT['coal']
        firm += player_state.power_plants['natural_gas'] * NATURAL_GAS_PLANT_CAPACITY * CAPACITY_CREDIT['natural_gas']
        firm += player_state.power_plants['nuclear'] * NUCLEAR_PLANT_CAPACITY * CAPACITY_CREDIT['nuclear']
        firm += player_state.power_plants['solar'] * SOLAR_PLANT_CAPACITY * CAPACITY_CREDIT['solar']
        firm += player_state.power_plants['wind'] * WIND_PLANT_CAPACITY * CAPACITY_CREDIT['wind']
        firm += player_state.power_plants['hydro'] * HYDRO_PLANT_CAPACITY * CAPACITY_CREDIT['hydro']
        for battery in player_state.batteries:
            health = battery['current_capacity'] / max(battery['max_capacity'], 1)
            firm += (battery.get('max_power', BATTERY_POWER_CAPACITY)
                     * CAPACITY_CREDIT['battery'] * health)
        return firm

    def reserve_margin(self, player_state):
        """(firm capacity - peak demand) / peak demand. Uses current demand as peak proxy."""
        peak = max(self.total_demand, 1)
        contracted_supply = player_state.wholesale_commitment_mw
        return (self.firm_capacity(player_state) + contracted_supply - peak) / peak

    def update_grid_status(self, player_state, game_state):
        self.calculate_demand(player_state, game_state)

        self.gas_generation = 0
        self.battery_discharged = 0
        self.battery_charged = 0

        baseload = self._baseload(player_state, game_state)
        gas_available = player_state.power_plants['natural_gas'] * NATURAL_GAS_PLANT_CAPACITY
        self.maximum_generation = baseload + gas_available
        self.contract_imports_mw = max(0.0, player_state.wholesale_commitment_mw)
        self.contract_exports_mw = max(0.0, -player_state.wholesale_commitment_mw)
        # Export commitments consume output; imports meet load before peakers.
        supply = baseload + self.contract_imports_mw - self.contract_exports_mw
        deficit = max(0.0, self.total_demand - supply)

        if player_state.battery_dispatch_mode == "before_gas":
            # Batteries fill the gap first, then gas covers what's left.
            self.battery_discharged = self._discharge(player_state, deficit)
            supply += self.battery_discharged
            deficit = max(0.0, self.total_demand - supply)
            self.gas_generation = min(gas_available, deficit)
            supply += self.gas_generation
        else:  # "after_gas"
            # Gas runs first, then batteries cover any remaining gap.
            self.gas_generation = min(gas_available, deficit)
            supply += self.gas_generation
            deficit = max(0.0, self.total_demand - supply)
            self.battery_discharged = self._discharge(player_state, deficit)
            supply += self.battery_discharged

        # Any leftover surplus charges the batteries.
        surplus = supply - self.total_demand
        if surplus > 0:
            self.battery_charged = self._charge(player_state, surplus)

        self.total_generation = baseload + self.gas_generation
        self.available_for_customers = (
            self.total_generation + self.battery_discharged
            - self.battery_charged + self.contract_imports_mw - self.contract_exports_mw
        )
        self.current_surplus_deficit = self.available_for_customers - self.total_demand
        # Balance any remaining gap in the spot market, at less favorable prices.
        self.spot_imports_mw = max(0.0, -self.current_surplus_deficit)
        self.spot_exports_mw = max(0.0, self.current_surplus_deficit)

    def display_grid_status(self, player_state=None):
        print("\n--- Power Grid Status ---")
        print(f"Total Generation: {self.total_generation:.2f} MW")
        print(f"Maximum generation (including gas): {self.maximum_generation:,.0f} MW")
        print(f"Contract imports: {self.contract_imports_mw:,.0f} MW | "
              f"Contract exports: {self.contract_exports_mw:,.0f} MW")
        print(f"Available for customers before spot balancing: {self.available_for_customers:,.0f} MW")
        print(f"  (Natural gas peakers dispatched: {self.gas_generation:.2f} MW)")
        if self.battery_discharged > 0:
            print(f"  (Batteries discharged: {self.battery_discharged:.2f} MW)")
        if self.battery_charged > 0:
            print(f"  (Batteries charged: {self.battery_charged:.2f} MW)")
        print(f"Total Demand: {self.total_demand:.2f} MW")
        if self.current_surplus_deficit >= 0:
            print(f"Surplus: {self.current_surplus_deficit:.2f} MW")
        else:
            print(f"Deficit: {abs(self.current_surplus_deficit):.2f} MW")

        if player_state is not None:
            nameplate = self.nameplate_capacity(player_state)
            firm = self.firm_capacity(player_state)
            margin = self.reserve_margin(player_state)
            print(f"\n  Nameplate Capacity: {nameplate:,.0f} MW")
            print(f"  Firm Capacity:      {firm:,.0f} MW (renewables de-rated)")
            if margin < 0:
                status = "SHORTFALL — you cannot meet peak demand!"
            elif margin < TARGET_RESERVE_MARGIN:
                status = f"THIN — below the {TARGET_RESERVE_MARGIN*100:.0f}% target"
            else:
                status = "adequate"
            print(f"  Reserve Margin:     {margin*100:+.1f}%  ({status})")


class Financials:
    def __init__(self):
        self.has_closed_month = False
        self.operational_costs = 0
        self.variable_operating_costs = 0
        self.carbon_costs = 0
        self.coal_generation_mwh = 0
        self.gas_generation_mwh = 0
        self.coal_emissions_tons = 0
        self.gas_emissions_tons = 0
        self.total_emissions_tons = 0
        self.coal_carbon_cost = 0
        self.gas_carbon_cost = 0
        self.revenue = 0
        self.net_profit = 0
        self.trailing_earnings = []  # last 12 months of net_profit
        self.trailing_ebitda = []  # operating earnings used for credit coverage
        self.trailing_share_counts = []
        self.monthly_weighted_shares = 0.0
        self.monthly_history = []
        self.actual_earnings_months = 0
        self.operating_cost_breakdown = []  # latest monthly snapshot, including imports

        # Latest monthly income statement.
        self.monthly_electric_revenue = 0
        self.other_wholesale_income = 0
        self.contract_sales_revenue = 0
        self.spot_sales_revenue = 0
        self.contract_purchase_cost = 0
        self.spot_purchase_cost = 0
        self.purchased_power_costs = 0
        self.total_operating_revenue = 0
        self.monthly_variable_operating_costs = 0
        self.monthly_carbon_tax_expense = 0
        self.cash_operating_expenses = 0
        self.ebitda = 0
        self.depreciation_expense = 0
        self.operating_income = 0
        self.interest_expense = 0
        self.unusual_gain_loss = 0
        self.pretax_income = 0
        self.income_tax_expense = 0

        # Latest monthly cash-flow statement.
        self.beginning_cash = 0
        self.net_cash_from_operations = 0
        self.capital_expenditures = 0
        self.asset_sale_proceeds = 0
        self.net_cash_from_investing = 0
        self.debt_issuance = 0
        self.debt_repayments = 0
        self.dividend_payments = 0
        self.stock_issuance = 0.0
        self.stock_buybacks = 0.0
        self.net_cash_from_financing = 0
        self.cash_reconciliation_adjustment = 0
        self.net_change_in_cash = 0
        self.ending_cash = 0

    @property
    def ttm_net_income(self):
        return sum(self.trailing_earnings)

    @property
    def ttm_ebitda(self):
        return sum(self.trailing_ebitda)

    def ttm_eps(self, shares_outstanding):
        shares = (sum(self.trailing_share_counts) / len(self.trailing_share_counts)
                  if self.trailing_share_counts else shares_outstanding)
        return self.ttm_net_income / max(shares, 1)

    def ttm_coverage_description(self):
        actual = self.actual_earnings_months
        if actual >= 12:
            return '12 completed months'
        return f'{actual} actual / {12 - actual} pre-game estimated months'

    def record_monthly_earnings(self, net_income, weighted_shares=None):
        self.trailing_earnings.append(net_income)
        self.trailing_earnings = self.trailing_earnings[-12:]
        self.actual_earnings_months = min(12, self.actual_earnings_months + 1)
        shares = weighted_shares or self.monthly_weighted_shares
        self.trailing_share_counts = (self.trailing_share_counts + [shares])[-12:]

    def calculate_operational_costs(self, player_state, game_state, power_grid, economy):
        infl = economy.price_index
        plants = player_state.power_plants
        generation_mw = {
            'coal': plants['coal'] * COAL_PLANT_CAPACITY,
            'natural_gas': power_grid.gas_generation,
            'nuclear': plants['nuclear'] * NUCLEAR_PLANT_CAPACITY,
            'solar': plants['solar'] * SOLAR_PLANT_CAPACITY * game_state.region_sunlight_level,
            'wind': plants['wind'] * WIND_PLANT_CAPACITY * game_state.region_wind_level,
            'hydro': plants['hydro'] * HYDRO_PLANT_CAPACITY * HYDRO_OUTPUT_FACTOR,
            'battery': power_grid.battery_discharged,
        }
        unit_costs = {
            'coal': COAL_COST_PER_MWH * infl,
            'natural_gas': game_state.natural_gas_price,
            'nuclear': NUCLEAR_COST_PER_MWH * infl,
            'solar': SOLAR_COST_PER_MWH * infl,
            'wind': WIND_COST_PER_MWH * infl,
            'hydro': HYDRO_COST_PER_MWH * infl,
            # Storage charging energy is already costed at its generating source
            # or as purchased power; no separate cash battery O&M is modeled.
            'battery': 0.0,
        }
        self.coal_generation_mwh = generation_mw['coal'] * HOURS_PER_YEAR
        self.gas_generation_mwh = generation_mw['natural_gas'] * HOURS_PER_YEAR
        self.coal_emissions_tons = (
            self.coal_generation_mwh * COAL_EMISSIONS_TONS_PER_MWH
        )
        self.gas_emissions_tons = (
            self.gas_generation_mwh * GAS_EMISSIONS_TONS_PER_MWH
        )
        self.total_emissions_tons = (
            self.coal_emissions_tons + self.gas_emissions_tons
        )
        self.coal_carbon_cost = self.coal_emissions_tons * game_state.carbon_tax
        self.gas_carbon_cost = self.gas_emissions_tons * game_state.carbon_tax
        self.carbon_costs = self.coal_carbon_cost + self.gas_carbon_cost
        carbon_by_type = {'coal': self.coal_carbon_cost / 12,
                          'natural_gas': self.gas_carbon_cost / 12}
        self.operating_cost_breakdown = []
        for plant_type, output in generation_mw.items():
            fuel_om = output * HOURS_PER_MONTH * unit_costs[plant_type]
            carbon = carbon_by_type.get(plant_type, 0.0)
            self.operating_cost_breakdown.append({
                'source': plant_type,
                'units': len(player_state.batteries) if plant_type == 'battery' else plants[plant_type],
                'energy_mwh': output * HOURS_PER_MONTH,
                'fuel_om_power': fuel_om, 'carbon': carbon,
                'cash_cost': fuel_om + carbon, 'depreciation': 0.0,
            })
        self.variable_operating_costs = sum(
            row['fuel_om_power'] for row in self.operating_cost_breakdown
        ) * 12
        for source, mw, cost in (
            ('contract_imports', power_grid.contract_imports_mw, self.contract_purchase_cost),
            ('spot_imports', power_grid.spot_imports_mw, self.spot_purchase_cost),
        ):
            self.operating_cost_breakdown.append({
                'source': source, 'units': None, 'energy_mwh': mw * HOURS_PER_MONTH,
                'fuel_om_power': cost, 'carbon': 0.0, 'cash_cost': cost, 'depreciation': 0.0,
            })
        costs = self.variable_operating_costs + self.carbon_costs + self.purchased_power_costs
        self.last_interest_rate = economy.interest_rate
        self.operational_costs = costs
        return costs

    def calculate_revenue(self, power_grid, regulator, economy):
        """Monthly MWh settlement, with imports reported as costs, not negative revenue."""
        price = wholesale_market_price(economy)
        self.monthly_electric_revenue = (
            power_grid.total_demand * regulator.current_retail_price * HOURS_PER_MONTH
        )
        self.contract_sales_revenue = (
            power_grid.contract_exports_mw * HOURS_PER_MONTH * price * CONTRACT_SELL_FACTOR
        )
        self.spot_sales_revenue = (
            power_grid.spot_exports_mw * HOURS_PER_MONTH * price * SPOT_SELL_FACTOR
        )
        self.contract_purchase_cost = (
            power_grid.contract_imports_mw * HOURS_PER_MONTH * price * CONTRACT_BUY_FACTOR
        )
        self.spot_purchase_cost = (
            power_grid.spot_imports_mw * HOURS_PER_MONTH * price * SPOT_BUY_FACTOR
        )
        self.other_wholesale_income = self.contract_sales_revenue + self.spot_sales_revenue
        self.total_operating_revenue = self.monthly_electric_revenue + self.other_wholesale_income
        self.purchased_power_costs = (self.contract_purchase_cost + self.spot_purchase_cost) * 12
        self.revenue = self.total_operating_revenue * 12
        return self.revenue

    def update_player_financials(self, player_state, game_state, power_grid,
                                 economy, regulator, valuation_only=False):
        # Management transactions occur at the month boundary, so the post-trade
        # share count is the full month's weighted-average shares.
        self.monthly_weighted_shares = player_state.shares_outstanding
        self.calculate_revenue(power_grid, regulator, economy)
        self.calculate_operational_costs(player_state, game_state, power_grid, economy)
        self.monthly_variable_operating_costs = self.variable_operating_costs / 12
        self.monthly_carbon_tax_expense = self.carbon_costs / 12
        self.cash_operating_expenses = (
            self.monthly_variable_operating_costs + self.monthly_carbon_tax_expense
            + self.contract_purchase_cost + self.spot_purchase_cost
        )
        self.ebitda = self.total_operating_revenue - self.cash_operating_expenses
        depreciation_by_type = dict.fromkeys(ASSET_USEFUL_LIFE_YEARS, 0.0)
        for asset in player_state.plant_assets:
            depreciation_by_type[asset.plant_type] += asset.monthly_depreciation
        self.depreciation_expense = player_state.monthly_depreciation(
            post=not valuation_only
        )
        for row in self.operating_cost_breakdown:
            row['depreciation'] = depreciation_by_type.get(row['source'], 0.0)
        self.operating_income = self.ebitda - self.depreciation_expense
        self.interest_expense = (
            sum(bond.monthly_interest() for bond in player_state.bonds)
            if valuation_only else player_state.process_bonds()
        )
        self.unusual_gain_loss = (
            0.0 if valuation_only else
            player_state.disposal_gain_loss_since_close
            + player_state.debt_gain_loss_since_close
        )
        self.pretax_income = (
            self.operating_income - self.interest_expense + self.unusual_gain_loss
        )
        self.income_tax_expense = max(0.0, self.pretax_income * CORPORATE_TAX_RATE)
        self.net_profit = self.pretax_income - self.income_tax_expense

        if valuation_only:
            # An established opening utility has estimated pre-game earnings.
            # Real closes replace these one by one; previews never erase history.
            if not self.trailing_earnings:
                self.trailing_earnings = [self.net_profit] * 12
            if not self.trailing_ebitda:
                self.trailing_ebitda = [self.ebitda] * 12
            if not self.trailing_share_counts:
                self.trailing_share_counts = [self.monthly_weighted_shares] * 12
            player_state.update_stock_price(economy, self.ttm_net_income,
                                             self.ttm_eps(player_state.shares_outstanding))
            player_state.equity = player_state.company_value
            self.beginning_cash = player_state.cash
            self.ending_cash = player_state.cash
            return

        # Power contracts settle once with recurring operations at month close.
        # Construction, retirements and financing were posted when chosen;
        # bond processing already paid interest and any maturing principal.
        self.beginning_cash = self.ending_cash
        player_state.cash += self.ebitda - self.income_tax_expense

        self.record_monthly_earnings(self.net_profit, self.monthly_weighted_shares)
        self.trailing_ebitda = (self.trailing_ebitda + [self.ebitda])[-12:]
        player_state.update_stock_price(economy, self.ttm_net_income,
                                         self.ttm_eps(player_state.shares_outstanding))
        player_state.pay_quarterly_dividend(game_state)
        player_state.review_dividend_policy(game_state)
        player_state.equity = player_state.company_value

        # Indirect-method cash-flow statement. Gains and losses are removed from
        # operating cash because their settlement belongs in investing/financing.
        self.net_cash_from_operations = (
            self.net_profit + self.depreciation_expense - self.unusual_gain_loss
        )
        self.capital_expenditures = player_state.capital_expenditures_since_close
        self.asset_sale_proceeds = player_state.asset_sale_proceeds_since_close
        self.net_cash_from_investing = (
            -self.capital_expenditures + self.asset_sale_proceeds
        )
        self.debt_issuance = player_state.debt_issued_since_close
        self.debt_repayments = player_state.debt_repaid_since_close
        self.dividend_payments = player_state.dividends_since_close
        self.stock_issuance = player_state.stock_issued_since_close
        self.stock_buybacks = player_state.stock_bought_since_close
        self.net_cash_from_financing = (
            self.debt_issuance - self.debt_repayments - self.dividend_payments
            + self.stock_issuance - self.stock_buybacks
        )
        calculated_change = (
            self.net_cash_from_operations + self.net_cash_from_investing
            + self.net_cash_from_financing
        )
        self.ending_cash = player_state.cash
        actual_change = self.ending_cash - self.beginning_cash
        self.cash_reconciliation_adjustment = actual_change - calculated_change
        self.net_change_in_cash = actual_change
        self.has_closed_month = True
        utility_reports.store_close(self, player_state, game_state)
        player_state.reset_monthly_ledgers()


    def display_financial_summary(self):
        print("\n--- Financial Summary (This Month) ---")
        print(f"Revenue (monthly):        ${self.total_operating_revenue:,.2f}")
        print(f"  Contract power sales:   ${self.contract_sales_revenue:,.2f}")
        print(f"  Contract power buys:    ${self.contract_purchase_cost:,.2f}")
        print(f"  Spot balancing buys:    ${self.spot_purchase_cost:,.2f}")
        print(f"Cash operating costs:     ${self.cash_operating_expenses:,.2f}")
        for row in self.operating_cost_breakdown:
            print(f"  {row['source'].replace('_', ' ').title()}: "
                  f"cash ${row['cash_cost']:,.0f}, depreciation ${row['depreciation']:,.0f}")
        print(f"EBITDA:                   ${self.ebitda:,.2f}")
        print(f"Depreciation:             ${self.depreciation_expense:,.2f}")
        print(f"Bond interest:            ${self.interest_expense:,.2f}")
        print(f"Income tax:               ${self.income_tax_expense:,.2f}")
        print(f"Net Profit/Loss (monthly): ${self.net_profit:,.2f}")
        print(f"  (Annualized revenue: ${self.revenue:,.0f} | "
              f"costs: ${self.operational_costs:,.0f})")


def check_bankruptcy(player_state, credit):
    """Game over if the player can't cover cash and can't raise any more."""
    if player_state.cash >= 0:
        return False

    # Ordinary or emergency financing must fit inside this month's allowance.
    if player_state.remaining_borrowing_capacity() >= -player_state.cash:
        return False

    # No lenders. Do they have anything left to liquidate?
    has_plants = any(c > 0 for c in player_state.power_plants.values())
    has_batteries = len(player_state.batteries) > 0
    if has_plants or has_batteries:
        return False  # could still sell assets to survive

    # Broke, no credit, nothing to sell -> bankrupt.
    return True



def player_action_menu(player_state, economy, regulator, financials, credit, current_turn,
                       game_state=None):
    build_options = {
        '1': 'coal', '2': 'natural_gas', '3': 'nuclear', '4': 'solar',
        '5': 'wind', '6': 'battery', '13': 'hydro',
    }
    decom_options = {
        'a': 'coal', 'b': 'natural_gas', 'c': 'nuclear', 'd': 'solar',
        'e': 'wind', 'g': 'hydro',
    }

    def quantity_prompt():
        raw = input("Quantity [1]: ").strip()
        try:
            return int(raw) if raw else 1
        except ValueError:
            print("Quantity must be a whole number.")
            return None

    while True:
        print("\n=== PLAYER ACTIONS ===")
        print(f"Cash: ${player_state.cash:,.2f} | Stock: ${player_state.stock_price:,.2f} "
              f"| Debt: ${player_state.total_debt():,.0f} | Rating: {credit.rating}")
        print(f"Net debt (bonds - cash): ${player_state.net_debt():,.0f} | "
              f"Borrowing left this month: ${player_state.remaining_borrowing_capacity():,.0f} "
              f"of ${player_state.monthly_borrowing_limit:,.0f}")
        print(f"Power contract: {power_contract_description(player_state.wholesale_commitment_mw)}")
        if player_state.pending_wholesale_commitment_mw is not None:
            print('Next month: ' + power_contract_description(player_state.pending_wholesale_commitment_mw))
        print(player_state.shareholder_status())
        if player_state.cash < 0:
            print("  *** WARNING: CASH IS NEGATIVE. You must raise cash before ending the turn. ***")
        print("  Build:  1 Coal  2 Gas  3 Nuclear  4 Solar  5 Wind  6 Battery  13 Hydro")
        print("  Decommission:  a Coal  b Gas  c Nuclear  d Solar  e Wind  f Battery  g Hydro")
        print("  7 Issue bond  8 Rate increase  9 Wholesale trade  10 Set dividend")
        print(" 11 Toggle battery dispatch  0 End turn")
        print(" 12 Emergency loan (high interest, last resort)")
        print(" 14 Demand forecast (next 24 months)")
        print(" 15 Issue stock  16 Buy back stock")
        if player_state.fired:
            return 'FIRED'

        choice = input("Action: ").strip().lower()
        if choice == '0':
            if player_state.cash < 0:
                if check_bankruptcy(player_state, credit):
                    print("\n!!! BANKRUPTCY: negative cash, credit rating 'D' "
                          "(no lenders), and no assets left to sell. !!!")
                    return "BANKRUPT"
                print("Cannot end turn: cash is negative. Raise funds first.")
                continue
            break
        elif choice in build_options:
            quantity = quantity_prompt()
            if quantity is not None:
                player_state.start_construction(build_options[choice], quantity)
        elif choice in decom_options:
            quantity = quantity_prompt()
            if quantity is not None:
                player_state.decommission_plant(decom_options[choice], quantity)
        elif choice == 'f':
            quantity = quantity_prompt()
            if quantity is not None:
                player_state.decommission_battery(quantity)
        elif choice == '7':
            print("Terms:", ", ".join(BOND_TERMS.keys()))
            term = input("Term: ").strip()
            if term not in BOND_TERMS:
                print("Invalid term.")
                continue
            try:
                amt_millions = float(input("Principal ($ millions): "))
            except ValueError:
                print("Please enter a number (in millions).")
                continue
            player_state.issue_bond(amt_millions * 1_000_000, economy, term, credit)
        elif choice == '8':
            pct = float(input("Increase above automatic inflation adjustment (e.g. 0.05): "))
            regulator.request_increase(player_state, financials, economy, current_turn, pct)
        elif choice == '9':
            d = input("buy or sell? ").strip().lower()
            mw = float(input("Recurring MW from next month (0 cancels): "))
            if d in ('buy','sell'):
                player_state.wholesale_trade(mw, d, economy)
        elif choice == '10':
            div = float(input("New annual dividend per share $: "))
            player_state.set_dividend(div)
        elif choice == '11':
            player_state.battery_dispatch_mode = (
                "before_gas" if player_state.battery_dispatch_mode == "after_gas" else "after_gas")
            print(f"Dispatch mode: {player_state.battery_dispatch_mode}")
        elif choice == '12':
            amt = float(input("Emergency loan amount $ (millions): "))
            player_state.emergency_loan(amt * 1_000_000)
        elif choice == '14' and game_state is not None:
            print('Demand forecast: seasonal growth and known events; no new shocks assumed.')
            for row in PowerGrid().forecast_demand(player_state, game_state):
                print(f"{row['label']:8}  Expected {row['expected']:,.0f} MW  "
                      f"Range {row['low']:,.0f}–{row['high']:,.0f} MW  "
                      f"Dependable supply {row['firm_supply']:,.0f} MW")
        elif choice in ('15', '16') and game_state is not None:
            try:
                quantity = int(input(f'Shares (remaining annual allowance '
                                     f'{player_state.remaining_share_allowance():,}): '))
                player_state.trade_shares('issue' if choice == '15' else 'buyback',
                                         quantity, game_state)
            except ValueError:
                print('Enter a whole number of shares.')
        else:
            print("Invalid.")
            

def play_turn(game_state, player_state, power_grid, financials, economy, regulator, credit):
    print(f"\n--- {MONTH_NAMES[game_state.current_month-1]}, YEAR {game_state.year} ---")
    result = player_action_menu(player_state, economy, regulator, financials, credit,
                                game_state.turn, game_state)
    if result in ('BANKRUPT', 'FIRED'):
        return result

    economy.update()
    game_state.advance_turn()
    player_state.reset_annual_share_allowance(game_state.year)
    player_state.activate_power_contract()
    game_state.display_env_status()
    economy.display()
    player_state.update_constructions()
    power_grid.update_grid_status(player_state, game_state)
    power_grid.display_grid_status(player_state)
    financials.update_player_financials(player_state, game_state, power_grid, economy, regulator)
    financials.display_financial_summary()
    print(f"TTM EPS: ${financials.ttm_eps(player_state.shares_outstanding):.3f} "
          f"({financials.ttm_coverage_description()})")
    credit.update(player_state, financials)      # refresh rating from the turn's results
    player_state.display_player_status()
    player_state.display_equity()
    credit.display()

    if player_state.fired:
        return "FIRED"

    # Post-turn safety net: if a maturing bond or dividend drove cash negative
    # and there's no way out, end the game.
    if check_bankruptcy(player_state, credit):
        print("\n!!! BANKRUPTCY: obligations came due with no cash, no credit, "
              "and no assets to liquidate. !!!")
        return "BANKRUPT"
    return "OK"


def run_game(num_turns):
    session = UtilityGameSession(max_turns=num_turns)
    game_state, player_state, power_grid = session.game_state, session.player, session.grid
    financials, economy, regulator, credit = session.financials, session.economy, session.regulator, session.credit

    print("\n--- Game Start ---")
    for _ in range(num_turns):
        result = play_turn(game_state, player_state, power_grid, financials,
                           economy, regulator, credit)
        if result == "FIRED":
            print("\n=== GAME OVER: Shareholders have fired you after losing confidence. ===")
            return
        if result == "BANKRUPT":
            print("\n=== GAME OVER: Your utility has gone bankrupt. ===")
            print(f"Survived until {MONTH_NAMES[game_state.current_month-1]}, "
                  f"YEAR {game_state.year}.")
            return
    print("\n--- Game Over (reached turn limit) ---")
    player_state.display_player_status()
    player_state.display_equity()
    credit.display()


# --- Graphical game -------------------------------------------------------

GUI_BUILD_INFO = {
    'coal': ("Coal", COAL_CONSTRUCTION_COST, COAL_CONSTRUCTION_TIME),
    'natural_gas': ("Gas", NATURAL_GAS_CONSTRUCTION_COST, NATURAL_GAS_CONSTRUCTION_TIME),
    'nuclear': ("Nuclear", NUCLEAR_CONSTRUCTION_COST, NUCLEAR_CONSTRUCTION_TIME),
    'solar': ("Solar", SOLAR_CONSTRUCTION_COST, SOLAR_CONSTRUCTION_TIME),
    'wind': ("Wind", WIND_CONSTRUCTION_COST, WIND_CONSTRUCTION_TIME),
    'hydro': ("Hydro", HYDRO_BASE_CONSTRUCTION_COST, HYDRO_CONSTRUCTION_TIME),
    'battery': ("Battery", BATTERY_CONSTRUCTION_COST, BATTERY_CONSTRUCTION_TIME),
}


def compact_money(value):
    """Format large dollar values so dashboard cards stay readable."""
    sign = "-" if value < 0 else ""
    value = abs(value)
    if value >= 1_000_000_000:
        return f"{sign}${value / 1_000_000_000:.2f}B"
    if value >= 1_000_000:
        return f"{sign}${value / 1_000_000:.1f}M"
    if value >= 1_000:
        return f"{sign}${value / 1_000:.1f}K"
    return f"{sign}${value:,.0f}"


STATEMENT_DEFINITIONS = {
    'Electric revenue': (
        "Revenue from retail customers. Power bought to meet their demand is reported "
        "separately as purchased-power expense. Retail tariffs automatically follow "
        "cumulative inflation; approved rate cases add increases above inflation."
    ),
    'Contract power sales': 'Recurring export MW × 730 monthly hours × the monthly contract sale price.',
    'Spot power sales': 'Revenue from surplus remaining after customer demand and export commitments.',
    'Contract power purchases': 'Recurring import MW × 730 monthly hours × the monthly purchase price.',
    'Spot power purchases': 'Power bought at a premium to cover remaining customer or export shortfalls.',
    'Total operating revenue': "Retail revenue plus contract and spot wholesale sales.",
    'Fuel and variable O&M': (
        "Fuel and variable operating and maintenance costs that rise "
        "with plant output and cumulative inflation. Natural gas also follows its commodity market."
    ),
    'Carbon tax expense': (
        "Tax on metric tons of CO₂ emitted by coal and natural-gas generation. The price per ton "
        "follows inflation plus its separate carbon-policy escalator."
    ),
    'Cash operating expenses': (
        "Operating costs paid in cash, before depreciation, interest, and income tax."
    ),
    'EBITDA': (
        "Earnings before interest, taxes, depreciation, and amortization. It measures "
        "cash-like operating performance before financing and non-cash asset wear."
    ),
    'Depreciation and amortization': (
        "The monthly non-cash allocation of historical plant purchase cost over each asset's "
        "useful life. Existing cost bases and depreciation are not marked up for later inflation."
    ),
    'Operating income (EBIT)': (
        "Earnings before interest and income taxes: EBITDA less depreciation and amortization."
    ),
    'Retirement / debt gain (loss)': (
        "Gain or loss when an asset is retired for proceeds different from its remaining "
        "book value, or debt is repurchased above or below principal."
    ),
    'Interest expense': "Monthly coupon interest owed on outstanding bonds.",
    'Income before tax': "Operating income plus unusual gains or losses, less interest expense.",
    'Income tax expense': (
        "Estimated corporate income tax at 21% of positive pretax income; losses create no "
        "current tax benefit in this simulation."
    ),
    'Net income after interest': (
        "Profit available to shareholders after operating costs, depreciation, bond "
        "interest, unusual items, and income tax."
    ),
    'Weighted average shares': (
        "Shares outstanding during the reporting period, weighted by time. Issues dilute "
        "ownership and buybacks reduce the count. Management trades occur at monthly boundaries."
    ),
    'Basic earnings per share': "Monthly net income divided by shares outstanding.",
    'TTM net income': (
        'Net income after tax summed over the rolling twelve-month earnings window. '
        'At game start, pre-game months use opening estimates; one actual close replaces '
        'one estimate each month.'
    ),
    'Trailing twelve-month EPS': (
        'TTM means trailing twelve months. TTM net income divided by weighted-average shares. '
        'This exact figure feeds the stock valuation: 70% earnings, 20% book value, '
        'and 10% dividend value, followed by market adjustments.'
    ),
    'TTM earnings coverage': 'Shows how much of the twelve-month window is actual gameplay versus pre-game estimates.',
    'Utility P/E multiple': 'The utility earnings multiplier follows the market P/E at 85%, with a minimum of 6×.',
    'Actual price / earnings': 'Current share price divided by trailing-twelve-month EPS. '
                              'N/M means earnings are zero or negative.',
    'Treasury stock': 'Cost of stock repurchases, shown as a reduction of shareholders’ equity.',
    'Stock issued': 'Cash raised by issuing new common shares, net of the 1% execution spread.',
    'Stock repurchased': 'Cash spent on common-share buybacks, including the 1% execution spread.',
    'EPS-based price benchmark': (
        'TTM EPS multiplied by the current utility P/E. Earnings receive 70% of the '
        'ongoing valuation weight; book value, dividends, rates, confidence and market noise '
        'also influence the stock. A negative earnings benchmark represents losses.'
    ),
    'Cash and cash equivalents': "Cash available to operate the utility and pay obligations.",
    'Gross utility plant': "Original purchase or construction cost of completed assets in service.",
    'Accumulated depreciation': (
        "Total plant cost recognized as expense since acquisition; shown as a reduction of assets."
    ),
    'Net utility plant': "Gross utility plant less accumulated depreciation.",
    'Construction work in progress': (
        "Capital already spent on projects that are not yet operating or depreciating."
    ),
    'Total assets': "Cash, net completed utility plant, and construction work in progress.",
    'Current portion of debt': "Bond principal due within the next 12 months.",
    'Long-term debt': "Bond principal due more than 12 months from now.",
    'Total debt': "All outstanding bond principal, both current and long term.",
    'Paid-in capital': "Opening shareholder book capital plus net proceeds from stock issuance.",
    'Retained earnings': (
        "Cumulative book profit kept in the business after dividends and other equity changes."
    ),
    'Total shareholders’ equity': "Accounting assets minus debt; this is book value, not market cap.",
    'Liabilities and equity': "Debt plus shareholders' book equity; it must equal total assets.",
    'Net income': "Profit from the latest closed month, used as the starting point for cash flow.",
    'Depreciation added back': "Adds back non-cash depreciation deducted on the income statement.",
    'Gains / losses removed': (
        "Removes asset-sale and debt-retirement gains or losses because their cash is classified "
        "under investing or financing."
    ),
    'Net cash from operations': "Cash generated by power operations after interest and income tax.",
    'Capital expenditures': "Cash spent to build new generation, storage, or work in progress.",
    'Asset retirement proceeds': (
        "Cash salvage proceeds less decommissioning costs, both priced in current dollars. "
        "Inflation since purchase is applied once; the removed book value remains historical."
    ),
    'Net cash from investing': "Asset-sale proceeds less capital expenditures.",
    'Debt issued': "Cash received from new bond principal.",
    'Debt repaid or repurchased': "Cash used for maturities and market-price bond buybacks.",
    'Dividends paid': "Cash returned to shareholders during the month.",
    'Net cash from financing': "Debt proceeds less debt repayments and shareholder dividends.",
    'Other / reconciliation': (
        "Unclassified or rounding cash movement needed to reconcile the simulated cash ledger."
    ),
    'Net change in cash': "Combined operating, investing, and financing movement for the month.",
    'Beginning cash': "Cash reported at the end of the previous month.",
    'Ending cash': "Cash on hand at the end of the latest closed month.",
}


class HoverTooltip:
    """Small delayed tooltip used for financial-statement definitions."""

    def __init__(self, widget, text, colors):
        self.widget = widget
        self.text = text
        self.colors = colors
        self.tip = None
        self.job = None
        widget.bind('<Enter>', self._schedule, add='+')
        widget.bind('<Leave>', self._hide, add='+')
        widget.bind('<ButtonPress>', self._hide, add='+')

    def _schedule(self, _event=None):
        self._cancel()
        self.job = self.widget.after(350, self._show)

    def _cancel(self):
        if self.job is not None:
            self.widget.after_cancel(self.job)
            self.job = None

    def _show(self):
        self.job = None
        if self.tip is not None or not self.text:
            return
        x = self.widget.winfo_rootx() + 18
        y = self.widget.winfo_rooty() + self.widget.winfo_height() + 5
        self.tip = tk.Toplevel(self.widget)
        self.tip.wm_overrideredirect(True)
        self.tip.wm_geometry(f"+{x}+{y}")
        tk.Label(
            self.tip, text=self.text, justify='left', wraplength=360,
            bg=self.colors['panel_alt'], fg=self.colors['text'], padx=10, pady=8,
            font=('Helvetica', 9), relief='solid', borderwidth=1,
        ).pack()

    def _hide(self, _event=None):
        self._cancel()
        if self.tip is not None:
            self.tip.destroy()
            self.tip = None


class UtilityGameSession:
    """A small controller shared by the graphical interface and its tests."""

    def __init__(self, max_turns=1000):
        self.max_turns = max_turns
        self.game_state = GameState()
        self.player = PlayerState()
        self.grid = PowerGrid()
        self.financials = Financials()
        self.economy = Economy()
        self.game_state.economy = self.economy
        self.player.economy = self.economy
        self.regulator = RateRegulator(self.economy)
        self.credit = CreditRating()
        self.game_over = False
        self.ui_state = {}

        # Populate the opening dashboard with a real demand and dispatch picture.
        self.grid.update_grid_status(self.player, self.game_state)
        self.financials.update_player_financials(
            self.player, self.game_state, self.grid, self.economy,
            self.regulator, valuation_only=True
        )
        utility_reports.seed_history(self)
        self.player.stock_price = 0.0
        self.player._dividend_initialized = False
        self.player.update_stock_price(self.economy, self.financials.ttm_net_income,
                                       self.financials.ttm_eps(self.player.shares_outstanding))
        self.player.equity = self.player.company_value
        self.last_monthly_profit = self.financials.net_profit
        self.credit.update(self.player, self.financials)

    @staticmethod
    def save_classes():
        return {cls.__name__: cls for cls in (UtilityGameSession, GameState, PlayerState,
                Economy, RateRegulator, CreditRating, Financials, PowerGrid, Bond, PlantAsset)}

    def save_game(self, path):
        utility_persistence.save_game(self, path, self.save_classes(), GAME_VERSION)

    @classmethod
    def load_game(cls, path):
        return utility_persistence.load_game(path, cls.save_classes(), cls.validate_loaded_game)

    @staticmethod
    def validate_loaded_game(session):
        if not isinstance(session, UtilityGameSession):
            raise utility_persistence.SaveError('The save does not contain a game session.')
        expected = dict(game_state=GameState, player=PlayerState, economy=Economy,
                        regulator=RateRegulator, credit=CreditRating, financials=Financials, grid=PowerGrid)
        for key, kind in expected.items():
            if not isinstance(getattr(session, key), kind):
                raise utility_persistence.SaveError(f'Missing or invalid {key}.')
        p, state, economy, f = session.player, session.game_state, session.economy, session.financials
        if (not 1 <= state.current_month <= 12 or state.year < 1 or state.turn < 1
                or not math.isfinite(economy.price_index) or economy.price_index <= 0
                or not isinstance(p.shares_outstanding, int) or p.shares_outstanding <= 0
                or not math.isfinite(p.cash) or not 0 <= p.shareholder_happiness <= 100
                or not isinstance(f.monthly_history, list) or not isinstance(session.ui_state, dict)):
            raise utility_persistence.SaveError('Invalid game balances or calendar.')
        if any(obj.economy is not economy for obj in (p, state, session.regulator)):
            raise utility_persistence.SaveError('The saved price-index references are inconsistent.')
        if any(not isinstance(b, Bond) for b in p.bonds) or any(
                not isinstance(asset, PlantAsset) for asset in p.plant_assets):
            raise utility_persistence.SaveError('Invalid bond or plant register.')
        # Essential gameplay fields must not silently default or vanish.
        for key in ('max_turns', 'game_over', 'last_monthly_profit'):
            getattr(session, key)
        for key in ('ongoing_constructions', 'batteries', 'share_trade_year', 'dividend_high_water',
                    'pending_wholesale_commitment_mw', 'monthly_borrowing_limit'):
            getattr(p, key)

    def advance_month(self):
        """Resolve one month after the player has finished making decisions."""
        if self.game_over:
            return "GAME_OVER"
        if self.player.fired:
            self.game_over = True
            return 'FIRED'

        state = self.game_state
        self.economy.update()
        state.advance_turn()
        self.player.reset_annual_share_allowance(state.year)
        self.player.activate_power_contract()
        self.player.update_constructions()
        self.grid.update_grid_status(self.player, state)
        self.financials.update_player_financials(
            self.player, state, self.grid, self.economy, self.regulator
        )
        self.last_monthly_profit = self.financials.net_profit
        self.credit.update(self.player, self.financials)

        if self.player.fired:
            self.game_over = True
            return "FIRED"
        if check_bankruptcy(self.player, self.credit):
            self.game_over = True
            print("BANKRUPTCY: obligations came due with no cash, no credit, "
                  "and no assets left to liquidate.")
            return "BANKRUPT"
        if state.turn > self.max_turns:
            self.game_over = True
            print("The board's planning horizon is complete.")
            return "COMPLETE"
        return "OK"


class UtilityGameGUI:
    """Tk-based control room for the utility management simulation."""

    COLORS = {
        'background': '#08111f',
        'panel': '#101d2f',
        'panel_alt': '#14243a',
        'line': '#263a54',
        'text': '#e8f0f8',
        'muted': '#8da2b8',
        'cyan': '#32d6e6',
        'blue': '#4387f5',
        'green': '#49d17d',
        'amber': '#f2b84b',
        'orange': '#f27a4b',
        'red': '#f25f64',
        'purple': '#a879f5',
    }

    def __init__(self, session, startup_log=""):
        self.session = session
        self.root = tk.Tk()
        self.root.title(f"Gridline {GAME_VERSION} — Utility Command Center")
        self.root.configure(bg=self.COLORS['background'])
        self.root.minsize(1040, 700)
        screen_w = self.root.winfo_screenwidth()
        screen_h = self.root.winfo_screenheight()
        width = min(1380, max(1040, screen_w - 80))
        height = min(920, max(700, screen_h - 100))
        self.root.geometry(f"{width}x{height}")

        self.cards = {}
        self.action_buttons = []
        self.history = list(session.ui_state.get('history', []))
        self.flow_phase = 0
        self._configure_styles()
        self._build_layout()
        if not self.history:
            self._record_history()
        self.refresh()
        if startup_log.strip():
            self._append_log(startup_log.strip())
        self._append_log(
            "Welcome to Gridline. Review the control room, make your decisions, "
            "then advance to the next month."
        )
        self.root.bind("<Return>", lambda _event: self.advance_month())
        self.root.bind("<F1>", lambda _event: self.show_help())
        self.root.bind('<Command-s>', lambda _event: self.save_game())
        self.root.bind('<Control-s>', lambda _event: self.save_game())
        self.root.bind('<Command-o>', lambda _event: self.load_game())
        self.root.after(140, self._animate_flow)

    def _configure_styles(self):
        style = ttk.Style(self.root)
        try:
            style.theme_use('clam')
        except tk.TclError:
            pass
        style.configure(
            'Utility.Treeview', background=self.COLORS['panel_alt'],
            fieldbackground=self.COLORS['panel_alt'], foreground=self.COLORS['text'],
            rowheight=26, borderwidth=0, font=('Helvetica', 10)
        )
        style.configure(
            'Utility.Treeview.Heading', background=self.COLORS['panel'],
            foreground=self.COLORS['muted'], relief='flat', font=('Helvetica', 9, 'bold')
        )
        style.map('Utility.Treeview', background=[('selected', self.COLORS['blue'])])
        style.configure('Utility.TNotebook', background=self.COLORS['background'], borderwidth=0)
        style.configure('Utility.TNotebook.Tab', background=self.COLORS['panel_alt'],
                        foreground=self.COLORS['text'], padding=(12, 7))
        style.map('Utility.TNotebook.Tab', background=[('selected', self.COLORS['blue'])])
        style.configure(
            'Utility.Horizontal.TProgressbar', troughcolor=self.COLORS['background'],
            background=self.COLORS['cyan'], bordercolor=self.COLORS['background'],
            lightcolor=self.COLORS['cyan'], darkcolor=self.COLORS['cyan']
        )

    def _panel(self, parent, **grid_options):
        panel = tk.Frame(
            parent, bg=self.COLORS['panel'], highlightthickness=1,
            highlightbackground=self.COLORS['line']
        )
        panel.grid(**grid_options)
        return panel

    def _build_layout(self):
        root = self.root
        root.grid_columnconfigure(0, weight=1)
        root.grid_rowconfigure(2, weight=1)

        header = tk.Frame(root, bg=self.COLORS['background'], padx=20, pady=12)
        header.grid(row=0, column=0, sticky='ew')
        header.grid_columnconfigure(1, weight=1)

        logo = tk.Canvas(header, width=46, height=46, bg=self.COLORS['background'],
                         highlightthickness=0)
        logo.grid(row=0, column=0, rowspan=2, padx=(0, 12))
        logo.create_oval(3, 3, 43, 43, fill=self.COLORS['cyan'], outline='')
        logo.create_polygon(25, 7, 13, 26, 23, 26, 18, 40, 35, 19, 25, 19,
                            fill=self.COLORS['background'])

        tk.Label(header, text="GRIDLINE", bg=self.COLORS['background'],
                 fg=self.COLORS['text'], font=('Helvetica', 20, 'bold')).grid(
                     row=0, column=1, sticky='sw')
        tk.Label(header, text="UTILITY COMMAND CENTER", bg=self.COLORS['background'],
                 fg=self.COLORS['muted'], font=('Helvetica', 9, 'bold')).grid(
                     row=1, column=1, sticky='nw')
        self.date_label = tk.Label(header, bg=self.COLORS['background'],
                                   fg=self.COLORS['text'], font=('Helvetica', 12, 'bold'))
        self.date_label.grid(row=0, column=2, padx=14)
        self.happiness_bar = tk.Canvas(header, width=210, height=27,
                                       bg=self.COLORS['background'], highlightthickness=0)
        self.happiness_bar.grid(row=1, column=2, padx=14)
        HoverTooltip(self.happiness_bar, 'Shareholder happiness: 3%+ dividends help; 2% or less hurts. '
                     'A dividend cut immediately costs 50 points. Consistent raises and buybacks help; '
                     'repeated share issuance hurts. Yield is measured against at least the '
                     'inflation-adjusted opening share price, so crashing the price is no escape. '
                     'At 10/100 or less you are fired.', self.COLORS)
        self.next_button = tk.Button(
            header, text="ADVANCE MONTH  →", command=self.advance_month,
            bg=self.COLORS['cyan'], fg='#031017', activebackground='#72e8f2',
            activeforeground='#031017', relief='flat', cursor='hand2',
            font=('Helvetica', 10, 'bold'), padx=18, pady=10
        )
        self.next_button.grid(row=0, column=3, rowspan=2, padx=(8, 0))
        self._clickable_label(header, 'SAVE', self.save_game, self.COLORS['panel_alt']).grid(
            row=0, column=4, padx=(8, 0))
        self._clickable_label(header, 'LOAD', self.load_game, self.COLORS['panel_alt']).grid(
            row=1, column=4, padx=(8, 0))

        stats = tk.Frame(root, bg=self.COLORS['background'], padx=16, pady=2)
        stats.grid(row=1, column=0, sticky='ew')
        for col in range(6):
            stats.grid_columnconfigure(col, weight=1, uniform='cards')
        card_specs = [
            ('cash', 'CASH', self.COLORS['green']),
            ('profit', 'MONTHLY PROFIT', self.COLORS['cyan']),
            ('stock', 'SHARE PRICE', self.COLORS['purple']),
            ('demand', 'GRID DEMAND', self.COLORS['orange']),
            ('reserve', 'RESERVE MARGIN', self.COLORS['blue']),
            ('rating', 'CREDIT RATING', self.COLORS['amber']),
        ]
        for column, (key, title, color) in enumerate(card_specs):
            frame = tk.Frame(stats, bg=self.COLORS['panel'], padx=13, pady=10,
                             highlightthickness=1, highlightbackground=self.COLORS['line'])
            frame.grid(row=0, column=column, sticky='ew', padx=4, pady=5)
            tk.Frame(frame, bg=color, width=4).pack(side='left', fill='y', padx=(0, 10))
            text = tk.Frame(frame, bg=self.COLORS['panel'])
            text.pack(side='left', fill='both', expand=True)
            tk.Label(text, text=title, bg=self.COLORS['panel'], fg=self.COLORS['muted'],
                     font=('Helvetica', 8, 'bold')).pack(anchor='w')
            value = tk.Label(text, text='—', bg=self.COLORS['panel'], fg=self.COLORS['text'],
                             font=('Helvetica', 15, 'bold'))
            value.pack(anchor='w')
            self.cards[key] = value

        body = tk.Frame(root, bg=self.COLORS['background'], padx=20, pady=8)
        body.grid(row=2, column=0, sticky='nsew')
        body.grid_columnconfigure(0, weight=7)
        body.grid_columnconfigure(1, weight=4)
        body.grid_rowconfigure(0, weight=5)
        body.grid_rowconfigure(1, weight=3)

        visual_panel = self._panel(body, row=0, column=0, sticky='nsew', padx=(0, 7), pady=(0, 7))
        visual_panel.grid_rowconfigure(1, weight=1)
        visual_panel.grid_columnconfigure(0, weight=1)
        self._section_title(visual_panel, "LIVE GRID", "Generation, storage, and customer load")
        self.scene = tk.Canvas(visual_panel, bg='#102540', highlightthickness=0, height=310)
        self.scene.grid(row=1, column=0, sticky='nsew', padx=10, pady=(0, 10))
        self.scene.bind('<Configure>', lambda _event: self._draw_scene())

        side = self._panel(body, row=0, column=1, rowspan=2, sticky='nsew', padx=(7, 0))
        side.grid_columnconfigure(0, weight=1)
        side.grid_rowconfigure(3, weight=1)
        self._section_title(side, "OPERATIONS", "Fleet and executive actions")

        self.conditions_label = tk.Label(
            side, justify='left', anchor='nw', bg=self.COLORS['panel_alt'],
            fg=self.COLORS['text'], font=('Helvetica', 9), padx=12, pady=9
        )
        self.conditions_label.grid(row=1, column=0, sticky='ew', padx=10, pady=(0, 8))

        self.assets = ttk.Treeview(
            side, columns=('asset', 'units', 'capacity'), show='headings',
            height=6, style='Utility.Treeview'
        )
        self.assets.heading('asset', text='ASSET')
        self.assets.heading('units', text='UNITS')
        self.assets.heading('capacity', text='NAMEPLATE')
        self.assets.column('asset', width=125, anchor='w')
        self.assets.column('units', width=55, anchor='center')
        self.assets.column('capacity', width=90, anchor='e')
        self.assets.grid(row=2, column=0, sticky='ew', padx=10, pady=(0, 8))

        project_box = tk.Frame(side, bg=self.COLORS['panel_alt'], padx=10, pady=8)
        project_box.grid(row=3, column=0, sticky='nsew', padx=10, pady=(0, 8))
        tk.Label(project_box, text="CONSTRUCTION PIPELINE", bg=self.COLORS['panel_alt'],
                 fg=self.COLORS['muted'], font=('Helvetica', 8, 'bold')).pack(anchor='w')
        self.projects_label = tk.Label(
            project_box, text='No active projects', justify='left', anchor='nw',
            bg=self.COLORS['panel_alt'], fg=self.COLORS['text'], font=('Helvetica', 9)
        )
        self.projects_label.pack(fill='both', expand=True, pady=(5, 0))

        actions = tk.Frame(side, bg=self.COLORS['panel'])
        actions.grid(row=4, column=0, sticky='ew', padx=10, pady=(0, 10))
        action_columns = 4
        for column in range(action_columns):
            actions.grid_columnconfigure(column, weight=1, uniform='actions')
        tk.Label(actions, text="BUILD CAPACITY", bg=self.COLORS['panel'],
                 fg=self.COLORS['muted'], font=('Helvetica', 8, 'bold')).grid(
                     row=0, column=0, columnspan=action_columns, sticky='w', pady=(0, 5))
        build_colors = {
            'coal': '#46566b', 'natural_gas': '#397c9d', 'nuclear': '#8067c5',
            'solar': '#b6812c', 'wind': '#357f84', 'hydro': '#286d9a',
            'battery': '#367a57'
        }
        for index, plant_type in enumerate(GUI_BUILD_INFO):
            label = GUI_BUILD_INFO[plant_type][0]
            self._action_button(
                actions, label, lambda kind=plant_type: self.build_plant(kind),
                index // action_columns + 1, index % action_columns,
                build_colors[plant_type]
            )

        management = [
            ("Retire", self.open_retire_menu),
            ("Construction", self.open_construction_menu),
            ("Financial", self.open_financial_menu),
            ("Issue bond", self.issue_bond),
            ("Rate case", self.request_rate_case),
            ("Trade power", self.trade_power),
            ("Dividend", self.set_dividend),
            ("Battery mode", self.toggle_battery_mode),
            ("Emergency loan", self.emergency_loan),
            ("Forecast", self.open_demand_forecast),
            ("Stock trades", self.open_equity_menu),
            ("Help", self.show_help),
        ]
        management_start = math.ceil(len(GUI_BUILD_INFO) / action_columns) + 1
        for index, (label, command) in enumerate(management):
            self._action_button(
                actions, label, command,
                index // action_columns + management_start,
                index % action_columns, self.COLORS['panel_alt']
            )

        chart_panel = self._panel(body, row=1, column=0, sticky='nsew', padx=(0, 7), pady=(7, 0))
        chart_panel.grid_rowconfigure(1, weight=1)
        chart_panel.grid_columnconfigure(0, weight=1)
        self._section_title(chart_panel, "GRID HISTORY", "Produced / maximum including peakers (MW)")
        self.chart = tk.Canvas(chart_panel, bg=self.COLORS['panel'], highlightthickness=0,
                               height=175)
        self.chart.grid(row=1, column=0, sticky='nsew', padx=10, pady=(0, 8))
        self.chart.bind('<Configure>', lambda _event: self._draw_chart())

        log_panel = self._panel(root, row=3, column=0, sticky='ew', padx=20, pady=(0, 16))
        log_panel.grid_columnconfigure(0, weight=1)
        tk.Label(log_panel, text="EVENT LOG", bg=self.COLORS['panel'],
                 fg=self.COLORS['muted'], font=('Helvetica', 8, 'bold')).grid(
                     row=0, column=0, sticky='w', padx=12, pady=(8, 2))
        self.log = tk.Text(
            log_panel, height=4, wrap='word', bg=self.COLORS['panel'],
            fg=self.COLORS['text'], insertbackground=self.COLORS['text'],
            relief='flat', padx=12, pady=4, font=('Helvetica', 9), state='disabled'
        )
        self.log.grid(row=1, column=0, sticky='ew')
        self.log.tag_configure('good', foreground=self.COLORS['green'])
        self.log.tag_configure('warn', foreground=self.COLORS['amber'])
        self.log.tag_configure('bad', foreground=self.COLORS['red'])
        self.log.tag_configure('date', foreground=self.COLORS['cyan'])

    def _section_title(self, parent, title, subtitle):
        heading = tk.Frame(parent, bg=self.COLORS['panel'], padx=12, pady=9)
        heading.grid(row=0, column=0, sticky='ew')
        tk.Label(heading, text=title, bg=self.COLORS['panel'], fg=self.COLORS['text'],
                 font=('Helvetica', 10, 'bold')).pack(side='left')
        tk.Label(heading, text=subtitle, bg=self.COLORS['panel'], fg=self.COLORS['muted'],
                 font=('Helvetica', 9)).pack(side='left', padx=10)

    def _clickable_label(self, parent, label, command, color):
        """Create a button-like control whose colors render consistently on macOS."""
        button = tk.Label(
            parent, text=label, bg=color, fg='#ffffff',
            disabledforeground=self.COLORS['muted'], relief='flat', cursor='hand2',
            font=('Helvetica', 9, 'bold'), padx=4, pady=7, takefocus=True,
            highlightthickness=1, highlightbackground=color,
            highlightcolor=self.COLORS['cyan']
        )
        button._base_color = color

        def invoke(_event=None):
            if str(button.cget('state')) != 'disabled':
                command()
            return 'break'

        def enter(_event=None):
            if str(button.cget('state')) != 'disabled':
                button.configure(bg=self.COLORS['blue'])

        def leave(_event=None):
            button.configure(bg=button._base_color)

        button.bind('<Button-1>', invoke)
        button.bind('<Return>', invoke)
        button.bind('<space>', invoke)
        button.bind('<Enter>', enter)
        button.bind('<Leave>', leave)
        return button

    def _action_button(self, parent, label, command, row, column, color):
        button = self._clickable_label(parent, label, command, color)
        button.grid(row=row, column=column, sticky='ew', padx=2, pady=2)
        if label != "Help":
            self.action_buttons.append(button)
        return button

    def refresh(self):
        session = self.session
        state = session.game_state
        player = session.player
        grid = session.grid
        reserve = grid.reserve_margin(player)
        profit = session.last_monthly_profit

        self.date_label.configure(
            text=f"{MONTH_NAMES[state.current_month - 1].title()}  •  Year {state.year}"
        )
        values = {
            'cash': compact_money(player.cash),
            'profit': compact_money(profit),
            'stock': f"${player.stock_price:,.2f}",
            'demand': f"{grid.total_demand:,.0f} MW",
            'reserve': f"{reserve * 100:+.1f}%",
            'rating': session.credit.rating,
        }
        for key, value in values.items():
            self.cards[key].configure(text=value)
        self.cards['cash'].configure(fg=self.COLORS['red'] if player.cash < 0 else self.COLORS['text'])
        self.cards['profit'].configure(fg=self.COLORS['red'] if profit < 0 else self.COLORS['green'])
        reserve_color = self.COLORS['red'] if reserve < 0 else (
            self.COLORS['amber'] if reserve < TARGET_RESERVE_MARGIN else self.COLORS['green'])
        self.cards['reserve'].configure(fg=reserve_color)

        mood = ("Boom" if session.economy.sentiment > 0.4 else
                "Recession" if session.economy.sentiment < -0.4 else "Stable")
        mode = "battery first" if player.battery_dispatch_mode == 'before_gas' else "gas first"
        carbon = (f"${state.carbon_tax:.2f}/t" if state.carbon_tax > 0 else "not enacted")
        self.conditions_label.configure(text=(
            f"{state.climate.title()} territory  •  Latitude {state.latitude:.1f}°N\n"
            f"Economy: {mood}  •  Inflation {session.economy.inflation * 100:.1f}%/yr  •  "
            f"Rates {session.economy.interest_rate * 100:.1f}%\n"
            f"Price index {session.economy.price_index * 100:.1f} (start 100)  •  "
            f"Wholesale ${wholesale_market_price(session.economy):.2f}/MWh\n"
            f"Gas ${state.natural_gas_price:.2f}/MWh  •  Retail "
            f"${session.regulator.current_retail_price:.2f}/MWh\n"
            f"Carbon tax: {carbon}  •  Dispatch: {mode}\n"
            f"Power contract: {power_contract_description(player.wholesale_commitment_mw)}"
            + (f"\nNext month: {power_contract_description(player.pending_wholesale_commitment_mw)}"
               if player.pending_wholesale_commitment_mw is not None else '')
            + f"\nDividend yield {player.dividend_yield():.2%}  •  "
            f"Shareholder happiness {player.shareholder_happiness:.0f}/100"
        ))
        self.happiness_bar.delete('all')
        happiness = player.shareholder_happiness
        color = ('green' if happiness >= 70 else 'amber' if happiness >= 45
                 else 'orange' if happiness >= 25 else 'red')
        self.happiness_bar.create_rectangle(1, 3, 122, 24, outline=self.COLORS['muted'], width=2)
        self.happiness_bar.create_rectangle(123, 9, 128, 18, fill=self.COLORS['muted'], outline='')
        self.happiness_bar.create_rectangle(4, 6, 4 + 115 * happiness / 100, 21,
                                            fill=self.COLORS[color], outline='')
        self.happiness_bar.create_text(135, 13, text=f'{happiness:.0f}/100', anchor='w',
                                       fill=self.COLORS[color], font=('Helvetica', 10, 'bold'))

        for item in self.assets.get_children():
            self.assets.delete(item)
        capacities = {
            'coal': COAL_PLANT_CAPACITY, 'natural_gas': NATURAL_GAS_PLANT_CAPACITY,
            'nuclear': NUCLEAR_PLANT_CAPACITY, 'solar': SOLAR_PLANT_CAPACITY,
            'wind': WIND_PLANT_CAPACITY, 'hydro': HYDRO_PLANT_CAPACITY,
        }
        for kind, count in player.power_plants.items():
            if count:
                self.assets.insert('', 'end', values=(
                    GUI_BUILD_INFO[kind][0], count, f"{count * capacities[kind]:,.0f} MW"
                ))
        battery_capacity = sum(b.get('max_power', BATTERY_POWER_CAPACITY)
                               for b in player.batteries)
        if player.batteries:
            self.assets.insert('', 'end', values=(
                'Battery', len(player.batteries), f"{battery_capacity:,.0f} MW"
            ))

        if player.ongoing_constructions:
            grouped = {}
            for project in player.ongoing_constructions:
                key = (project['type'], project['turns_remaining'])
                grouped[key] = grouped.get(key, 0) + 1
            lines = []
            for (plant_type, months), count in grouped.items():
                label = GUI_BUILD_INFO[plant_type][0]
                lines.append(f"{label} ×{count}  •  {months} months remaining")
            self.projects_label.configure(text='\n'.join(lines), fg=self.COLORS['text'])
        else:
            self.projects_label.configure(text='No active projects', fg=self.COLORS['muted'])

        self._draw_scene()
        self._draw_chart()
        if session.game_over:
            self.next_button.configure(state='disabled', text='GAME COMPLETE')
            for button in self.action_buttons:
                button.configure(state='disabled')

    def _draw_scene(self):
        canvas = self.scene
        width = max(500, canvas.winfo_width())
        height = max(250, canvas.winfo_height())
        canvas.delete('all')
        state = self.session.game_state
        grid = self.session.grid
        player = self.session.player

        # Layered sky responds to the current sunlight level.
        light = state.region_sunlight_level
        sky_top = (11 + int(18 * light), 35 + int(30 * light), 61 + int(45 * light))
        sky_bottom = (20 + int(35 * light), 57 + int(45 * light), 83 + int(55 * light))
        for band in range(12):
            ratio = band / 11
            color = '#%02x%02x%02x' % tuple(
                int(sky_top[i] + (sky_bottom[i] - sky_top[i]) * ratio) for i in range(3)
            )
            y1 = height * .62 * band / 12
            y2 = height * .62 * (band + 1) / 12 + 1
            canvas.create_rectangle(0, y1, width, y2, fill=color, outline='')
        canvas.create_rectangle(0, height * .62, width, height, fill='#122a2e', outline='')

        sun_x = width * (.18 + .62 * ((state.current_month - 1) / 11))
        sun_r = 13 + 10 * light
        canvas.create_oval(sun_x - sun_r, 24 - sun_r, sun_x + sun_r, 24 + sun_r,
                           fill='#ffd56a', outline='#ffe7a6', width=2)

        kinds = [kind for kind, count in player.power_plants.items() if count]
        usable_width = max(280, width - 240)
        spacing = usable_width / max(1, len(kinds))
        for index, kind in enumerate(kinds):
            x = 55 + spacing * (index + .5)
            self._draw_plant_icon(canvas, kind, x, height * .62,
                                  player.power_plants[kind])
        if player.batteries:
            stored_energy = sum(battery['stored_energy'] for battery in player.batteries)
            usable_energy = sum(battery['current_capacity'] for battery in player.batteries)
            charge_percent = (stored_energy / usable_energy * 100
                              if usable_energy > 0 else 0)
            self._draw_battery(canvas, width - 155, height * .62,
                               len(player.batteries), charge_percent)
        self._draw_city(canvas, width - 45, height * .62)

        line_y = height * .72
        flow_color = self.COLORS['green'] if grid.current_surplus_deficit >= 0 else self.COLORS['red']
        canvas.create_line(35, line_y, width - 25, line_y, fill='#203d4a', width=7)
        canvas.create_line(35, line_y, width - 25, line_y, fill=flow_color, width=3,
                           dash=(10, 12), dashoffset=self.flow_phase, tags='flow_line')
        for x in (width * .30, width * .62, width * .88):
            canvas.create_line(x, line_y, x - 8, line_y + 28, fill='#70899a', width=2)
            canvas.create_line(x, line_y, x + 8, line_y + 28, fill='#70899a', width=2)
            canvas.create_line(x - 7, line_y + 18, x + 7, line_y + 18, fill='#70899a')

        top_text = (f"Produced {grid.total_generation:,.0f} / max {grid.maximum_generation:,.0f} MW\n"
                    f"For customers: {grid.available_for_customers:,.0f} MW   "
                    f"Demand: {grid.total_demand:,.0f} MW\n"
                    f"Contract: +{grid.contract_imports_mw:,.0f} MW in / "
                    f"−{grid.contract_exports_mw:,.0f} MW out")
        canvas.create_text(14, 13, anchor='nw', text=top_text,
                           fill='#e9f4fb', font=('Helvetica', 11, 'bold'))
        balance = grid.current_surplus_deficit
        status = f"SURPLUS  {balance:,.0f} MW" if balance >= 0 else f"SHORTFALL  {abs(balance):,.0f} MW"
        pill_width = 155
        canvas.create_rectangle(width - pill_width - 12, 10, width - 12, 38,
                                fill=flow_color, outline='')
        canvas.create_text(width - pill_width / 2 - 12, 24, text=status,
                           fill='#07131c', font=('Helvetica', 9, 'bold'))

        bar_y = height - 28
        max_power = max(grid.total_generation, grid.total_demand, 1)
        bar_width = width - 120
        gen_width = bar_width * grid.total_generation / max_power
        demand_width = bar_width * grid.total_demand / max_power
        canvas.create_text(12, bar_y - 7, text='SUPPLY', anchor='w', fill=self.COLORS['muted'],
                           font=('Helvetica', 7, 'bold'))
        canvas.create_rectangle(65, bar_y - 15, 65 + gen_width, bar_y - 9,
                                fill=self.COLORS['cyan'], outline='')
        canvas.create_text(12, bar_y + 7, text='DEMAND', anchor='w', fill=self.COLORS['muted'],
                           font=('Helvetica', 7, 'bold'))
        canvas.create_rectangle(65, bar_y + 1, 65 + demand_width, bar_y + 7,
                                fill=self.COLORS['orange'], outline='')

    def _draw_plant_icon(self, canvas, kind, x, ground, count):
        colors = {
            'coal': '#697688', 'natural_gas': '#56a6c7', 'nuclear': '#a184e5',
            'solar': '#e2ae46', 'wind': '#66c7ca', 'hydro': '#4f9fd1'
        }
        color = colors[kind]
        if kind in ('coal', 'natural_gas'):
            canvas.create_rectangle(x - 25, ground - 42, x + 25, ground,
                                    fill=color, outline='')
            canvas.create_rectangle(x - 17, ground - 72, x - 7, ground - 42,
                                    fill='#344554', outline='')
            if kind == 'coal':
                canvas.create_oval(x - 20, ground - 82, x - 5, ground - 68,
                                   fill='#7890a2', outline='')
        elif kind == 'nuclear':
            canvas.create_polygon(x - 27, ground, x - 20, ground - 55,
                                  x + 20, ground - 55, x + 27, ground,
                                  fill=color, outline='')
            canvas.create_oval(x - 20, ground - 65, x + 20, ground - 45,
                               fill='#b9a8ed', outline='')
        elif kind == 'solar':
            canvas.create_polygon(x - 34, ground - 10, x + 26, ground - 10,
                                  x + 35, ground - 43, x - 25, ground - 43,
                                  fill='#245985', outline=color, width=2)
            for shift in (-14, 5, 23):
                canvas.create_line(x + shift, ground - 42, x + shift - 8, ground - 11,
                                   fill=color)
            canvas.create_line(x, ground - 10, x, ground, fill='#8499a5', width=3)
        elif kind == 'wind':
            canvas.create_line(x, ground, x, ground - 58, fill='#c1dde1', width=3)
            hub_y = ground - 58
            canvas.create_oval(x - 4, hub_y - 4, x + 4, hub_y + 4,
                               fill=color, outline='')
            canvas.create_line(x, hub_y, x - 24, hub_y - 13, fill=color, width=3)
            canvas.create_line(x, hub_y, x + 25, hub_y - 10, fill=color, width=3)
            canvas.create_line(x, hub_y, x - 2, hub_y + 26, fill=color, width=3)
        elif kind == 'hydro':
            canvas.create_polygon(x - 31, ground, x - 22, ground - 48,
                                  x + 23, ground - 48, x + 31, ground,
                                  fill='#718494', outline=color, width=2)
            canvas.create_line(x - 13, ground - 43, x - 6, ground - 4,
                               fill='#b8c6d0', width=2)
            canvas.create_line(x + 2, ground - 43, x + 8, ground - 4,
                               fill='#b8c6d0', width=2)
            canvas.create_arc(x + 12, ground - 32, x + 48, ground + 5,
                              start=70, extent=210, style='arc', outline='#63c7ed', width=3)
        canvas.create_text(x, ground + 12, text=f"{GUI_BUILD_INFO[kind][0]} ×{count}",
                           fill='#c7d8e3', font=('Helvetica', 8, 'bold'))

    def _draw_battery(self, canvas, x, ground, count, charge_percent):
        canvas.create_rectangle(x - 20, ground - 45, x + 20, ground,
                                fill='#18372e', outline='#64d79d', width=2)
        fill_bottom = ground - 3
        fill_height = 39 * max(0, min(100, charge_percent)) / 100
        if fill_height > 0:
            canvas.create_rectangle(
                x - 17, fill_bottom - fill_height, x + 17, fill_bottom,
                fill='#2d8e64', outline=''
            )
        canvas.create_rectangle(x - 7, ground - 51, x + 7, ground - 45,
                                fill='#64d79d', outline='')
        canvas.create_polygon(x + 1, ground - 40, x - 9, ground - 23,
                              x - 1, ground - 23, x - 7, ground - 8,
                              x + 10, ground - 29, x + 2, ground - 29,
                              fill='#d9ffe9')
        canvas.create_text(x, ground + 12,
                           text=f"Battery ×{count} • {charge_percent:.0f}% charged",
                           fill='#c7d8e3', font=('Helvetica', 8, 'bold'))

    def _draw_city(self, canvas, x, ground):
        buildings = [(0, 38, 24), (18, 58, 20), (34, 44, 24), (52, 68, 22)]
        for offset, height, width in buildings:
            left = x + offset - 56
            canvas.create_rectangle(left, ground - height, left + width, ground,
                                    fill='#243b4b', outline='#486175')
            for wy in range(int(ground - height + 9), int(ground - 5), 12):
                canvas.create_rectangle(left + 5, wy, left + 8, wy + 4,
                                        fill='#f1c75a', outline='')
        canvas.create_text(x - 18, ground + 12, text="Customers", fill='#c7d8e3',
                           font=('Helvetica', 8, 'bold'))

    def _record_history(self):
        grid = self.session.grid
        state = self.session.game_state
        self.history.append({
            'label': f"{MONTH_NAMES[state.current_month - 1][:3].title()} {state.year}",
            'generation': grid.total_generation,
            'maximum_generation': grid.maximum_generation,
            'demand': grid.total_demand,
        })
        self.history = self.history[-24:]

    def _draw_chart(self):
        canvas = self.chart
        width = max(400, canvas.winfo_width())
        height = max(140, canvas.winfo_height())
        canvas.delete('all')
        left, right, top, bottom = 48, width - 16, 30, height - 28
        all_values = [point[key] for point in self.history
                      for key in ('generation', 'maximum_generation', 'demand')]
        ceiling = max(all_values + [1]) * 1.12
        for line in range(4):
            y = top + (bottom - top) * line / 3
            value = ceiling * (1 - line / 3)
            canvas.create_line(left, y, right, y, fill=self.COLORS['line'])
            canvas.create_text(left - 7, y, text=f"{value:,.0f}", anchor='e',
                               fill=self.COLORS['muted'], font=('Helvetica', 7))
        if len(self.history) == 1:
            x_positions = [(left + right) / 2]
        else:
            x_positions = [left + (right - left) * i / (len(self.history) - 1)
                           for i in range(len(self.history))]
        for key, color, dash in (('maximum_generation', self.COLORS['purple'], (5, 3)),
                                 ('generation', self.COLORS['cyan'], ()),
                                 ('demand', self.COLORS['orange'], ())):
            coords = []
            for x, point in zip(x_positions, self.history):
                y = bottom - (bottom - top) * point[key] / ceiling
                coords.extend((x, y))
            if len(coords) >= 4:
                canvas.create_line(*coords, fill=color, width=2, dash=dash)
            elif coords:
                canvas.create_oval(coords[0] - 3, coords[1] - 3,
                                   coords[0] + 3, coords[1] + 3, fill=color, outline='')
        if self.history:
            canvas.create_text(left, bottom + 13, text=self.history[0]['label'], anchor='w',
                               fill=self.COLORS['muted'], font=('Helvetica', 7))
            canvas.create_text(right, bottom + 13, text=self.history[-1]['label'], anchor='e',
                               fill=self.COLORS['muted'], font=('Helvetica', 7))
        for offset, label, color, dash in (
            (0, 'Produced', self.COLORS['cyan'], ()),
            (95, 'Max incl. gas', self.COLORS['purple'], (5, 3)),
            (220, 'Demand', self.COLORS['orange'], ()),
        ):
            x = left + offset
            canvas.create_line(x, 10, x + 18, 10, fill=color, width=2, dash=dash)
            canvas.create_text(x + 23, 10, text=label, anchor='w',
                               fill=self.COLORS['muted'], font=('Helvetica', 8))

    def _animate_flow(self):
        if not self.root.winfo_exists():
            return
        self.flow_phase = (self.flow_phase + 2) % 22
        try:
            self.scene.itemconfigure('flow_line', dashoffset=self.flow_phase)
        except tk.TclError:
            return
        self.root.after(140, self._animate_flow)

    def _append_log(self, text):
        if not text:
            return
        self.log.configure(state='normal')
        state = self.session.game_state
        stamp = f"{MONTH_NAMES[state.current_month - 1].title()} Y{state.year}  "
        self.log.insert('end', stamp, 'date')
        for line in text.splitlines():
            if not line.strip():
                continue
            lowered = line.lower()
            tag = ('bad' if any(word in lowered for word in ('bankrupt', 'failed', 'rejected', 'insufficient'))
                   else 'warn' if any(word in lowered for word in ('warning', 'overrun', 'emergency', 'matured'))
                   else 'good' if any(word in lowered for word in ('complete', 'approved', 'started', 'issued'))
                   else None)
            if tag:
                self.log.insert('end', line.strip() + "\n", tag)
            else:
                self.log.insert('end', line.strip() + "\n")
        self.log.see('end')
        self.log.configure(state='disabled')

    def _run_action(self, action):
        if self.session.game_over:
            return "GAME_OVER"
        output = io.StringIO()
        try:
            with contextlib.redirect_stdout(output):
                result = action()
        except (ValueError, KeyError) as exc:
            messagebox.showerror("Action could not be completed", str(exc), parent=self.root)
            return None
        self._append_log(output.getvalue().strip())
        if self.session.player.fired:
            self.session.game_over = True
            if result != 'FIRED':
                messagebox.showerror('You have been fired', self.session.player.shareholder_status(),
                                     parent=self.root)
        self.refresh()
        return result

    def save_game(self):
        path = filedialog.asksaveasfilename(parent=self.root, title='Save Gridline game',
            defaultextension='.gridline.json', initialfile='utility-v2.gridline.json',
            filetypes=[('Gridline save', '*.gridline.json'), ('JSON', '*.json')])
        if not path:
            return
        self.session.ui_state = dict(history=self.history, event_log=self.log.get('1.0', 'end-1c'))
        try:
            self.session.save_game(path)
        except (OSError, utility_persistence.SaveError) as exc:
            messagebox.showerror('Save failed', str(exc), parent=self.root)
            return
        self._append_log(f'Game saved to {path}')

    def load_game(self):
        path = filedialog.askopenfilename(parent=self.root, title='Load Gridline game',
            filetypes=[('Gridline save', '*.gridline.json'), ('JSON', '*.json')])
        if not path or not messagebox.askyesno('Replace current game?',
                'Load this save and replace the current unsaved game?', parent=self.root):
            return
        try:
            loaded = UtilityGameSession.load_game(path)
        except (OSError, utility_persistence.SaveError) as exc:
            messagebox.showerror('Load failed', str(exc), parent=self.root)
            return
        for window in self.root.winfo_children():
            if isinstance(window, tk.Toplevel):
                window.destroy()
        self.session = loaded
        self.history = list(loaded.ui_state.get('history', []))
        if not self.history:
            self._record_history()
        self.log.configure(state='normal')
        self.log.delete('1.0', 'end')
        self.log.insert('end', loaded.ui_state.get('event_log', ''))
        self.log.configure(state='disabled')
        self._append_log('Saved game loaded; simulation state and future random events restored.')
        self.refresh()

    def open_equity_menu(self):
        window = tk.Toplevel(self.root)
        window.title('Stock issuance and buybacks')
        window.configure(bg=self.COLORS['panel'])
        p = self.session.player
        tk.Label(window, text=f'Outstanding shares: {p.shares_outstanding:,}\n'
                 f'Annual allowance remaining: {p.remaining_share_allowance():,} shares\n'
                 'Issues and buybacks share a 4.9% annual limit in both shares and value.\n'
                 'Execution spread: 1%. Issuance hurts shareholder happiness;\n'
                 'sustained buybacks help, with no penalty for stopping.', justify='left',
                 bg=self.COLORS['panel'], fg=self.COLORS['text'], padx=18, pady=18).pack()
        for label, action in (('ISSUE STOCK', 'issue'), ('BUY BACK STOCK', 'buyback')):
            self._clickable_label(window, label,
                lambda kind=action: (window.destroy(), self.trade_equity(kind)),
                self.COLORS['blue']).pack(fill='x', padx=18, pady=6)

    def trade_equity(self, action):
        p = self.session.player
        remaining = p.remaining_share_allowance()
        if remaining <= 0:
            messagebox.showinfo('Annual limit', 'No stock-trading allowance remains this year.', parent=self.root)
            return
        quantity = simpledialog.askinteger('Issue stock' if action == 'issue' else 'Buy back stock',
            f'How many shares? Annual allowance remaining: {remaining:,}\n'
            f'Current price ${p.stock_price:.2f}; 1% execution spread.',
            minvalue=1, maxvalue=remaining, parent=self.root)
        if quantity is not None:
            factor = 1 - SHARE_TRADE_SPREAD if action == 'issue' else 1 + SHARE_TRADE_SPREAD
            amount = quantity * p.stock_price * factor
            if messagebox.askyesno('Confirm stock transaction',
                    f'{action.title()} {quantity:,} shares for {compact_money(amount)}?', parent=self.root):
                self._run_action(lambda: p.trade_shares(action, quantity, self.session.game_state))

    def build_plant(self, plant_type):
        label, _base_cost, months = GUI_BUILD_INFO[plant_type]
        quantity = simpledialog.askinteger(
            f"Build {label}", "How many units do you want to build?",
            initialvalue=1, minvalue=1, maxvalue=50, parent=self.root
        )
        if quantity is None:
            return
        cost = self.session.player.construction_quote(plant_type, quantity)
        site_note = ("\nEach additional hydro site is more expensive."
                     if plant_type == 'hydro' and quantity > 1 else "")
        unit_capacity = PLANT_NAMEPLATE_CAPACITY[plant_type]
        capacity_text = f"{quantity * unit_capacity:,} MW total"
        if plant_type == 'battery':
            capacity_text += f" / {quantity * BATTERY_ENERGY_CAPACITY:,} MWh"
        confirmed = messagebox.askyesno(
            f"Build {label}",
            f"Start {quantity} new {label.lower()} project"
            f"{'s' if quantity != 1 else ''}?\n\n"
            f"Capacity: {capacity_text}\nTotal cost: {compact_money(cost)}\n"
            f"Includes cumulative inflation ({self.session.economy.price_index - 1:+.1%}).\n"
            f"Construction: {months} months"
            f"{site_note}",
            parent=self.root
        )
        if confirmed:
            self._run_action(lambda: self.session.player.start_construction(
                plant_type, quantity
            ))

    def open_retire_menu(self):
        player = self.session.player
        window = tk.Toplevel(self.root)
        window.title("Retire an asset")
        window.configure(bg=self.COLORS['panel'])
        window.resizable(False, False)
        window.transient(self.root)
        tk.Label(window, text="Choose an asset to retire", bg=self.COLORS['panel'],
                 fg=self.COLORS['text'], font=('Helvetica', 13, 'bold')).pack(
                     padx=22, pady=(18, 10))
        found = False
        for kind, count in player.power_plants.items():
            if count:
                found = True
                asset_button = self._clickable_label(
                    window, f"{GUI_BUILD_INFO[kind][0]}  ({count} owned)",
                    lambda selected=kind: self._retire_asset(selected, window),
                    self.COLORS['panel_alt']
                )
                asset_button.configure(width=28)
                asset_button.pack(padx=22, pady=3)
        if player.batteries:
            found = True
            battery_button = self._clickable_label(
                window, f"Battery  ({len(player.batteries)} owned)",
                lambda: self._retire_asset('battery', window),
                self.COLORS['panel_alt']
            )
            battery_button.configure(width=28)
            battery_button.pack(padx=22, pady=3)
        if not found:
            tk.Label(window, text="There are no assets to retire.", bg=self.COLORS['panel'],
                     fg=self.COLORS['muted']).pack(padx=22, pady=12)
        tk.Button(window, text="Cancel", command=window.destroy, bg=self.COLORS['panel'],
                  fg=self.COLORS['muted'], relief='flat').pack(pady=(8, 16))

    def _retire_asset(self, plant_type, window):
        label = GUI_BUILD_INFO[plant_type][0]
        owned = (len(self.session.player.batteries) if plant_type == 'battery'
                 else self.session.player.power_plants[plant_type])
        quantity = simpledialog.askinteger(
            f"Retire {label}", f"How many units? ({owned} owned)",
            initialvalue=1, minvalue=1, maxvalue=owned, parent=window
        )
        if quantity is None:
            return
        if messagebox.askyesno("Confirm retirement",
                               f"Retire {quantity} {label.lower()} asset"
                               f"{'s' if quantity != 1 else ''}?",
                               parent=window):
            window.destroy()
            if plant_type == 'battery':
                self._run_action(lambda: self.session.player.decommission_battery(quantity))
            else:
                self._run_action(lambda: self.session.player.decommission_plant(
                    plant_type, quantity
                ))

    def open_construction_menu(self):
        window = tk.Toplevel(self.root)
        window.title("Projects in Construction")
        window.configure(bg=self.COLORS['background'])
        window.geometry("900x500")
        window.minsize(760, 400)
        window.transient(self.root)
        window.grid_columnconfigure(0, weight=1)
        window.grid_rowconfigure(2, weight=1)

        heading = tk.Frame(window, bg=self.COLORS['background'], padx=20, pady=14)
        heading.grid(row=0, column=0, sticky='ew')
        tk.Label(heading, text="PROJECTS IN CONSTRUCTION",
                 bg=self.COLORS['background'], fg=self.COLORS['text'],
                 font=('Helvetica', 18, 'bold')).pack(anchor='w')
        tk.Label(heading, text="Schedule, completion progress, and committed capital",
                 bg=self.COLORS['background'], fg=self.COLORS['muted'],
                 font=('Helvetica', 9)).pack(anchor='w')

        projects = self.session.player.ongoing_constructions
        committed = sum(project['total_cost'] for project in projects)
        overruns = sum(max(0, project['total_cost'] - project['initial_cost'])
                       for project in projects)
        summary = tk.Label(
            window,
            text=(f"Active projects  {len(projects)}     Capital committed  "
                  f"{compact_money(committed)}     Cost overruns  {compact_money(overruns)}"),
            justify='left', anchor='w', bg=self.COLORS['panel'],
            fg=self.COLORS['text'], padx=14, pady=11, font=('Helvetica', 10),
            highlightthickness=1, highlightbackground=self.COLORS['line']
        )
        summary.grid(row=1, column=0, sticky='ew', padx=20, pady=(0, 10))

        table_frame = tk.Frame(window, bg=self.COLORS['panel'], padx=10, pady=10,
                               highlightthickness=1, highlightbackground=self.COLORS['line'])
        table_frame.grid(row=2, column=0, sticky='nsew', padx=20)
        table_frame.grid_columnconfigure(0, weight=1)
        table_frame.grid_rowconfigure(0, weight=1)
        columns = ('project', 'type', 'status', 'progress', 'remaining', 'original', 'current')
        table = ttk.Treeview(
            table_frame, columns=columns, show='headings', style='Utility.Treeview'
        )
        headings = {
            'project': '#', 'type': 'PROJECT', 'status': 'STATUS',
            'progress': 'COMPLETE', 'remaining': 'REMAINING',
            'original': 'ORIGINAL COST', 'current': 'CURRENT COST',
        }
        widths = {
            'project': 35, 'type': 105, 'status': 105, 'progress': 80,
            'remaining': 95, 'original': 125, 'current': 125,
        }
        for column in columns:
            table.heading(column, text=headings[column])
            table.column(column, width=widths[column],
                         anchor='w' if column in ('type', 'status') else 'e')
        table.grid(row=0, column=0, sticky='nsew')
        scrollbar = ttk.Scrollbar(table_frame, orient='vertical', command=table.yview)
        scrollbar.grid(row=0, column=1, sticky='ns')
        table.configure(yscrollcommand=scrollbar.set)
        table.tag_configure('overrun', foreground=self.COLORS['amber'])

        for index, project in enumerate(projects, start=1):
            duration = GUI_BUILD_INFO[project['type']][2]
            elapsed = max(0, duration - project['turns_remaining'])
            progress = min(100, elapsed / max(duration, 1) * 100)
            overrun = project['total_cost'] > project['initial_cost'] + 0.01
            table.insert('', 'end', values=(
                index, GUI_BUILD_INFO[project['type']][0],
                'Cost overrun' if overrun else 'On schedule', f"{progress:.0f}%",
                f"{project['turns_remaining']} months",
                compact_money(project['initial_cost']),
                compact_money(project['total_cost']),
            ), tags=('overrun',) if overrun else ())
        if not projects:
            table.insert('', 'end', values=('', 'No active projects', '', '', '', '', ''))

        controls = tk.Frame(window, bg=self.COLORS['background'], padx=20, pady=12)
        controls.grid(row=3, column=0, sticky='ew')
        refresh = self._clickable_label(
            controls, "REFRESH",
            lambda: (window.destroy(), self.open_construction_menu()),
            self.COLORS['blue']
        )
        refresh.pack(side='left')
        close = self._clickable_label(
            controls, "CLOSE", window.destroy, self.COLORS['panel_alt']
        )
        close.pack(side='right')

    def open_financial_menu(self):
        window = tk.Toplevel(self.root)
        window.title("Financial Center")
        window.configure(bg=self.COLORS['background'])
        window.geometry("980x735")
        window.minsize(820, 580)
        window.transient(self.root)
        window.grid_columnconfigure(0, weight=1)
        window.grid_rowconfigure(3, weight=1)

        heading = tk.Frame(window, bg=self.COLORS['background'], padx=20, pady=14)
        heading.grid(row=0, column=0, sticky='ew')
        tk.Label(heading, text="FINANCIAL CENTER", bg=self.COLORS['background'],
                 fg=self.COLORS['text'], font=('Helvetica', 18, 'bold')).pack(anchor='w')
        tk.Label(heading, text="Capital structure, shareholder return, and debt management",
                 bg=self.COLORS['background'], fg=self.COLORS['muted'],
                 font=('Helvetica', 9)).pack(anchor='w')
        window.shareholder_warning = tk.Label(
            heading, bg=self.COLORS['background'], fg=self.COLORS['amber'],
            font=('Helvetica', 9, 'bold'), justify='left', wraplength=900
        )
        window.shareholder_warning.pack(anchor='w', pady=(6, 0))

        summary = tk.Label(
            window, justify='left', anchor='nw', bg=self.COLORS['panel'],
            fg=self.COLORS['text'], padx=14, pady=11, font=('Helvetica', 10),
            highlightthickness=1, highlightbackground=self.COLORS['line']
        )
        summary.grid(row=1, column=0, sticky='ew', padx=20, pady=(0, 10))

        carbon_frame = tk.Frame(
            window, bg=self.COLORS['panel'], padx=10, pady=9,
            highlightthickness=1, highlightbackground=self.COLORS['line']
        )
        carbon_frame.grid(row=2, column=0, sticky='ew', padx=20, pady=(0, 10))
        carbon_frame.grid_columnconfigure(0, weight=1)
        window.carbon_heading = tk.Label(
            carbon_frame, text="CARBON EXPOSURE — ANNUALIZED",
            bg=self.COLORS['panel'], fg=self.COLORS['muted'],
            font=('Helvetica', 8, 'bold')
        )
        window.carbon_heading.grid(row=0, column=0, sticky='w', pady=(0, 6))
        carbon_columns = ('source', 'units', 'generation', 'emissions', 'tax')
        window.carbon_table = ttk.Treeview(
            carbon_frame, columns=carbon_columns, show='headings', height=3,
            style='Utility.Treeview', selectmode='none'
        )
        carbon_headings = {
            'source': 'EMITTING SOURCE', 'units': 'PLANTS',
            'generation': 'ANNUAL GENERATION', 'emissions': 'CO₂ EMISSIONS',
            'tax': 'ANNUAL TAX',
        }
        carbon_widths = {
            'source': 150, 'units': 75, 'generation': 160,
            'emissions': 150, 'tax': 145,
        }
        for column in carbon_columns:
            window.carbon_table.heading(column, text=carbon_headings[column])
            window.carbon_table.column(
                column, width=carbon_widths[column],
                anchor='w' if column == 'source' else 'e'
            )
        window.carbon_table.grid(row=1, column=0, sticky='ew')

        table_frame = tk.Frame(window, bg=self.COLORS['panel'], padx=10, pady=10,
                               highlightthickness=1, highlightbackground=self.COLORS['line'])
        table_frame.grid(row=3, column=0, sticky='nsew', padx=20)
        table_frame.grid_columnconfigure(0, weight=1)
        table_frame.grid_rowconfigure(1, weight=1)
        tk.Label(table_frame, text="OUTSTANDING BOND LADDER", bg=self.COLORS['panel'],
                 fg=self.COLORS['muted'], font=('Helvetica', 8, 'bold')).grid(
                     row=0, column=0, sticky='w', pady=(0, 7))

        columns = ('principal', 'coupon', 'remaining', 'market_yield', 'market_value', 'settlement')
        ladder = ttk.Treeview(
            table_frame, columns=columns, show='headings', style='Utility.Treeview',
            selectmode='browse'
        )
        headings = {
            'principal': 'PRINCIPAL', 'coupon': 'COUPON', 'remaining': 'REMAINING',
            'market_yield': 'MARKET YIELD', 'market_value': 'MARKET VALUE',
            'settlement': 'BUYBACK COST',
        }
        widths = {
            'principal': 125, 'coupon': 80, 'remaining': 105,
            'market_yield': 105, 'market_value': 130, 'settlement': 130,
        }
        for column in columns:
            ladder.heading(column, text=headings[column])
            ladder.column(column, width=widths[column], anchor='e')
        ladder.grid(row=1, column=0, sticky='nsew')
        scrollbar = ttk.Scrollbar(table_frame, orient='vertical', command=ladder.yview)
        scrollbar.grid(row=1, column=1, sticky='ns')
        ladder.configure(yscrollcommand=scrollbar.set)

        statements = tk.Frame(window, bg=self.COLORS['background'], padx=20)
        statements.grid(row=4, column=0, sticky='ew', pady=(10, 0))
        tk.Label(
            statements, text="FINANCIAL STATEMENTS", bg=self.COLORS['background'],
            fg=self.COLORS['muted'], font=('Helvetica', 8, 'bold')
        ).pack(side='left', padx=(0, 10))
        for label, statement_type in (
            ("INCOME STATEMENT", 'income'),
            ("BALANCE SHEET", 'balance'),
            ("CASH FLOW", 'cash_flow'),
        ):
            button = self._clickable_label(
                statements, label,
                lambda kind=statement_type: self.open_statement_window(kind),
                self.COLORS['panel_alt']
            )
            button.pack(side='left', padx=(0, 7))

        controls = tk.Frame(window, bg=self.COLORS['background'], padx=20, pady=12)
        controls.grid(row=5, column=0, sticky='ew')
        buyback = self._clickable_label(
            controls, "BUY BACK SELECTED BOND",
            lambda: self._buyback_selected_bond(window, summary, ladder),
            self.COLORS['blue']
        )
        buyback.pack(side='left')
        issue = self._clickable_label(
            controls, "ISSUE NEW BOND",
            lambda: (self.issue_bond(),
                     self._populate_financial_menu(window, summary, ladder)),
            self.COLORS['panel_alt']
        )
        issue.pack(side='left', padx=8)
        dividend = self._clickable_label(
            controls, "SET DIVIDEND",
            lambda: (self.set_dividend(),
                     self._populate_financial_menu(window, summary, ladder)),
            self.COLORS['panel_alt']
        )
        dividend.pack(side='left')
        close = self._clickable_label(
            controls, "CLOSE", window.destroy, self.COLORS['panel_alt']
        )
        close.pack(side='right')

        self._populate_financial_menu(window, summary, ladder)

    def _populate_financial_menu(self, window, summary, ladder):
        if not window.winfo_exists():
            return
        player = self.session.player
        economy = self.session.economy
        credit = self.session.credit
        financials = self.session.financials
        dividend_yield = (player.annual_dividend_per_share
                          / max(player.stock_price, 0.01) * 100)
        total_debt = player.total_debt()
        annual_interest = sum(b.monthly_interest() for b in player.bonds) * 12
        weighted_coupon = (annual_interest / total_debt * 100) if total_debt else 0
        debt_market_value = sum(
            player.bond_buyback_quote(bond, economy, credit)[2]
            for bond in player.bonds
        )
        book_equity = player.book_equity()
        debt_to_book = f'{total_debt / book_equity:.2f}×' if book_equity > 0 else 'N/M'
        price_to_book = (player.company_value / book_equity
                         if book_equity > 0 else float('inf'))
        book_value_per_share = book_equity / max(player.shares_outstanding, 1)
        pb_text = f"{price_to_book:.2f}×" if math.isfinite(price_to_book) else "N/M"
        net_debt = player.net_debt()
        net_leverage = (f"{max(0.0, net_debt) / book_equity:.2f}×"
                        if book_equity > 0 else "N/M")
        window.shareholder_warning.configure(
            text=player.shareholder_status(),
            fg=self.COLORS['amber'] if player.dividend_yield() < MIN_DIVIDEND_YIELD
            else self.COLORS['muted']
        )
        summary.configure(text=(
            f"Cash  {compact_money(player.cash)}     Total debt  {compact_money(total_debt)}     "
            f"Debt / book equity  {debt_to_book}     Credit  {credit.rating}\n"
            f"Net debt (bonds − cash)  {compact_money(net_debt)}     "
            f"Net debt / book equity  {net_leverage}     "
            f"TTM EBITDA / interest  {credit.interest_coverage:.2f}×\n"
            f"Borrowing this month  {compact_money(player.debt_issued_since_close)} / "
            f"{compact_money(player.monthly_borrowing_limit)}     "
            f"Remaining  {compact_money(player.remaining_borrowing_capacity())}     "
            f"Cap: {MONTHLY_BORROWING_ASSET_FRACTION:.0%} of opening non-cash assets\n"
            f"Stock  ${player.stock_price:,.2f}     Market cap  {compact_money(player.company_value)}     "
            f"Dividend  ${player.annual_dividend_per_share:.3f}/share     Yield  {dividend_yield:.2f}%\n"
            f"TTM EPS  ${financials.ttm_eps(player.shares_outstanding):.3f}     "
            f"Actual P/E  {self._pe_text()}     Valuation P/E  {player.valuation_pe:.1f}×     "
            f"Earnings weight  {EARNINGS_WEIGHT:.0%}\n"
            f"Book equity  {compact_money(book_equity)}     Book value/share  ${book_value_per_share:,.2f}     "
            f"Price / book  {pb_text}     Book valuation benchmark  {UTILITY_TARGET_PRICE_TO_BOOK:.2f}×\n"
            f"Annual interest  {compact_money(annual_interest)}     Weighted coupon  {weighted_coupon:.2f}%     "
            f"Debt market value  {compact_money(debt_market_value)}\n"
            f"Base rate  {economy.interest_rate * 100:.2f}%     "
            f"Carbon cost/month  {compact_money(financials.carbon_costs / 12)}     "
            f"Price index  {economy.price_index * 100:.2f} (start 100)\n"
            f"Recurring power: {power_contract_description(player.wholesale_commitment_mw)}"
            + (f"     Next month: {power_contract_description(player.pending_wholesale_commitment_mw)}"
               if player.pending_wholesale_commitment_mw is not None else '')
        ))

        carbon_table = window.carbon_table
        for item in carbon_table.get_children():
            carbon_table.delete(item)
        state = self.session.game_state
        tax_text = (f"${state.carbon_tax:.2f}/metric ton"
                    if state.carbon_tax > 0 else "not yet enacted")
        window.carbon_heading.configure(
            text=f"CARBON EXPOSURE — ANNUALIZED     CURRENT TAX: {tax_text}"
        )
        carbon_rows = (
            ('Coal', player.power_plants['coal'], financials.coal_generation_mwh,
             financials.coal_emissions_tons, financials.coal_carbon_cost),
            ('Natural gas', player.power_plants['natural_gas'],
             financials.gas_generation_mwh, financials.gas_emissions_tons,
             financials.gas_carbon_cost),
            ('TOTAL', player.power_plants['coal'] + player.power_plants['natural_gas'],
             financials.coal_generation_mwh + financials.gas_generation_mwh,
             financials.total_emissions_tons, financials.carbon_costs),
        )
        for source, units, generation, emissions, tax_cost in carbon_rows:
            carbon_table.insert('', 'end', values=(
                source, units, f"{generation / 1_000_000:.2f} TWh",
                f"{emissions / 1_000_000:.2f} Mt", compact_money(tax_cost),
            ))

        for item in ladder.get_children():
            ladder.delete(item)
        ladder.bond_lookup = {}
        ordered_bonds = sorted(player.bonds, key=lambda item: item.months_remaining)
        for index, bond in enumerate(ordered_bonds, start=1):
            settlement, market_yield, clean_value = player.bond_buyback_quote(
                bond, economy, credit
            )
            iid = f"bond_{index}_{id(bond)}"
            ladder.bond_lookup[iid] = bond
            years, months = divmod(max(0, bond.months_remaining), 12)
            remaining = f"{years}y {months}m" if years else f"{months}m"
            ladder.insert('', 'end', iid=iid, values=(
                compact_money(bond.principal), f"{bond.annual_rate * 100:.2f}%",
                remaining, f"{market_yield * 100:.2f}%", compact_money(clean_value),
                compact_money(settlement),
            ))

    def _pe_text(self):
        eps = self.session.financials.ttm_eps(self.session.player.shares_outstanding)
        return f'{self.session.player.stock_price / eps:.2f}×' if eps > 0 else 'N/M (loss)'

    def open_statement_window(self, statement_type, frequency='monthly'):
        """Open a detailed statement; hovering any line explains the accounting term."""
        if frequency != 'monthly':
            self.open_period_statement(statement_type, frequency)
            return
        player = self.session.player
        financials = self.session.financials

        if statement_type == 'income':
            title = "INCOME STATEMENT"
            subtitle = ('Latest monthly results — operating costs by plant in the next tab'
                        if financials.has_closed_month else
                        'Opening monthly estimate — operating costs by plant in the next tab')
            rows = [
                ('OPERATING REVENUE', None, 'section'),
                ('Electric revenue', financials.monthly_electric_revenue, 'normal'),
                ('Contract power sales', financials.contract_sales_revenue, 'normal'),
                ('Spot power sales', financials.spot_sales_revenue, 'normal'),
                ('Total operating revenue', financials.total_operating_revenue, 'total'),
                ('OPERATING EXPENSES', None, 'section'),
                ('Fuel and variable O&M', -financials.monthly_variable_operating_costs, 'normal'),
                ('Contract power purchases', -financials.contract_purchase_cost, 'normal'),
                ('Spot power purchases', -financials.spot_purchase_cost, 'normal'),
                ('Carbon tax expense', -financials.monthly_carbon_tax_expense, 'normal'),
                ('Cash operating expenses', -financials.cash_operating_expenses, 'total'),
                ('EBITDA', financials.ebitda, 'total'),
                ('Depreciation and amortization', -financials.depreciation_expense, 'normal'),
                ('Operating income (EBIT)', financials.operating_income, 'total'),
                ('Retirement / debt gain (loss)', financials.unusual_gain_loss, 'normal'),
                ('Interest expense', -financials.interest_expense, 'normal'),
                ('Income before tax', financials.pretax_income, 'total'),
                ('Income tax expense', -financials.income_tax_expense, 'normal'),
                ('Net income after interest', financials.net_profit, 'grand'),
                ('Weighted average shares',
                 f"{financials.monthly_weighted_shares / 1_000_000:,.1f}M", 'normal'),
                ('Basic earnings per share',
                 f"${financials.net_profit / max(financials.monthly_weighted_shares, 1):,.3f}",
                 'normal'),
                ('TRAILING EARNINGS AND STOCK VALUATION', None, 'section'),
                ('TTM net income', financials.ttm_net_income, 'normal'),
                ('Trailing twelve-month EPS',
                 f"${financials.ttm_eps(player.shares_outstanding):,.3f}", 'grand'),
                ('TTM earnings coverage', financials.ttm_coverage_description(), 'normal'),
                ('Actual price / earnings', self._pe_text(), 'normal'),
                ('Utility P/E multiple', f'{player.valuation_pe:.2f}×', 'normal'),
                ('EPS-based price benchmark', f'${player.earnings_price_target:,.2f}', 'normal'),
            ]
        elif statement_type == 'balance':
            title = "BALANCE SHEET"
            subtitle = "Current book values — see Plant details for individual costs and depreciation"
            current_debt = sum(
                bond.principal for bond in player.bonds if bond.months_remaining <= 12
            ) + player.debt
            long_term_debt = max(0.0, player.total_debt() - current_debt)
            book_equity = player.book_equity()
            retained_earnings = book_equity - player.paid_in_capital + player.treasury_stock
            rows = [
                ('ASSETS', None, 'section'),
                ('Cash and cash equivalents', player.cash, 'normal'),
                ('Gross utility plant', player.gross_utility_plant(), 'normal'),
                ('Accumulated depreciation', -player.accumulated_depreciation(), 'normal'),
                ('Net utility plant', player.net_utility_plant(), 'total'),
                ('Construction work in progress', player.construction_work_in_progress(), 'normal'),
                ('Total assets', player.total_asset_value(), 'grand'),
                ('LIABILITIES', None, 'section'),
                ('Current portion of debt', current_debt, 'normal'),
                ('Long-term debt', long_term_debt, 'normal'),
                ('Total debt', player.total_debt(), 'total'),
                ('SHAREHOLDERS’ EQUITY', None, 'section'),
                ('Paid-in capital', player.paid_in_capital, 'normal'),
                ('Treasury stock', -player.treasury_stock, 'normal'),
                ('Retained earnings', retained_earnings, 'normal'),
                ('Total shareholders’ equity', book_equity, 'total'),
                ('Liabilities and equity', player.total_debt() + book_equity, 'grand'),
            ]
        else:
            title = "STATEMENT OF CASH FLOWS"
            closed = financials.has_closed_month
            subtitle = ("Latest closed month — indirect method" if closed else
                        "Opening balances — advance one month for cash-flow activity")
            reported_net_income = financials.net_profit if closed else 0.0
            reported_depreciation = financials.depreciation_expense if closed else 0.0
            reported_unusual = financials.unusual_gain_loss if closed else 0.0
            rows = [
                ('OPERATING ACTIVITIES', None, 'section'),
                ('Net income', reported_net_income, 'normal'),
                ('Depreciation added back', reported_depreciation, 'normal'),
                ('Gains / losses removed', -reported_unusual, 'normal'),
                ('Net cash from operations', financials.net_cash_from_operations, 'total'),
                ('INVESTING ACTIVITIES', None, 'section'),
                ('Capital expenditures', -financials.capital_expenditures, 'normal'),
                ('Asset retirement proceeds', financials.asset_sale_proceeds, 'normal'),
                ('Net cash from investing', financials.net_cash_from_investing, 'total'),
                ('FINANCING ACTIVITIES', None, 'section'),
                ('Debt issued', financials.debt_issuance, 'normal'),
                ('Debt repaid or repurchased', -financials.debt_repayments, 'normal'),
                ('Stock issued', financials.stock_issuance, 'normal'),
                ('Stock repurchased', -financials.stock_buybacks, 'normal'),
                ('Dividends paid', -financials.dividend_payments, 'normal'),
                ('Net cash from financing', financials.net_cash_from_financing, 'total'),
                ('Other / reconciliation', financials.cash_reconciliation_adjustment, 'normal'),
                ('Net change in cash', financials.net_change_in_cash, 'grand'),
                ('Beginning cash', financials.beginning_cash, 'normal'),
                ('Ending cash', financials.ending_cash, 'grand'),
            ]

        window = tk.Toplevel(self.root)
        window.title(title.title())
        window.configure(bg=self.COLORS['background'])
        window.geometry("1100x760" if statement_type in ('balance', 'income') else "760x760")
        window.minsize(620, 650)
        window.transient(self.root)
        window.grid_columnconfigure(0, weight=1)
        window.grid_rowconfigure(1, weight=1)

        heading = tk.Frame(window, bg=self.COLORS['background'], padx=22, pady=16)
        heading.grid(row=0, column=0, sticky='ew')
        tk.Label(heading, text=title, bg=self.COLORS['background'],
                 fg=self.COLORS['text'], font=('Helvetica', 18, 'bold')).pack(anchor='w')
        subtitle_label = tk.Label(
            heading, text=f"{subtitle}  •  Hover over a line item for its definition",
            bg=self.COLORS['background'], fg=self.COLORS['muted'],
            font=('Helvetica', 9), wraplength=950, justify='left'
        )
        subtitle_label.pack(anchor='w')
        self._statement_period_buttons(heading, window, statement_type)
        heading.bind('<Configure>', lambda event: subtitle_label.configure(
            wraplength=max(280, event.width - 44)))

        statement_parent = window
        if statement_type in ('balance', 'income'):
            notebook = ttk.Notebook(window, style='Utility.TNotebook')
            notebook.grid(row=1, column=0, sticky='nsew', padx=22)
            statement_parent = tk.Frame(notebook, bg=self.COLORS['panel'])
            notebook.add(statement_parent, text='Balance sheet' if statement_type == 'balance'
                         else 'Income statement')
            asset_tab = tk.Frame(notebook, bg=self.COLORS['panel'])
            notebook.add(asset_tab, text='Plant details' if statement_type == 'balance'
                         else 'Operating costs by plant')
            if statement_type == 'balance':
                self._populate_plant_register(asset_tab)
            else:
                self._populate_operating_costs(asset_tab)

        # Scroll all statements so the full report remains reachable on small screens.
        report_frame = tk.Frame(statement_parent, bg=self.COLORS['panel'])
        if statement_type in ('balance', 'income'):
            report_frame.pack(fill='both', expand=True)
        else:
            report_frame.grid(row=1, column=0, sticky='nsew', padx=22)
        report_frame.grid_columnconfigure(0, weight=1)
        report_frame.grid_rowconfigure(0, weight=1)
        report_canvas = tk.Canvas(report_frame, bg=self.COLORS['panel'], highlightthickness=0)
        report_canvas.grid(row=0, column=0, sticky='nsew')
        report_scroll = ttk.Scrollbar(report_frame, orient='vertical', command=report_canvas.yview)
        report_scroll.grid(row=0, column=1, sticky='ns')
        report_canvas.configure(yscrollcommand=report_scroll.set)
        statement = tk.Frame(
            report_canvas, bg=self.COLORS['panel'], padx=18, pady=12,
            highlightthickness=1, highlightbackground=self.COLORS['line']
        )
        report_item = report_canvas.create_window(0, 0, window=statement, anchor='nw')
        statement.bind('<Configure>', lambda _event: report_canvas.configure(
            scrollregion=report_canvas.bbox('all')))
        report_canvas.bind('<Configure>', lambda event: report_canvas.itemconfigure(
            report_item, width=event.width))
        statement.grid_columnconfigure(0, weight=1)

        row_number = 0
        for label, value, style in rows:
            if style == 'section':
                tk.Label(
                    statement, text=label, bg=self.COLORS['panel'],
                    fg=self.COLORS['muted'], font=('Helvetica', 8, 'bold')
                ).grid(row=row_number, column=0, columnspan=2, sticky='w',
                       pady=(9 if row_number else 0, 3))
                row_number += 1
                continue

            font = ('Helvetica', 10, 'bold' if style in ('total', 'grand') else 'normal')
            foreground = self.COLORS['cyan'] if style == 'grand' else self.COLORS['text']
            label_widget = tk.Label(
                statement, text=label, bg=self.COLORS['panel'], fg=foreground,
                font=font, cursor='question_arrow'
            )
            label_widget.grid(row=row_number, column=0, sticky='w', pady=3)
            value_widget = tk.Label(
                statement,
                text=value if isinstance(value, str) else compact_money(value),
                bg=self.COLORS['panel'],
                fg=foreground, font=font, cursor='question_arrow'
            )
            value_widget.grid(row=row_number, column=1, sticky='e', pady=3)
            definition = STATEMENT_DEFINITIONS.get(label, '')
            HoverTooltip(label_widget, definition, self.COLORS)
            HoverTooltip(value_widget, definition, self.COLORS)
            if style in ('total', 'grand'):
                divider = tk.Frame(statement, bg=self.COLORS['line'], height=1)
                divider.grid(row=row_number + 1, column=0, columnspan=2,
                             sticky='ew', pady=(1, 2))
                row_number += 1
            row_number += 1

        footer = tk.Frame(window, bg=self.COLORS['background'], padx=22, pady=12)
        footer.grid(row=2, column=0, sticky='ew')
        self._clickable_label(
            footer, "CLOSE", window.destroy, self.COLORS['panel_alt']
        ).pack(side='right')

    def _statement_period_buttons(self, parent, window, statement_type):
        controls = tk.Frame(parent, bg=self.COLORS['background'])
        controls.pack(anchor='w', pady=(8, 0))
        for label, frequency in (('LATEST MONTH', 'monthly'), ('LAST 4 QUARTERS', 'quarterly'),
                                 ('LAST 4 FULL YEARS', 'annual')):
            self._clickable_label(controls, label,
                lambda mode=frequency: (window.destroy(), self.open_statement_window(statement_type, mode)),
                self.COLORS['panel_alt']).pack(side='left', padx=(0, 7))

    def open_period_statement(self, statement_type, frequency):
        reports = utility_reports.periods(self.session.financials, self.session.game_state, frequency)
        kind = 'income' if statement_type == 'income' else 'balance' if statement_type == 'balance' else 'cash_flow'
        lines = {'income': utility_reports.INCOME_LINES, 'balance': utility_reports.BALANCE_LINES,
                 'cash_flow': utility_reports.CASH_LINES}[kind]
        title = {'income': 'Income Statement', 'balance': 'Balance Sheet', 'cash_flow': 'Cash Flow'}[kind]
        window = tk.Toplevel(self.root)
        window.title(f'{title} — {frequency.title()}')
        window.configure(bg=self.COLORS['background'])
        window.geometry('1180x760')
        window.minsize(800, 600)
        window.grid_columnconfigure(0, weight=1)
        window.grid_rowconfigure(1, weight=1)
        heading = tk.Frame(window, bg=self.COLORS['background'], padx=18, pady=14)
        heading.grid(row=0, column=0, sticky='ew')
        tk.Label(heading, text=f'{title.upper()} — {frequency.upper()}',
                 bg=self.COLORS['background'], fg=self.COLORS['text'],
                 font=('Helvetica', 17, 'bold')).pack(anchor='w')
        tk.Label(heading, text='Complete calendar periods only. Balance sheets show period-end values; '
                 'income and cash flows sum the months.', bg=self.COLORS['background'],
                 fg=self.COLORS['muted'], wraplength=1050, justify='left').pack(anchor='w')
        self._statement_period_buttons(heading, window, statement_type)
        frame = tk.Frame(window, bg=self.COLORS['panel'])
        frame.grid(row=1, column=0, sticky='nsew', padx=18)
        frame.grid_rowconfigure(0, weight=1)
        frame.grid_columnconfigure(0, weight=1)
        canvas = tk.Canvas(frame, bg=self.COLORS['panel'], highlightthickness=0)
        canvas.grid(row=0, column=0, sticky='nsew')
        vertical = ttk.Scrollbar(frame, orient='vertical', command=canvas.yview)
        vertical.grid(row=0, column=1, sticky='ns')
        horizontal = ttk.Scrollbar(frame, orient='horizontal', command=canvas.xview)
        horizontal.grid(row=1, column=0, sticky='ew')
        canvas.configure(yscrollcommand=vertical.set, xscrollcommand=horizontal.set)
        table = tk.Frame(canvas, bg=self.COLORS['panel'], padx=12, pady=12)
        canvas.create_window(0, 0, window=table, anchor='nw')
        table.bind('<Configure>', lambda _event: canvas.configure(scrollregion=canvas.bbox('all')))
        for column, report in enumerate(reports, 1):
            tk.Label(table, text=report['label'], bg=self.COLORS['panel'], fg=self.COLORS['cyan'],
                     font=('Helvetica', 10, 'bold'), padx=12, pady=8).grid(row=0, column=column)
        for row, (label, key, sign) in enumerate(lines, 1):
            term = tk.Label(table, text=label, bg=self.COLORS['panel'], fg=self.COLORS['text'],
                            font=('Helvetica', 10), pady=5, cursor='question_arrow')
            term.grid(row=row, column=0, sticky='w')
            HoverTooltip(term, STATEMENT_DEFINITIONS.get(label, label), self.COLORS)
            for column, report in enumerate(reports, 1):
                value = report[kind][key] * sign
                text = (f'${value:,.3f}' if key == 'eps' else f'{value:,.0f}' if key == 'weighted_shares'
                        else compact_money(value))
                tk.Label(table, text=text, bg=self.COLORS['panel'], fg=self.COLORS['text'],
                         font=('Helvetica', 10), padx=12, pady=5).grid(row=row, column=column, sticky='e')
        tk.Label(window, text='(est.) = backfilled pre-game/opening estimates, not recorded gameplay. '
                 '(mixed) = estimates plus actual closes. Backfill assumes seasonal operations, '
                 '35% earnings distributions and reinvestment of remaining cash. EPS uses '
                 'weighted-average shares. Negative-numbered years are before your appointment.',
                 bg=self.COLORS['background'], fg=self.COLORS['muted'], wraplength=1080,
                 justify='left', padx=18, pady=12).grid(row=2, column=0, sticky='ew')

    def _populate_operating_costs(self, parent):
        financials = self.session.financials
        parent.grid_columnconfigure(0, weight=1)
        parent.grid_rowconfigure(1, weight=1)
        period = 'Latest month' if financials.has_closed_month else 'Opening monthly estimate'
        total = financials.cash_operating_expenses + financials.depreciation_expense
        summary_label = tk.Label(
            parent, text=f'{period}  •  Cash costs: ${financials.cash_operating_expenses:,.0f}'
            f'  •  Depreciation: ${financials.depreciation_expense:,.0f}'
            f'  •  Total operating expenses: ${total:,.0f}',
            bg=self.COLORS['panel'], fg=self.COLORS['text'], font=('Helvetica', 10, 'bold'),
            wraplength=950, justify='left', padx=10, pady=12
        )
        summary_label.grid(row=0, column=0, sticky='w')
        specs = (
            ('source', 'SOURCE', 140), ('units', 'UNITS', 55), ('energy', 'MWh', 100),
            ('fuel', 'FUEL / O&M / POWER', 150), ('carbon', 'CARBON TAX', 120),
            ('cash', 'CASH COST', 130), ('depreciation', 'DEPRECIATION', 130),
            ('total', 'TOTAL OP. EXPENSE', 150),
        )
        table = ttk.Treeview(parent, columns=[s[0] for s in specs], show='headings',
                             style='Utility.Treeview')
        for column, title, width in specs:
            table.heading(column, text=title)
            table.column(column, width=width, minwidth=width, stretch=False,
                         anchor='w' if column == 'source' else 'e')
        table.grid(row=1, column=0, sticky='nsew', padx=(10, 0))
        vertical = ttk.Scrollbar(parent, orient='vertical', command=table.yview)
        vertical.grid(row=1, column=1, sticky='ns')
        horizontal = ttk.Scrollbar(parent, orient='horizontal', command=table.xview)
        horizontal.grid(row=2, column=0, sticky='ew', padx=10)
        table.configure(yscrollcommand=vertical.set, xscrollcommand=horizontal.set)
        totals = dict.fromkeys(('fuel_om_power', 'carbon', 'cash_cost', 'depreciation'), 0.0)
        names = {key: value[0] for key, value in GUI_BUILD_INFO.items()}
        names.update(contract_imports='Contract imports', spot_imports='Spot imports')
        for row in financials.operating_cost_breakdown:
            for key in totals:
                totals[key] += row[key]
            table.insert('', 'end', values=(
                names[row['source']], row['units'] if row['units'] is not None else '—',
                f"{row['energy_mwh']:,.0f}", f"${row['fuel_om_power']:,.0f}",
                f"${row['carbon']:,.0f}", f"${row['cash_cost']:,.0f}",
                f"${row['depreciation']:,.0f}",
                f"${row['cash_cost'] + row['depreciation']:,.0f}",
            ))
        table.tag_configure('total', foreground=self.COLORS['cyan'])
        table.insert('', 'end', tags=('total',), values=(
            'TOTAL', '', '', *(f'${totals[key]:,.0f}' for key in totals),
            f"${totals['cash_cost'] + totals['depreciation']:,.0f}",
        ))
        note_label = tk.Label(
            parent, text='All values are monthly. Fuel/O&M uses actual dispatched output, '
            'including gas peakers. Imports are separate from owned plants. Battery MWh is '
            'discharged energy; charging costs remain with the generating source or purchased '
            'power (no separate cash battery O&M is modeled). Depreciation is noncash. '
            'Interest and income tax are not operating costs.',
            bg=self.COLORS['panel'], fg=self.COLORS['muted'], font=('Helvetica', 9),
            wraplength=950, justify='left', padx=10, pady=12
        )
        note_label.grid(row=3, column=0, sticky='w')
        parent.bind('<Configure>', lambda event: [label.configure(
            wraplength=max(280, event.width - 40)) for label in (summary_label, note_label)])

    def open_demand_forecast(self):
        forecast = self.session.grid.forecast_demand(self.session.player, self.session.game_state)
        window = tk.Toplevel(self.root)
        window.title('Demand forecast — 24 months')
        window.configure(bg=self.COLORS['background'])
        window.geometry('1000x760')
        window.minsize(800, 650)
        window.transient(self.root)
        window.grid_columnconfigure(0, weight=1)
        window.grid_rowconfigure(2, weight=1)
        peak = max(forecast, key=lambda row: row['expected'])
        shortfall = next((row for row in forecast if row['reserve_margin'] < 0), None)
        risk = (f"First potential shortfall: {shortfall['label']}" if shortfall else
                'Dependable supply covers the upper demand range throughout')
        heading_label = tk.Label(
            window, text=f"24-MONTH DEMAND FORECAST\n"
            f"Expected peak: {peak['expected']:,.0f} MW in {peak['label']}  •  {risk}",
            bg=self.COLORS['background'], fg=self.COLORS['text'],
            font=('Helvetica', 12, 'bold'), justify='left', wraplength=940, padx=20, pady=14
        )
        heading_label.grid(row=0, column=0, sticky='w')
        chart = tk.Canvas(window, height=240, bg=self.COLORS['panel'], highlightthickness=0)
        chart.grid(row=1, column=0, sticky='ew', padx=20)
        chart.bind('<Configure>', lambda _event: self._draw_demand_forecast(chart, forecast))
        table_frame = tk.Frame(window, bg=self.COLORS['background'])
        table_frame.grid(row=2, column=0, sticky='nsew', padx=20, pady=(12, 0))
        table_frame.grid_columnconfigure(0, weight=1)
        table_frame.grid_rowconfigure(0, weight=1)
        specs = (('period', 'MONTH', 90), ('expected', 'EXPECTED MW', 130),
                 ('low', 'LOW MW', 110), ('high', 'HIGH MW', 110),
                 ('supply', 'DEPENDABLE MW', 160), ('reserve', 'RESERVE VS. HIGH', 160))
        table = ttk.Treeview(table_frame, columns=[s[0] for s in specs], show='headings',
                             style='Utility.Treeview', height=8)
        for column, title, width in specs:
            table.heading(column, text=title)
            table.column(column, width=width, minwidth=75,
                         anchor='w' if column == 'period' else 'e')
        table.grid(row=0, column=0, sticky='nsew')
        scroll = ttk.Scrollbar(table_frame, orient='vertical', command=table.yview)
        scroll.grid(row=0, column=1, sticky='ns')
        table.configure(yscrollcommand=scroll.set)
        table.tag_configure('shortfall', foreground=self.COLORS['red'])
        table.tag_configure('thin', foreground=self.COLORS['amber'])
        for row in forecast:
            tag = 'shortfall' if row['reserve_margin'] < 0 else (
                'thin' if row['reserve_margin'] < 0.15 else '')
            table.insert('', 'end', tags=(tag,), values=(
                row['label'], *(f"{row[key]:,.0f}" for key in
                                ('expected', 'low', 'high', 'firm_supply')),
                f"{row['reserve_margin']:+.1%}",
            ))
        note_label = tk.Label(
            window, text='Demand includes seasonal patterns, normal 2% annual growth, and '
            'remaining effects of known demand events. The shaded ±10% range represents '
            'normal monthly variation, not a confidence interval; unforeseen events can exceed it. '
            'Dependable supply includes peakers, capacity credits for renewables/storage, '
            'scheduled construction completions, and next-month power contracts (imports minus '
            'exports). It assumes no new project delays or battery degradation. '
            'Amber: less than 15% reserve. Red: insufficient supply for high demand.',
            bg=self.COLORS['background'], fg=self.COLORS['muted'],
            font=('Helvetica', 9), wraplength=940, justify='left', padx=20, pady=12
        )
        note_label.grid(row=3, column=0, sticky='ew')
        def resize_notes(event):
            if event.widget is window:
                for label in (heading_label, note_label):
                    label.configure(wraplength=max(280, event.width - 50))
        window.bind('<Configure>', resize_notes)
        self._clickable_label(window, 'CLOSE', window.destroy, self.COLORS['panel_alt']).grid(
            row=4, column=0, sticky='e', padx=20, pady=(0, 12))

    def _draw_demand_forecast(self, canvas, forecast):
        canvas.delete('all')
        width, height = canvas.winfo_width(), canvas.winfo_height()
        if width < 100 or not forecast:
            return
        left, top, right, bottom = 65, 35, width - 25, height - 30
        low = min(0, min(row['firm_supply'] for row in forecast))
        high = max(max(row['high'], row['firm_supply']) for row in forecast) * 1.1
        span = max(high - low, 1)
        x = lambda i: left + i * (right - left) / max(len(forecast) - 1, 1)
        y = lambda value: bottom - (value - low) / span * (bottom - top)
        for tick in range(5):
            value = low + span * tick / 4
            yy = y(value)
            canvas.create_line(left, yy, right, yy, fill=self.COLORS['line'])
            canvas.create_text(left - 8, yy, text=f'{value:,.0f}', anchor='e',
                               fill=self.COLORS['muted'], font=('Helvetica', 8))
        band = [(x(i), y(row['high'])) for i, row in enumerate(forecast)]
        band += [(x(i), y(forecast[i]['low'])) for i in reversed(range(len(forecast)))]
        canvas.create_polygon(*[v for point in band for v in point], fill='#1b3a59', outline='')
        for key, color in (('expected', 'cyan'), ('firm_supply', 'green')):
            points = [v for i, row in enumerate(forecast) for v in (x(i), y(row[key]))]
            canvas.create_line(*points, fill=self.COLORS[color], width=2)
        for i in range(0, len(forecast), 3):
            canvas.create_text(x(i), bottom + 16, text=forecast[i]['label'],
                               fill=self.COLORS['muted'], font=('Helvetica', 8))
        for offset, label, color in ((0, 'Demand (MW) ±10%', 'cyan'),
                                     (210, 'Dependable supply', 'green')):
            canvas.create_text(left + offset, 16, text=label, anchor='w',
                               fill=self.COLORS[color], font=('Helvetica', 9, 'bold'))

    def _populate_plant_register(self, parent):
        player = self.session.player
        parent.grid_columnconfigure(0, weight=1)
        parent.grid_rowconfigure(1, weight=1)
        totals = (f"{len(player.plant_assets)} units in service     "
                  f"Cost: ${player.gross_utility_plant():,.0f}     "
                  f"Accumulated depreciation: ${player.accumulated_depreciation():,.0f}     "
                  f"Net plant: ${player.net_utility_plant():,.0f}")
        tk.Label(parent, text=totals, bg=self.COLORS['panel'], fg=self.COLORS['text'],
                 font=('Helvetica', 10, 'bold'), padx=10, pady=12,
                 wraplength=980, justify='left').grid(row=0, column=0, sticky='w')
        columns = ('id', 'type', 'mw', 'age', 'life', 'cost', 'monthly', 'accumulated', 'net')
        table = ttk.Treeview(parent, columns=columns, show='headings', style='Utility.Treeview')
        specs = (
            ('id', 'UNIT', 65), ('type', 'TYPE', 85), ('mw', 'MW', 60),
            ('age', 'AGE (MO)', 85), ('life', 'LIFE (YR)', 80),
            ('cost', 'ORIGINAL COST', 155), ('monthly', 'MONTHLY DEP.', 135),
            ('accumulated', 'TOTAL DEP.', 155), ('net', 'NET BOOK VALUE', 155),
        )
        for column, title, width in specs:
            table.heading(column, text=title)
            table.column(column, width=width, minwidth=width, stretch=False,
                         anchor='w' if column in ('id', 'type') else 'e')
        table.grid(row=1, column=0, sticky='nsew', padx=(10, 0))
        vertical = ttk.Scrollbar(parent, orient='vertical', command=table.yview)
        vertical.grid(row=1, column=1, sticky='ns')
        horizontal = ttk.Scrollbar(parent, orient='horizontal', command=table.xview)
        horizontal.grid(row=2, column=0, sticky='ew', padx=10)
        table.configure(yscrollcommand=vertical.set, xscrollcommand=horizontal.set)
        for asset in player.plant_assets:
            table.insert('', 'end', values=(
                f'#{asset.asset_id:03d}', GUI_BUILD_INFO[asset.plant_type][0],
                f'{PLANT_NAMEPLATE_CAPACITY[asset.plant_type]:,}', asset.months_in_service,
                ASSET_USEFUL_LIFE_YEARS[asset.plant_type], f'${asset.original_cost:,.0f}',
                f'${asset.monthly_depreciation:,.0f}', f'${asset.accumulated_depreciation:,.0f}',
                f'${asset.net_book_value:,.0f}',
            ))
        if not player.plant_assets:
            table.insert('', 'end', values=('', 'No units in service'))
        note = tk.Label(
            parent, text='Monthly dep. is the next scheduled straight-line charge. Age includes '
            'pre-game service: inherited plants start 20–65% through their useful lives, with '
            'that depreciation already recorded. Newly built plants start at age zero. '
            'Projects under construction do not '
            'depreciate until completion. Retiring units removes the newest units of that type first.',
            bg=self.COLORS['panel'], fg=self.COLORS['muted'], font=('Helvetica', 9),
            justify='left', wraplength=950, padx=10, pady=12
        )
        note.grid(row=3, column=0, sticky='w')

    def _buyback_selected_bond(self, window, summary, ladder):
        selection = ladder.selection()
        if not selection:
            messagebox.showinfo("Select a bond", "Choose a bond in the ladder first.",
                                parent=window)
            return
        bond = ladder.bond_lookup.get(selection[0])
        if bond is None:
            return
        settlement, market_yield, clean_value = self.session.player.bond_buyback_quote(
            bond, self.session.economy, self.session.credit
        )
        difference = clean_value - bond.principal
        relation = "premium" if difference >= 0 else "discount"
        confirmed = messagebox.askyesno(
            "Confirm bond buyback",
            f"Retire {compact_money(bond.principal)} of debt?\n\n"
            f"Coupon: {bond.annual_rate * 100:.2f}%\n"
            f"Current market yield: {market_yield * 100:.2f}%\n"
            f"Market adjustment: {compact_money(abs(difference))} {relation} to par\n"
            f"Settlement including 0.5% transaction cost: {compact_money(settlement)}",
            parent=window
        )
        if not confirmed:
            return
        self._run_action(lambda: self.session.player.buy_back_bond(
            bond, self.session.economy, self.session.credit
        ))
        self._populate_financial_menu(window, summary, ladder)

    def _prompt_borrowing_amount(self, title, description):
        player = self.session.player
        remaining = player.remaining_borrowing_capacity()
        if remaining <= 0:
            messagebox.showinfo(
                "Monthly borrowing limit reached",
                "You have used this month's borrowing allowance. It renews after "
                "the month closes. Bond repayments do not restore the allowance.",
                parent=self.root
            )
            return None
        return simpledialog.askfloat(
            title,
            f"{description}\n\n"
            f"Remaining this month: ${remaining:,.2f}\n"
            f"Monthly cap: {MONTHLY_BORROWING_ASSET_FRACTION:.0%} of plant and "
            "construction book value at month start.\n"
            "Bonds and emergency loans share this allowance.",
            minvalue=0.000001, maxvalue=remaining / 1_000_000, parent=self.root
        )

    def issue_bond(self):
        term = simpledialog.askstring(
            "Issue bond", "Term (6mo, 1yr, 2yr, 5yr, 10yr, or 20yr):",
            parent=self.root
        )
        if term is None:
            return
        term = term.strip().lower()
        if term not in BOND_TERMS:
            messagebox.showerror("Invalid term", "Choose 6mo, 1yr, 2yr, 5yr, 10yr, or 20yr.",
                                 parent=self.root)
            return
        amount = self._prompt_borrowing_amount("Issue bond", "Principal ($ millions):")
        if amount is not None:
            self._run_action(lambda: self.session.player.issue_bond(
                amount * 1_000_000, self.session.economy, term, self.session.credit
            ))

    def request_rate_case(self):
        percent = simpledialog.askfloat(
            "Request rate increase",
            "Retail tariffs already track inflation automatically.\n"
            "Requested additional increase (%):", minvalue=0.1,
            maxvalue=50, parent=self.root
        )
        if percent is not None:
            self._run_action(lambda: self.session.regulator.request_increase(
                self.session.player, self.session.financials, self.session.economy,
                self.session.game_state.turn, percent / 100
            ))

    def trade_power(self):
        player = self.session.player
        pending = player.pending_wholesale_commitment_mw
        direction = simpledialog.askstring(
            "Recurring wholesale power",
            f"Active: {power_contract_description(player.wholesale_commitment_mw)}\n"
            + (f"Scheduled: {power_contract_description(pending)}\n" if pending is not None else '')
            + "Type BUY or SELL. This sets the TOTAL recurring amount from next month.",
            parent=self.root
        )
        if direction is None:
            return
        direction = direction.strip().lower()
        if direction not in ('buy', 'sell'):
            messagebox.showerror("Invalid trade", "Enter BUY or SELL.", parent=self.root)
            return
        market = wholesale_market_price(self.session.economy)
        factor = CONTRACT_BUY_FACTOR if direction == 'buy' else CONTRACT_SELL_FACTOR
        mw = simpledialog.askfloat(
            "Recurring wholesale power",
            f"{direction.upper()} how many MW each month? Enter 0 to cancel.\n"
            f"Current estimate: ${market * factor:.2f}/MWh × {HOURS_PER_MONTH:.0f} hours/month.\n"
            "Prices change with the market. Exports use generation; any shortage is\n"
            "bought on the spot market at a premium. No cash moves until next month.",
            minvalue=0, parent=self.root
        )
        if mw is not None:
            self._run_action(lambda: self.session.player.wholesale_trade(
                mw, direction, self.session.economy
            ))

    def set_dividend(self):
        current = self.session.player.annual_dividend_per_share
        dividend = simpledialog.askfloat(
            "Set dividend", f"New annual dividend per share (current ${current:.3f}):",
            minvalue=0, parent=self.root
        )
        if dividend is not None:
            self._run_action(lambda: self.session.player.set_dividend(dividend))
            if self.session.player.shareholder_happiness < 35 and not self.session.player.fired:
                messagebox.showwarning('Shareholders unhappy',
                                       self.session.player.shareholder_status(), parent=self.root)

    def toggle_battery_mode(self):
        player = self.session.player
        player.battery_dispatch_mode = (
            'before_gas' if player.battery_dispatch_mode == 'after_gas' else 'after_gas'
        )
        readable = "battery before gas" if player.battery_dispatch_mode == 'before_gas' else "gas before battery"
        self._append_log(f"Dispatch priority changed to {readable}.")
        self.refresh()

    def emergency_loan(self):
        amount = self._prompt_borrowing_amount(
            "Emergency loan", "Loan amount ($ millions, 18% APR):"
        )
        if amount is None:
            return
        if messagebox.askyesno(
            "Confirm emergency financing",
            f"Borrow {compact_money(amount * 1_000_000)} at 18% APR for one year?",
            parent=self.root
        ):
            self._run_action(lambda: self.session.player.emergency_loan(amount * 1_000_000))

    def advance_month(self):
        if self.session.game_over:
            return
        if self.session.player.cash < 0:
            messagebox.showwarning(
                "Negative cash",
                "Raise cash through financing or asset retirement before advancing.",
                parent=self.root
            )
            return
        result = self._run_action(self.session.advance_month)
        self._record_history()
        self.refresh()
        state = self.session.game_state
        grid = self.session.grid
        self._append_log(
            f"Month closed: {grid.total_generation:,.0f} MW produced, "
            f"{grid.available_for_customers:,.0f} MW available before spot balancing against "
            f"{grid.total_demand:,.0f} MW demand; net income "
            f"{compact_money(self.session.last_monthly_profit)}."
        )
        event_messages = [
            state.last_gas_event_msg, state.last_demand_event_msg,
            state.last_carbon_event_msg,
        ]
        for event in event_messages:
            if event:
                self._append_log(event)
        if result == 'FIRED':
            messagebox.showerror(
                "You have been fired",
                'Shareholder happiness fell to 10/100 or below. The board has replaced you.',
                parent=self.root
            )
        elif result == 'BANKRUPT':
            messagebox.showerror("Game over", "Your utility has gone bankrupt.", parent=self.root)
        elif result == 'COMPLETE':
            messagebox.showinfo("Planning complete", "You reached the end of the simulation.",
                                parent=self.root)
        elif self.session.player.shareholder_happiness < 25:
            messagebox.showwarning('Shareholders unhappy',
                                   self.session.player.shareholder_status(), parent=self.root)

    def show_help(self):
        messagebox.showinfo(
            "How to play Gridline",
            "Keep the grid reliable and the company solvent. Build capacity before demand "
            "overtakes supply, maintain at least a 15% reserve margin, and watch fuel prices, "
            "interest rates, debt, carbon policy, and construction lead times. Hydro gets "
            "more expensive as the best river sites are used.\n\n"
            "Inflation compounds monthly into the price index (opening = 100). New plants, "
            "fuel/O&M, wholesale buys and sales, retail tariffs, carbon charges, salvage, "
            "and teardown all follow it. Gas shocks and carbon-policy escalation apply on top. "
            "Rate cases request increases above automatic inflation adjustments. Prepaid "
            "construction stays fixed; new overrun work uses current prices. Historical plant "
            "costs/depreciation, cash, existing bond principal/coupons, and declared dividends "
            "are not automatically marked up.\n\n"
            "You may take as many management actions as you like before choosing Advance Month. "
            "Use Financial to review dividends, open the three accounting statements, and buy "
            "bonds back at their current market value. Hover over statement terms for definitions. "
            f"Borrowing is capped at {MONTHLY_BORROWING_ASSET_FRACTION:.0%} of plant and "
            "construction book value each month, including emergency loans. Credit uses "
            "net debt (bonds minus cash) relative to book equity and trailing-12-month EBITDA "
            "coverage of current annual interest (opening earnings estimates roll off monthly). "
            "AAA requires a 95/100 score plus at least 12 strong months with net leverage ≤0.35× "
            "and coverage ≥6×. D requires three consecutive negative-cash closes with debt "
            "outstanding; three nonnegative-cash closes restore CCC, then recovery remains slow. "
            'Shareholder happiness replaces the old six-month rule: 3%+ dividends help, '
            '2% or less hurts, no raises slowly erode confidence, and every cut costs 50 points. '
            'At 10/100 or less you are fired. Stock trades share a 4.9% annual share/value cap. '
            'Repeated issuance hurts happiness; sustained buybacks help without a stopping penalty. '
            'Save/Load preserves all state and random events in versioned JSON files. '
            'Statements offer the last four complete calendar quarters or years, with estimated '
            'pre-game data labeled. Solar/wind real build costs decline over the first ten years. '
            "Power trades are recurring MW commitments, replaced starting next month when "
            "you change them; enter 0 to cancel. Sold power leaves your grid. "
            "Balance sheet → Plant details lists every unit's cost and depreciation. "
            "Income statement → Operating costs by plant breaks out fuel/O&M, carbon, "
            "purchased power, and depreciation. The income statement also shows TTM EPS: "
            "12 months of net income per share, with pre-game estimates labeled until replaced. "
            "Ongoing stock valuation weights earnings 70%, book value 20%, and dividends 10%. "
            "Forecast shows 24 months of seasonal demand and planned dependable supply. "
            "The animated line is green when supply covers demand and red during a shortfall.\n\n"
            "Keyboard: Enter advances the month • F1 opens this help.",
            parent=self.root
        )

    def run(self):
        self.root.mainloop()


def launch_graphical_game(num_turns=1000):
    if tk is None:
        print("The graphical interface is unavailable because Tkinter is not installed. "
              "Run with --cli to use the terminal version.")
        return False
    startup = io.StringIO()
    try:
        with contextlib.redirect_stdout(startup):
            session = UtilityGameSession(max_turns=num_turns)
        app = UtilityGameGUI(session, startup.getvalue())
    except tk.TclError as exc:
        print(f"The graphical interface could not open ({exc}). Run with --cli instead.")
        return False
    app.run()
    return True


def main(argv=None):
    parser = argparse.ArgumentParser(description="Utility company management game")
    parser.add_argument('--cli', action='store_true', help='use the original terminal interface')
    parser.add_argument('--turns', type=int, default=1000, help='maximum months to play')
    parser.add_argument('--seed', type=int, help='fixed random seed for a repeatable game')
    args = parser.parse_args(argv)
    if args.seed is not None:
        random.seed(args.seed)
    if args.turns < 1:
        parser.error('--turns must be at least 1')
    if args.cli:
        run_game(args.turns)
        return 0
    return 0 if launch_graphical_game(args.turns) else 1


if __name__ == "__main__":
    raise SystemExit(main())
