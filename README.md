# Utility Simulator — Version 3

A desktop utility-management game where you operate a power grid, manage a
generation portfolio, finance long-lived infrastructure, and respond to fuel,
economic, demand, and carbon-policy changes.

## Run the game

Python 3 with Tkinter is required; version 3 was tested with Python 3.13 on
macOS. There are no third-party Python dependencies. Keep `utility.py`,
`utility_reports.py`, and `utility_persistence.py` together in the same folder.

```bash
python3 utility.py
```

To use the terminal interface instead:

```bash
python3 utility.py --cli
```

For a repeatable game or a shorter planning horizon:

```bash
python3 utility.py --seed 42 --turns 240
```

## Save and resume

Use **Save** and **Load** on the main dashboard. Keyboard shortcuts are
Command-S / Command-O on macOS, or Control-S / Control-O. Saves use
`.gridline.json` files and include accounts, plants, construction, batteries,
contracts, bond maturities, credit history, shareholder happiness, economic
conditions, statement history, graph history, and the event log.

Loading also restores the random generator state, so it resumes the same
future simulation rather than rerolling the next event. Save before closing;
there is no automatic save. Save/load controls are in the graphical interface.
See [Save format](SAVE_FORMAT.md) for compatibility and maintenance rules.

## Financial statements

Open **Financials**, then the income statement, balance sheet, or cash-flow
statement. Each offers the latest month, the last four completed calendar
quarters, and the last four completed calendar years. Quarters are months
1–3, 4–6, 7–9, and 10–12; annual statements cover months 1–12.

Income and cash-flow columns sum activity; balance sheets show period-end
balances. The first four historical years are reasonable simulated estimates,
explicitly marked **est.**, not real company records. The opening January
estimate and subsequent actual closes produce **mixed** periods until the
estimates roll out. Hover over accounting terms for explanations.

Plant details show each unit's original cost, age, accumulated depreciation,
and remaining book value. Operating costs are also broken down by plant type.
The income statement includes trailing twelve-month EPS, while Financials
shows the actual P/E and debt/book-equity ratios.

## Regions and acquisitions

**View map** shows ten randomly generated regions with different areas and
utility sizes. All ten utilities draw their starting territory size from the
same 1,000–10,000 MW distribution, including yours: you can start anywhere
in the size ranking, not necessarily in the middle. Geography does not give
rivals an additional size advantage. You start in one region; the other nine have independent
companies with actual plants, construction projects, cash, debt, and earnings.
Their demand, operating costs, investment, borrowing, and stock values evolve
monthly. Historical plant costs are not simply marked up with inflation;
new investment and financing reflect current prices and capacity needs.

Competitors retire coal or gas when fuel plus carbon charges make operating
them uneconomic, use purchased power during construction, and select new
plants using construction, financing, operating, and expected carbon costs.
They anticipate aging plants, request rate relief for weak recurring profits,
and cut unaffordable dividends. New construction borrowing is limited by
earnings, interest coverage, and the project's power-cost savings. Actual
cash shortfalls are borrowed before each close; if ordinary credit is exhausted,
a competitor-only ten-year continuity loan covers the remainder at a higher
rate. Cash never gets an unexplained top-up: these loans increase debt, incur
interest, and transfer to you in a buyout. They cannot fund discretionary
construction, and this backstop does not change the player's borrowing limits.

Open **Financial → Competitors / Buyouts** to compare market capitalization,
assets, liabilities, cash, trailing earnings, credit, capacity, and demand.
Select a company to inspect its fleet and acquisition terms.

Buyouts cost at least 40% above market capitalization and 15% above book
equity, plus 2% closing costs. You acquire its cash, generating assets,
batteries, projects, customers, wholesale purchases, and outstanding debt.
The excess purchase cost is recorded as goodwill. The tariff becomes a
demand-weighted blend of the existing approved tariffs; an acquisition is
not an automatic rate increase. Dispatch incorporates the added fleet and
customers at the next monthly close.

Outside recessions, a dedicated ten-year acquisition loan may finance up to
50% of the closing price, subject to tangible-asset and earnings-coverage
limits. It is additional to the normal borrowing allowance, but can only be
drawn as part of a completed purchase. The target's existing debt is assumed
on top of that loan. Cash-funded acquisitions remain available in recessions.

## Plant service limits

Plants stop operating and automatically retire after 35 years for solar/wind,
50 years for coal/gas, 100 years for nuclear/hydro, and 20 years for batteries.
The last service month still produces power; subsequent months do not. Plan
and finance replacements before then. Wholesale purchases can bridge gaps.

The plant register lists each unit's service limit and remaining months.
Construction shows upcoming retirements, news warns before shutdown, and
the demand forecast subtracts expiring capacity. Service limits are separate
from accounting depreciation lives: a fully depreciated plant can continue
operating until its physical limit. Automatic retirements remove the expired
unit, record salvage and disposal costs, and leave historical statements intact.
Existing saves retain recorded ages and costs; already-expired units retire
before generating power when you advance the month. Existing regional sizes
are preserved when loading a save.

## Version 3 gameplay

- Opening retail tariff of $150/MWh, debt/book equity of 1.5×, approximately
  10× P/E, and a BBB+ or A− credit rating.
- Plus/minus credit grades, net-debt leverage, slow credit recovery, and a
  shared monthly borrowing ceiling of 10% of opening non-cash asset value,
  reduced to 5% in recessions. Goodwill is not borrowing collateral.
- Uncertain expansion, slowdown, recession, and recovery periods instead of
  a repeating cycle; very rare deflationary crises. Long-term rates retain
  memory of sustained high rates. Stock valuations rise in expansions and
  fall in recessions, other things equal.
- Recurring wholesale purchases that start the next month. Selling power
  is disabled, including automatic sales of surplus generation; excess
  power is curtailed after battery charging.
- Cumulative inflation for new construction, operating costs, wholesale
  prices, and other current-dollar costs. Retail tariffs stay fixed until
  an approved manual rate request. Recurring after-interest margins below
  12%, including small profits, qualify for review; approval is not guaranteed.
- Retirement write-offs remain accounting losses but are excluded from
  rate-case margins and added back to equity for credit leverage. Real cash
  shortfalls and subsequent operating weakness still affect credit.
- All new plant and battery prices are doubled from version 2. Nuclear is
  $18 billion per 1,200 MW unit. Solar and wind start at $1.2 billion and
  $900 million per unit, then decline over ten years to $660 million and
  $550 million in opening-dollar terms. Inflation still
  applies; annual news events explain the learning curve.
- A shareholder-happiness battery meter: yields of at least 3% help, yields
  of 2% or less hurt, regular raises help, and each dividend cut costs
  50 points. At 10/100 or below, the board fires you.
- Stock issuance and buybacks with a combined annual limit of 4.9% of both
  year-opening shares and market value, plus a 1% execution spread.
  Repeated issuance hurts happiness; sustained buybacks help without a
  penalty for stopping.
- Earnings-led stock valuation: 70% earnings, 20% book value, 10% dividends.
  Happiness uses a protected dividend reference so deliberately crashing
  the share price cannot make a tiny dividend acceptable.
- Actual and maximum production charts, plus a 24-month demand forecast.

These prices, credit thresholds, and learning curves are gameplay assumptions,
not predictions or investment guidance.

## Retained features

- Graphical grid dashboard with animated power flow and battery charge state
- Coal, gas, nuclear, solar, wind, hydro, and four-hour battery storage
- Batch construction and retirement with project schedules and cost overruns
- Demand growth, economic cycles, fuel-price shocks, and seasonal conditions
- Randomly enacted and escalating carbon tax with emissions reporting
- Retail rate cases, wholesale power purchases, and dividend management
- Credit ratings, term debt, bond ladders, and market-value bond buybacks
- Construction and financial screens with detailed operating information

New games start with a leveraged, partially depreciated fossil-heavy
fleet and no renewable generation, sized just below the seasonal demand peak
rather than with a large reserve cushion. The player must maintain reliability while
financing a cleaner portfolio before carbon costs and rising demand erode
the company's position.

## Tests and release notes

```bash
python3 -m unittest discover -p 'test_utility*.py'
```

[Release notes](CHANGELOG.md) cover version 3 and the earlier changes since
version 1. Original version 2 saves migrate automatically: existing plants,
debt, and historical statements retain their recorded values, the current
retail rate is frozen, and the new competitors are generated deterministically.
