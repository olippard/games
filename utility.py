import argparse
import contextlib
import io
import math
import random

try:
    import tkinter as tk
    from tkinter import messagebox, simpledialog, ttk
except ImportError:  # The simulation and CLI can still run without Tk.
    tk = None
    messagebox = simpledialog = ttk = None

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

# Costs and Revenues ($/MWh)
COAL_COST_PER_MWH = 30
NATURAL_GAS_COST_PER_MWH = 45  # pricier fuel, but faster/cleaner to run
NUCLEAR_COST_PER_MWH = 15
SOLAR_COST_PER_MWH = 5
WIND_COST_PER_MWH = 8
HYDRO_COST_PER_MWH = 10
HYDRO_OUTPUT_FACTOR = 0.75
BATTERY_DEGRADATION_PER_CYCLE = 0.01
WHOLESALE_PRICE_PER_MWH = 40
RETAIL_PRICE_PER_MWH = 60

# Natural gas price dynamics
NATURAL_GAS_BASE_COST_PER_MWH = 45   # long-run "normal" gas price
NATURAL_GAS_MIN_COST_PER_MWH = 20    # price floor
NATURAL_GAS_MAX_COST_PER_MWH = 140   # price ceiling (severe crisis)
GAS_PRICE_MEAN_REVERSION = 0.15      # how fast price drifts back to base each month
GAS_PRICE_MONTHLY_VOLATILITY = 0.04  # baseline random monthly wiggle (fraction)

# Battery operation
BATTERY_ROUND_TRIP_EFFICIENCY = 0.90  # 90% of stored energy is recoverable
BATTERY_MIN_CAPACITY_FRACTION = 0.20  # battery is "dead" below 20% of original max

# Construction Costs
COAL_CONSTRUCTION_COST = 3_000_000_000       # ~$3B for 600 MW
NATURAL_GAS_CONSTRUCTION_COST = 1_000_000_000 # ~$1B for 500 MW CCGT
NUCLEAR_CONSTRUCTION_COST = 9_000_000_000     # ~$7,500/kW for a 1,200 MW unit
SOLAR_CONSTRUCTION_COST = 300_000_000         # ~$300M for 200 MW
WIND_CONSTRUCTION_COST = 250_000_000          # ~$250M for 150 MW
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

# Add near the equity constants
STOCK_SMOOTHING = 0.25        # how fast price moves toward fair value (0=frozen, 1=instant)
STOCK_MONTHLY_NOISE = 0.02    # +/- 2% random market wiggle
DIVIDEND_WEIGHT = 0.45        # how much dividend value counts vs. earnings/book
REQUIRED_RETURN_PREMIUM = 0.03  # equity risk premium over the risk-free rate

# Debt: real electric utilities average a D/E ratio of ~2.35 (range 1.3-2.97)
MIN_DE_RATIO = 1.3
MAX_DE_RATIO = 2.97
STARTING_DEBT_MULTIPLIER = 2.0
LEGACY_BOND_RATE_RANGE = (0.03, 0.07)  # historical rates the old bonds were issued at
BOND_BUYBACK_TRANSACTION_COST = 0.005  # dealer spread / execution cost

# Credit trouble should arrive quickly but take much longer to repair. These
# are monthly weights applied to the newest financial result.
CREDIT_UPGRADE_SMOOTHING = 0.04
CREDIT_DOWNGRADE_SMOOTHING = 0.30

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
        self.update()

    def update(self):
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

    def display(self):
        mood = ("BOOM" if self.sentiment > 0.4 else
                "RECESSION" if self.sentiment < -0.4 else "STABLE")
        print("\n--- Economy ---")
        print(f"Cycle: {mood} (sentiment {self.sentiment:+.2f})")
        print(f"Inflation: {self.inflation * 100:.2f}%   "
              f"Interest Rate: {self.interest_rate * 100:.2f}%   "
              f"Market P/E: {self.market_pe:.1f}")

    # Economy
    def bond_rate(self, term_years, credit_spread):
        term_premium = 0.004 * math.log1p(term_years)
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
    def __init__(self):
        self.current_retail_price = RETAIL_PRICE_PER_MWH
        self.last_request_turn = -999
        self.recent_requests = 0

    def request_increase(self, player_state, financials, economy, current_turn, pct):
        """Player asks to raise retail rates by pct (e.g., 0.05 = 5%)."""
        # Estimate current net margin.
        rev = max(financials.revenue, 1)
        margin = financials.net_profit / rev

        # Base approval probability shrinks as margin nears the cap.
        headroom = max(0.0, FAIRNESS_MARGIN_CAP - margin)
        base_prob = min(0.9, headroom / FAIRNESS_MARGIN_CAP)

        # Inflation justification: easier to raise rates when inflation is high.
        base_prob += min(0.2, economy.inflation * 2)

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
    ('AAA', 0.005), ('AA', 0.010), ('A', 0.015), ('BBB', 0.025),
    ('BB', 0.045), ('B', 0.070), ('CCC', 0.110), ('D', None),  # D = default, no lending
]

class CreditRating:
    def __init__(self):
        self.rating = 'B'
        # Look up B's spread from the ratings table.
        self.spread = dict(CREDIT_RATINGS)['B']
        self.can_borrow = True
        self._score = 2.0        # a score consistent with a 'B' rating
        self._forced_start = True  # pin the first evaluation to 'B'

    def update(self, player_state, financials):
        if self._forced_start:
            # Game-start: keep the rating at 'B' regardless of metrics.
            self._forced_start = False
            self.rating = 'B'
            self.spread = dict(CREDIT_RATINGS)['B']
            self.can_borrow = True
            return

        equity = max(player_state.company_value, 1)
        de = player_state.total_debt() / equity
        annual_interest = sum(b.monthly_interest() for b in player_state.bonds) * 12
        annual_interest = max(annual_interest, 1)
        operating_profit = financials.revenue - financials.operational_costs
        coverage = operating_profit / annual_interest
        score = 10
        if de > 1.5: score -= (de - 1.5) * 2.5
        if de > 3.0: score -= 2
        if coverage < 3: score -= min(3, (3 - coverage) * 0.8)
        if coverage < 0: score -= 1
        if player_state.cash < 0: score -= 2

        smoothing = (CREDIT_UPGRADE_SMOOTHING
                     if score > self._score else CREDIT_DOWNGRADE_SMOOTHING)
        self._score += (score - self._score) * smoothing

        idx = min(len(CREDIT_RATINGS) - 1, max(0, int(round(len(CREDIT_RATINGS) - 1 - self._score))))
        if self._score >= 9: idx = 0
        elif self._score <= 0: idx = len(CREDIT_RATINGS) - 1
        self.rating, self.spread = CREDIT_RATINGS[idx]
        self.can_borrow = self.spread is not None
        

    def display(self):
        spread_txt = f"{self.spread*100:.1f}% spread" if self.can_borrow else "NO LENDERS"
        print(f"Credit Rating: {self.rating} ({spread_txt})")


class GameState:
    def __init__(self):
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
        self.natural_gas_price = NATURAL_GAS_BASE_COST_PER_MWH
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
        self.carbon_tax = 0.0
        self._carbon_tax_start_turn = random.randint(*CARBON_TAX_START_MONTH_RANGE)
        self._carbon_tax_initial = random.uniform(*CARBON_TAX_INITIAL_RANGE)
        self._carbon_tax_annual_growth = random.uniform(*CARBON_TAX_ANNUAL_GROWTH_RANGE)
        self.last_carbon_event_msg = None
        

    def _summer_factor(self):
        month_angle = 2 * math.pi * (self.current_month - 1) / 12
        return math.cos(month_angle - 2 * math.pi * 6 / 12)

    def update_seasonal_conditions(self):
        summer = self._summer_factor()

        lat_frac = self.latitude / 65.0
        solar_amplitude = 0.35 * lat_frac
        solar_baseline = 0.65 - 0.25 * lat_frac
        self.region_sunlight_level = max(0.05, min(1.0,
            solar_baseline + solar_amplitude * summer + random.uniform(-0.05, 0.05)))

        self.region_wind_level = max(0.05, min(1.0,
            0.5 - 0.2 * summer + random.uniform(-0.1, 0.1)))

        if self.climate == "hot":
            self.demand_multiplier = 1.0 + 0.35 * summer
        elif self.climate == "cold":
            self.demand_multiplier = 1.0 - 0.35 * summer
        else:
            self.demand_multiplier = 1.0 + 0.20 * abs(summer)

    def update_gas_price(self):
        """Advance the natural gas price one month: mean reversion + noise + events."""
        self.last_gas_event_msg = None

        # 1. Maybe trigger a new geopolitical event.
        if random.random() < GAS_EVENT_MONTHLY_CHANCE:
            event = random.choice(GAS_EVENTS)
            # Apply an immediate one-time shock to the price.
            self.natural_gas_price *= event["shock"]
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
            self.natural_gas_price *= (1.0 + ev["monthly_pressure"])
            ev["months_left"] -= 1
            if ev["months_left"] > 0:
                still_active.append(ev)
        self.active_gas_events = still_active

        # 3. Mean reversion toward the base price.
        self.natural_gas_price += (
            (NATURAL_GAS_BASE_COST_PER_MWH - self.natural_gas_price)
            * GAS_PRICE_MEAN_REVERSION
        )

        # 4. Baseline random noise.
        self.natural_gas_price *= (1.0 + random.uniform(
            -GAS_PRICE_MONTHLY_VOLATILITY, GAS_PRICE_MONTHLY_VOLATILITY))

        # 5. Clamp to sane bounds.
        self.natural_gas_price = max(NATURAL_GAS_MIN_COST_PER_MWH,
                                     min(NATURAL_GAS_MAX_COST_PER_MWH,
                                         self.natural_gas_price))

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
        if self.carbon_tax <= 0 and self.turn >= self._carbon_tax_start_turn:
            self.carbon_tax = self._carbon_tax_initial
            self.last_carbon_event_msg = (
                f"CARBON POLICY ENACTED: ${self.carbon_tax:.2f}/metric ton CO2; "
                f"scheduled to rise {self._carbon_tax_annual_growth * 100:.1f}% annually"
            )
            return
        if self.carbon_tax > 0:
            monthly_growth = (1 + self._carbon_tax_annual_growth) ** (1 / 12) - 1
            self.carbon_tax *= 1 + monthly_growth
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
              f"(base ${NATURAL_GAS_BASE_COST_PER_MWH})")
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
    def __init__(self):
        # Scale starting cash to the company so debt service doesn't instantly bankrupt you.
        self.company_value = random.uniform(MIN_COMPANY_SIZE, MAX_COMPANY_SIZE)
        self.cash = self.company_value * random.uniform(0.03, 0.06)
        # In PlayerState.__init__, after company_value:
        # Physical service territory (MW of peak demand) — independent of stock price.
        self.base_territory_mw = self.company_value / 1_000_000  # ~1000-2000 MW for a $1-2B co.

        
        # Derive debt from a realistic debt-to-equity ratio.
        # D/E = debt / equity, and equity = company_value - debt
        # => debt = company_value * de / (1 + de)
        # In PlayerState.__init__, replace the random shares_outstanding line:
        target_initial_price = random.uniform(25, 55)   # normal utility share price
        # equity / price = shares. Use equity so book value per share ~ price.
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

        self._initialize_random_plants()
        self.battery_dispatch_mode = "after_gas"  # or "before_gas"
        self.bonds = []  # list of Bond objects (replaces flat self.debt for new issuance)
        self.company_value = random.uniform(MIN_COMPANY_SIZE, MAX_COMPANY_SIZE)

        de_ratio = random.uniform(MIN_DE_RATIO, MAX_DE_RATIO)
        baseline_debt = self.company_value * de_ratio / (1 + de_ratio)
        target_debt = baseline_debt * STARTING_DEBT_MULTIPLIER
        opening_equity = self.company_value - baseline_debt
        self.baseline_starting_debt = baseline_debt
        self.de_ratio = target_debt / max(opening_equity, 1)

        self.debt = 0.0            # no more flat legacy debt; it's all bonds now
        self.bonds = []
        self._initialize_debt_ladder(target_debt)

        # Keep the original equity capitalization and layer the harder debt
        # burden on top, so doubling leverage does not collapse share count.
        self.equity = opening_equity
        self.shares_outstanding = max(1_000_000,
                                      int(self.equity / target_initial_price))
        self._target_initial_price = target_initial_price
        self.annual_dividend_per_share = 0.0   # set after we know share price
        self.stock_price = 0.0                  # computed each turn

        self.investor_confidence = 0.5   # 0..1, starts neutral
        self.last_dividend_per_share = None  # to detect raises/cuts
        self.consecutive_maintained = 0      # streak of holding-or-raising
        
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
        
    def total_asset_value(self):
        plant_values = {
            'coal': COAL_CONSTRUCTION_COST,
            'natural_gas': NATURAL_GAS_CONSTRUCTION_COST,
            'nuclear': NUCLEAR_CONSTRUCTION_COST,
            'solar': SOLAR_CONSTRUCTION_COST,
            'wind': WIND_CONSTRUCTION_COST,
            'hydro': HYDRO_BASE_CONSTRUCTION_COST,
        }
        assets = self.cash
        for ptype, count in self.power_plants.items():
            assets += count * plant_values.get(ptype, 0)
        assets += len(self.batteries) * BATTERY_CONSTRUCTION_COST
        return assets

    def emergency_loan(self, amount):
        """Last-resort high-interest loan. Always available while you have assets."""
        rate = 0.18  # punishing 18% APR
        bond = Bond(amount, rate, 1, 0)  # 1-year term
        self.bonds.append(bond)
        self.cash += amount
        print(f"!!! EMERGENCY LOAN: borrowed ${amount:,.0f} at {rate*100:.0f}% APR. "
              f"This will hurt. !!!")
        return bond

    def update_stock_price(self, economy, trailing_annual_earnings):
        # --- 1. Earnings-based value (P/E) ---
        eps = trailing_annual_earnings / max(self.shares_outstanding, 1)
        utility_pe = max(6.0, economy.market_pe * 0.85)
        earnings_value = eps * utility_pe if eps > 0 else 0.0

        # --- 2. Book value (asset floor) ---
        book_equity = max(self.equity, self.total_asset_value() * 0.1)
        book_value_per_share = book_equity / max(self.shares_outstanding, 1)

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
        # Weight earnings + book together, then blend with dividend value.
        fundamental = max(earnings_value, book_value_per_share * (0.4 if eps <= 0 else 1.0))
        if dividend_value > 0:
            fair_value = (1 - DIVIDEND_WEIGHT) * fundamental + DIVIDEND_WEIGHT * dividend_value
        else:
            # A utility that pays no dividend is less attractive: apply a haircut.
            fair_value = fundamental * 0.85
            
        # --- Investor confidence premium/discount (-15% to +15%) ---
        confidence_adj = 1.0 + (self.investor_confidence - 0.5) * 0.30
        fair_value *= confidence_adj
        
        # --- 5. Yield sanity: reward/punish vs. prevailing bond yields ---
        if self.stock_price > 0:
            current_yield = self.annual_dividend_per_share / self.stock_price
            yield_gap = current_yield - required_return
            fair_value *= (1 + max(-0.15, min(0.15, yield_gap * 1.5)))

        fair_value = max(0.50, fair_value)

        # --- 6. Smooth toward fair value instead of snapping ---
        if self.stock_price <= 0:
            # First valuation: anchor to the intended opening price, not the
            # loss-driven EPS.
            self.stock_price = getattr(self, '_target_initial_price', fair_value)
        else:
            self.stock_price += (fair_value - self.stock_price) * STOCK_SMOOTHING

        # --- 7. Market noise ---
        self.stock_price *= (1 + random.uniform(-STOCK_MONTHLY_NOISE, STOCK_MONTHLY_NOISE))
        self.stock_price = max(0.50, self.stock_price)

        self.company_value = self.stock_price * self.shares_outstanding

        if not self._dividend_initialized:
            self.annual_dividend_per_share = self.stock_price * 0.035
            self._dividend_initialized = True

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
        salvage_each = PLANT_BUILD_COST[plant_type] * salvage_frac
        net_each = salvage_each - teardown
        net = net_each * quantity
        self.power_plants[plant_type] -= quantity
        self.cash += net
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
        for _ in range(quantity):
            self.batteries.pop()
        salvage = BATTERY_CONSTRUCTION_COST * 0.10 * quantity
        self.cash += salvage
        noun = "unit" if quantity == 1 else "units"
        print(f"Decommissioned {quantity} battery {noun}. Salvage: ${salvage:,.0f}.")
        return True

    # Add to PlayerState — proactive wholesale trade
    def wholesale_trade(self, mw, direction, economy):
        # Price moves with the economy a bit.
        price = WHOLESALE_PRICE_PER_MWH * (1 + 0.1 * economy.sentiment)
        amount = mw * price * TURNS_PER_YEAR  # scale like your other $/MWh*year convention
        if direction == 'buy':
            self.cash -= amount
            print(f"Bought {mw} MW wholesale for ${amount:,.0f} (${price:.2f}/MWh).")
        else:
            self.cash += amount
            print(f"Sold {mw} MW wholesale for ${amount:,.0f} (${price:.2f}/MWh).")

    def pay_quarterly_dividend(self, game_state):
        if game_state.current_month in (3, 6, 9, 12):
            quarterly = self.annual_dividend_per_share / 4 * self.shares_outstanding
            self.cash -= quarterly
            self.dividends_paid += quarterly
            print(f"Paid quarterly dividend: ${quarterly:,.0f} "
                  f"(${self.annual_dividend_per_share/4:.3f}/share).")
        self.reward_dividend_consistency(game_state)  # update confidence streak

    def set_dividend(self, new_annual_per_share):
        new_div = max(0.0, new_annual_per_share)
        old_div = self.annual_dividend_per_share

        if old_div > 0:
            change = (new_div - old_div) / old_div
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

    def reward_dividend_consistency(self, game_state):
        """Called each quarter: reward holding/growing the dividend over time."""
        if game_state.current_month in (3, 6, 9, 12):
            if self.last_dividend_per_share is not None:
                if self.annual_dividend_per_share >= self.last_dividend_per_share:
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

    # PlayerState.issue_bond
    def issue_bond(self, principal, economy, term_key, credit):
        if not credit.can_borrow:
            print("Bond issuance FAILED: your credit rating is 'D' — no one will lend to you.")
            return None
        term_years = BOND_TERMS[term_key]
        rate = economy.bond_rate(term_years, credit.spread)
        bond = Bond(principal, rate, term_years, 0)
        self.bonds.append(bond)
        self.cash += principal
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
            return HYDRO_BASE_CONSTRUCTION_COST * (
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
        return cost_map.get(plant_type)

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
        cost_map = {
            'coal': COAL_CONSTRUCTION_COST,
            'natural_gas': NATURAL_GAS_CONSTRUCTION_COST,
            'nuclear': NUCLEAR_CONSTRUCTION_COST,
            'solar': SOLAR_CONSTRUCTION_COST,
            'wind': WIND_CONSTRUCTION_COST,
            'battery': BATTERY_CONSTRUCTION_COST,
            'hydro': HYDRO_BASE_CONSTRUCTION_COST,
        }
        time_map = {
            'coal': COAL_CONSTRUCTION_TIME,
            'natural_gas': NATURAL_GAS_CONSTRUCTION_TIME,
            'nuclear': NUCLEAR_CONSTRUCTION_TIME,
            'solar': SOLAR_CONSTRUCTION_TIME,
            'wind': WIND_CONSTRUCTION_TIME,
            'battery': BATTERY_CONSTRUCTION_TIME,
            'hydro': HYDRO_CONSTRUCTION_TIME,
        }

        if plant_type not in cost_map:
            print(f"Invalid plant type: {plant_type}")
            return False
        if quantity < 1:
            print("Construction quantity must be at least one.")
            return False

        individual_costs = ([self.construction_cost('hydro', offset)
                             for offset in range(quantity)]
                            if plant_type == 'hydro'
                            else [cost_map[plant_type]] * quantity)
        construction_cost = sum(individual_costs)
        construction_time = time_map[plant_type]

        if self.cash < construction_cost:
            print(f"Insufficient funds to start {plant_type} construction. "
                  f"Need ${construction_cost:,.2f}, have ${self.cash:,.2f}.")
            return False

        self.cash -= construction_cost
        for unit_cost in individual_costs:
            self.ongoing_constructions.append({
                'type': plant_type,
                'turns_remaining': construction_time,
                'cost_paid': unit_cost,
                'total_cost': unit_cost,
                'initial_cost': unit_cost,
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
                overrun_amount = project['initial_cost'] * random.uniform(0.01, 0.05)
                project['total_cost'] += overrun_amount
                project['cost_paid'] += overrun_amount
                self.cash -= overrun_amount
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
        self.total_demand = 0
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
        fluctuation = random.uniform(-0.1, 0.1)
        self.total_demand = (player_state.base_territory_mw
                             * (1 + fluctuation)
                             * game_state.demand_multiplier
                             * game_state.demand_index)
        return self.total_demand

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
        return (self.firm_capacity(player_state) - peak) / peak

    def update_grid_status(self, player_state, game_state):
        self.calculate_demand(player_state, game_state)

        self.gas_generation = 0
        self.battery_discharged = 0
        self.battery_charged = 0

        baseload = self._baseload(player_state, game_state)
        gas_available = player_state.power_plants['natural_gas'] * NATURAL_GAS_PLANT_CAPACITY
        supply = baseload
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
        self.current_surplus_deficit = (
            self.total_generation + self.battery_discharged
            - self.battery_charged - self.total_demand
        )

    def display_grid_status(self, player_state=None):
        print("\n--- Power Grid Status ---")
        print(f"Total Generation: {self.total_generation:.2f} MW")
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
        self.operational_costs = 0
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
        
    def calculate_operational_costs(self, player_state, game_state, power_grid, economy):
        infl = (1 + economy.inflation) ** ((game_state.year - 1) + game_state.current_month/12)
        costs = 0
        costs += player_state.power_plants['coal'] * COAL_PLANT_CAPACITY * COAL_COST_PER_MWH * HOURS_PER_YEAR * infl
        costs += power_grid.gas_generation * game_state.natural_gas_price * HOURS_PER_YEAR
        costs += player_state.power_plants['nuclear'] * NUCLEAR_PLANT_CAPACITY * NUCLEAR_COST_PER_MWH * HOURS_PER_YEAR * infl
        costs += player_state.power_plants['solar'] * SOLAR_PLANT_CAPACITY * SOLAR_COST_PER_MWH * game_state.region_sunlight_level * HOURS_PER_YEAR * infl
        costs += player_state.power_plants['wind'] * WIND_PLANT_CAPACITY * WIND_COST_PER_MWH * game_state.region_wind_level * HOURS_PER_YEAR * infl
        costs += player_state.power_plants['hydro'] * HYDRO_PLANT_CAPACITY * HYDRO_OUTPUT_FACTOR * HYDRO_COST_PER_MWH * HOURS_PER_YEAR * infl
        self.coal_generation_mwh = (
            player_state.power_plants['coal'] * COAL_PLANT_CAPACITY * HOURS_PER_YEAR
        )
        self.gas_generation_mwh = power_grid.gas_generation * HOURS_PER_YEAR
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
        costs += self.carbon_costs
        self.last_interest_rate = economy.interest_rate
        self.operational_costs = costs
        return costs

    def calculate_revenue(self, power_grid, regulator):
        retail = regulator.current_retail_price
        if power_grid.current_surplus_deficit >= 0:
            self.revenue = (power_grid.total_demand * retail * HOURS_PER_YEAR
                            + power_grid.current_surplus_deficit * WHOLESALE_PRICE_PER_MWH * HOURS_PER_YEAR)
        else:
            self.revenue = (power_grid.total_generation * retail * HOURS_PER_YEAR
                            - abs(power_grid.current_surplus_deficit) * WHOLESALE_PRICE_PER_MWH * HOURS_PER_YEAR)
        return self.revenue

    def update_player_financials(self, player_state, game_state, power_grid,
                                 economy, regulator, valuation_only=False):
        self.calculate_operational_costs(player_state, game_state, power_grid, economy)
        self.calculate_revenue(power_grid, regulator)

        # Annual figures (for valuation/display):
        annual_net = self.revenue - self.operational_costs

        if valuation_only:
            self.net_profit = annual_net
            self.trailing_earnings = [annual_net / 12] * 12
            player_state.update_stock_price(economy, annual_net)
            # company_value is the stock-market capitalization after valuation,
            # so it already represents market equity rather than enterprise value.
            player_state.equity = player_state.company_value
            return

        # Monthly cash impact:
        monthly_operating = annual_net / 12
        bond_interest = player_state.process_bonds()      # already monthly
        self.net_profit = monthly_operating - bond_interest
        player_state.cash += self.net_profit

        self.trailing_earnings.append(self.net_profit)
        if len(self.trailing_earnings) > 12:
            self.trailing_earnings.pop(0)
        annual_earnings = sum(self.trailing_earnings)     # trailing 12 months = annual
        player_state.update_stock_price(economy, annual_earnings)
        player_state.pay_quarterly_dividend(game_state)
        player_state.equity = player_state.company_value


    def display_financial_summary(self):
        print("\n--- Financial Summary (This Month) ---")
        monthly_rev = self.revenue / 12
        monthly_costs = self.operational_costs / 12
        print(f"Revenue (monthly):        ${monthly_rev:,.2f}")
        print(f"Operational Costs (monthly): ${monthly_costs:,.2f}")
        if self.carbon_costs > 0:
            print(f"  Carbon tax (monthly):    ${self.carbon_costs / 12:,.2f}")
        print(f"Bond Interest (monthly):  ${(monthly_rev - monthly_costs - self.net_profit):,.2f}")
        print(f"Net Profit/Loss (monthly): ${self.net_profit:,.2f}")
        print(f"  (Annualized revenue: ${self.revenue:,.0f} | "
              f"costs: ${self.operational_costs:,.0f})")


def check_bankruptcy(player_state, credit):
    """Game over if the player can't cover cash and can't raise any more."""
    if player_state.cash >= 0:
        return False

    # Can they still borrow?
    if credit.can_borrow:
        return False  # not bankrupt — they can still issue a bond next turn

    # No lenders. Do they have anything left to liquidate?
    has_plants = any(c > 0 for c in player_state.power_plants.values())
    has_batteries = len(player_state.batteries) > 0
    if has_plants or has_batteries:
        return False  # could still sell assets to survive

    # Broke, no credit, nothing to sell -> bankrupt.
    return True



def player_action_menu(player_state, economy, regulator, financials, credit, current_turn):
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
        if player_state.cash < 0:
            print("  *** WARNING: CASH IS NEGATIVE. You must raise cash before ending the turn. ***")
        print("  Build:  1 Coal  2 Gas  3 Nuclear  4 Solar  5 Wind  6 Battery  13 Hydro")
        print("  Decommission:  a Coal  b Gas  c Nuclear  d Solar  e Wind  f Battery  g Hydro")
        print("  7 Issue bond  8 Rate increase  9 Wholesale trade  10 Set dividend")
        print(" 11 Toggle battery dispatch  0 End turn")
        print(" 12 Emergency loan (high interest, last resort)")

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
            pct = float(input("Requested increase (e.g. 0.05): "))
            regulator.request_increase(player_state, financials, economy, current_turn, pct)
        elif choice == '9':
            d = input("buy or sell? ").strip().lower()
            mw = float(input("MW: "))
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
        else:
            print("Invalid.")
            

def play_turn(game_state, player_state, power_grid, financials, economy, regulator, credit):
    print(f"\n--- {MONTH_NAMES[game_state.current_month-1]}, YEAR {game_state.year} ---")
    result = player_action_menu(player_state, economy, regulator, financials, credit, game_state.turn)
    if result == "BANKRUPT":
        return "BANKRUPT"

    game_state.advance_turn()
    economy.update()
    game_state.display_env_status()
    economy.display()
    player_state.update_constructions()
    power_grid.update_grid_status(player_state, game_state)
    power_grid.display_grid_status(player_state)
    financials.update_player_financials(player_state, game_state, power_grid, economy, regulator)
    financials.display_financial_summary()
    credit.update(player_state, financials)      # refresh rating from the turn's results
    player_state.display_player_status()
    player_state.display_equity()
    credit.display()

    # Post-turn safety net: if a maturing bond or dividend drove cash negative
    # and there's no way out, end the game.
    if check_bankruptcy(player_state, credit):
        print("\n!!! BANKRUPTCY: obligations came due with no cash, no credit, "
              "and no assets to liquidate. !!!")
        return "BANKRUPT"
    return "OK"


def run_game(num_turns):
    game_state = GameState()
    player_state = PlayerState()
    power_grid = PowerGrid()
    financials = Financials()
    economy = Economy()
    regulator = RateRegulator()
    credit = CreditRating()

    financials.update_player_financials(player_state, game_state, power_grid,
                                        economy, regulator, valuation_only=True)
    credit.update(player_state, financials)

    print("\n--- Game Start ---")
    for _ in range(num_turns):
        result = play_turn(game_state, player_state, power_grid, financials,
                           economy, regulator, credit)
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


class UtilityGameSession:
    """A small controller shared by the graphical interface and its tests."""

    def __init__(self, max_turns=1000):
        self.max_turns = max_turns
        self.game_state = GameState()
        self.player = PlayerState()
        self.grid = PowerGrid()
        self.financials = Financials()
        self.economy = Economy()
        self.regulator = RateRegulator()
        self.credit = CreditRating()
        self.game_over = False

        # Populate the opening dashboard with a real demand and dispatch picture.
        self.grid.update_grid_status(self.player, self.game_state)
        self.financials.update_player_financials(
            self.player, self.game_state, self.grid, self.economy,
            self.regulator, valuation_only=True
        )
        self.last_monthly_profit = self.financials.net_profit / 12
        self.credit.update(self.player, self.financials)

    def advance_month(self):
        """Resolve one month after the player has finished making decisions."""
        if self.game_over:
            return "GAME_OVER"

        state = self.game_state
        state.advance_turn()
        self.economy.update()
        self.player.update_constructions()
        self.grid.update_grid_status(self.player, state)
        self.financials.update_player_financials(
            self.player, state, self.grid, self.economy, self.regulator
        )
        self.last_monthly_profit = self.financials.net_profit
        self.credit.update(self.player, self.financials)

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
        self.root.title("Gridline — Utility Command Center")
        self.root.configure(bg=self.COLORS['background'])
        self.root.minsize(1040, 700)
        screen_w = self.root.winfo_screenwidth()
        screen_h = self.root.winfo_screenheight()
        width = min(1380, max(1040, screen_w - 80))
        height = min(920, max(700, screen_h - 100))
        self.root.geometry(f"{width}x{height}")

        self.cards = {}
        self.action_buttons = []
        self.history = []
        self.flow_phase = 0
        self._configure_styles()
        self._build_layout()
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
        self.next_button = tk.Button(
            header, text="ADVANCE MONTH  →", command=self.advance_month,
            bg=self.COLORS['cyan'], fg='#031017', activebackground='#72e8f2',
            activeforeground='#031017', relief='flat', cursor='hand2',
            font=('Helvetica', 10, 'bold'), padx=18, pady=10
        )
        self.next_button.grid(row=0, column=3, rowspan=2, padx=(8, 0))

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
        self._section_title(chart_panel, "GRID HISTORY", "Demand and available generation (MW)")
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
            f"Economy: {mood}  •  Inflation {session.economy.inflation * 100:.1f}%  •  "
            f"Rates {session.economy.interest_rate * 100:.1f}%\n"
            f"Gas ${state.natural_gas_price:.2f}/MWh  •  Retail "
            f"${session.regulator.current_retail_price:.2f}/MWh\n"
            f"Carbon tax: {carbon}  •  Dispatch: {mode}"
        ))

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

        top_text = (f"{grid.total_generation:,.0f} MW generated   •   "
                    f"{grid.total_demand:,.0f} MW demanded")
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
            'demand': grid.total_demand,
        })
        self.history = self.history[-24:]

    def _draw_chart(self):
        canvas = self.chart
        width = max(400, canvas.winfo_width())
        height = max(140, canvas.winfo_height())
        canvas.delete('all')
        left, right, top, bottom = 48, width - 16, 18, height - 28
        all_values = [point[key] for point in self.history for key in ('generation', 'demand')]
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
        for key, color in (('generation', self.COLORS['cyan']),
                           ('demand', self.COLORS['orange'])):
            coords = []
            for x, point in zip(x_positions, self.history):
                y = bottom - (bottom - top) * point[key] / ceiling
                coords.extend((x, y))
            if len(coords) >= 4:
                canvas.create_line(*coords, fill=color, width=2, smooth=True)
            elif coords:
                canvas.create_oval(coords[0] - 3, coords[1] - 3,
                                   coords[0] + 3, coords[1] + 3, fill=color, outline='')
        if self.history:
            canvas.create_text(left, bottom + 13, text=self.history[0]['label'], anchor='w',
                               fill=self.COLORS['muted'], font=('Helvetica', 7))
            canvas.create_text(right, bottom + 13, text=self.history[-1]['label'], anchor='e',
                               fill=self.COLORS['muted'], font=('Helvetica', 7))
        canvas.create_line(right - 180, 10, right - 158, 10, fill=self.COLORS['cyan'], width=3)
        canvas.create_text(right - 152, 10, text='Generation', anchor='w',
                           fill=self.COLORS['muted'], font=('Helvetica', 8))
        canvas.create_line(right - 83, 10, right - 61, 10, fill=self.COLORS['orange'], width=3)
        canvas.create_text(right - 55, 10, text='Demand', anchor='w',
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
        output = io.StringIO()
        try:
            with contextlib.redirect_stdout(output):
                result = action()
        except (ValueError, KeyError) as exc:
            messagebox.showerror("Action could not be completed", str(exc), parent=self.root)
            return None
        self._append_log(output.getvalue().strip())
        self.refresh()
        return result

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
        window.geometry("980x680")
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

        controls = tk.Frame(window, bg=self.COLORS['background'], padx=20, pady=12)
        controls.grid(row=4, column=0, sticky='ew')
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
        debt_to_market_cap = total_debt / max(player.company_value, 1)
        debt_market_value = sum(
            player.bond_buyback_quote(bond, economy, credit)[2]
            for bond in player.bonds
        )
        summary.configure(text=(
            f"Cash  {compact_money(player.cash)}     Total debt  {compact_money(total_debt)}     "
            f"Debt / market cap  {debt_to_market_cap:.2f}×     Credit  {credit.rating}\n"
            f"Stock  ${player.stock_price:,.2f}     Market cap  {compact_money(player.company_value)}     "
            f"Dividend  ${player.annual_dividend_per_share:.3f}/share     Yield  {dividend_yield:.2f}%\n"
            f"Annual interest  {compact_money(annual_interest)}     Weighted coupon  {weighted_coupon:.2f}%     "
            f"Debt market value  {compact_money(debt_market_value)}\n"
            f"Base rate  {economy.interest_rate * 100:.2f}%     "
            f"Carbon cost/month  {compact_money(financials.carbon_costs / 12)}"
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
        amount = simpledialog.askfloat(
            "Issue bond", "Principal ($ millions):", minvalue=1, parent=self.root
        )
        if amount is not None:
            self._run_action(lambda: self.session.player.issue_bond(
                amount * 1_000_000, self.session.economy, term, self.session.credit
            ))

    def request_rate_case(self):
        percent = simpledialog.askfloat(
            "Request rate increase", "Requested increase (%):", minvalue=0.1,
            maxvalue=50, parent=self.root
        )
        if percent is not None:
            self._run_action(lambda: self.session.regulator.request_increase(
                self.session.player, self.session.financials, self.session.economy,
                self.session.game_state.turn, percent / 100
            ))

    def trade_power(self):
        direction = simpledialog.askstring(
            "Wholesale power", "Type BUY or SELL:", parent=self.root
        )
        if direction is None:
            return
        direction = direction.strip().lower()
        if direction not in ('buy', 'sell'):
            messagebox.showerror("Invalid trade", "Enter BUY or SELL.", parent=self.root)
            return
        mw = simpledialog.askfloat("Wholesale power", "Amount (MW):", minvalue=0.1,
                                   parent=self.root)
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

    def toggle_battery_mode(self):
        player = self.session.player
        player.battery_dispatch_mode = (
            'before_gas' if player.battery_dispatch_mode == 'after_gas' else 'after_gas'
        )
        readable = "battery before gas" if player.battery_dispatch_mode == 'before_gas' else "gas before battery"
        self._append_log(f"Dispatch priority changed to {readable}.")
        self.refresh()

    def emergency_loan(self):
        amount = simpledialog.askfloat(
            "Emergency loan", "Loan amount ($ millions, 18% APR):",
            minvalue=1, parent=self.root
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
            f"Month closed: {grid.total_generation:,.0f} MW supplied against "
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
        if result == 'BANKRUPT':
            messagebox.showerror("Game over", "Your utility has gone bankrupt.", parent=self.root)
        elif result == 'COMPLETE':
            messagebox.showinfo("Planning complete", "You reached the end of the simulation.",
                                parent=self.root)

    def show_help(self):
        messagebox.showinfo(
            "How to play Gridline",
            "Keep the grid reliable and the company solvent. Build capacity before demand "
            "overtakes supply, maintain at least a 15% reserve margin, and watch fuel prices, "
            "interest rates, debt, carbon policy, and construction lead times. Hydro gets "
            "more expensive as the best river sites are used.\n\n"
            "You may take as many management actions as you like before choosing Advance Month. "
            "Use Financial to review dividends and buy bonds back at their current market value. "
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
