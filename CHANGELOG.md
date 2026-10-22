# Utility Simulator release notes

## Version 3

- Added ten randomly generated regions of varying size, a clickable map, and
  nine independent utilities with full asset, debt, cash, and operating models.
- Use the same random 1,000–10,000 MW starting-size distribution for the player
  and competitors. The player can start anywhere in the ranking; map area no
  longer gives rivals a separate size advantage. Existing saved sizes remain.
- Added competitor comparisons and market-cap rankings in Financial. Regional
  utilities invest, finance projects, request rate relief, and reprice monthly
  as demand, inflation, and economic conditions change.
- Competitors retire uneconomic fossil plants as carbon/fuel costs rise,
  compare replacement technologies, and use imports during construction.
  They anticipate plant retirements and reduce unaffordable dividends. New
  construction borrowing must pass leverage, interest-coverage, and operating-
  savings checks to avoid debt-fueled overbuilding.
- Keep competitor cash nonnegative with recorded borrowing for actual
  shortfalls. Ordinary loans come first; a competitor-only continuity facility
  covers essential bills beyond normal credit limits. Its interest-bearing
  debt appears in comparisons and transfers in acquisitions; it cannot fund
  discretionary construction or expand the human player's borrowing limit.
- Add physical service limits: 35 years for solar/wind, 50 for coal/gas,
  100 for nuclear/hydro, and 20 for batteries. Automatically retire expired
  units with normal disposal accounting, separately from depreciation lives.
  Show remaining life, advance warnings, and forecast capacity reductions.
- Added premium-priced acquisitions: at least 40% over market cap and 15% over
  book equity, plus 2% closing costs. Purchases transfer plants, batteries,
  construction, cash, debt, customers, and purchase contracts; acquired company
  shares are canceled and its assets consolidate into the player's utility.
- Added acquisition goodwill and net acquisition spending to current and
  historical financial statements. Preserved original plant depreciation and
  bond maturities, and kept prior accounting periods immutable.
- Added dedicated ten-year acquisition financing outside recessions, capped
  by 50% of closing cost, 20% of combined net plant, interest coverage of at
  least 2×, and combined net debt of at most 6× EBITDA. It can only fund closing
  and does not consume or replenish the ordinary monthly credit allowance.
- Replaced the predictable sine-wave business cycle with uncertain transitions
  and shocks, including rare deflationary crises. Long-term yields retain
  recency bias through a slowly declining rate-memory anchor.
- Halved ordinary borrowing availability during recessions and disabled new
  dedicated acquisition borrowing until the recession ends. Added explicit
  expansion/recession stock-valuation adjustments.
- Removed power-selling controls and export revenue, including automatic
  surplus sales. Imports still work; surplus is curtailed after charging storage.
- Stopped automatic inflation increases to retail tariffs. Manual requests
  can qualify on recurring after-interest margins below 12%, not only losses.
  Retirement write-offs do not justify rate relief or worsen credit leverage;
  actual cash shortages and operating deterioration still matter.
- Reduced new-game inherited capacity to just below the seasonal demand peak.
  Doubled all new plant and battery construction costs, including the mature
  solar/wind learning-curve targets. Existing historical costs remain fixed.
- Added sequential schema-1/2 to schema-3 save migrations, including an original
  version 2 fixture. Maps, competitors, acquisitions, economic memory, plant
  service limits, and continuity debt persist without rerolling the saved RNG.
  Legacy negative competitor cash is refinanced with explicit debt entries;
  closed statements, plant ages, and historical costs remain unchanged.
- Added automated coverage for plant shutdown boundaries, carbon-driven
  replacement, cash-flow reconciliation, refinancing, randomized sizes,
  acquisition transfers, and deterministic continued play after save/load.

## Version 2

Version 2 adds persistent games, calendar financial reporting, and shareholder
management, and reworks the financial and operating model from version 1.

### Saves and compatibility

- Added dashboard Save/Load controls and keyboard shortcuts.
- Added atomic, versioned JSON saves of all simulation instance attributes,
  including monthly ledgers, pending actions, historical reports, graph
  history, event logs, and random-generator state.
- Preserved shared model references and unknown fields on registered classes.
  Added validation, safe class registration, schema migration hooks, and
  rejection of unsupported future formats without replacing the running game.
- Documented required compatibility practices for future updates.

### Accounting and reporting

- Added detailed income statements, balance sheets, and indirect-method
  cash-flow statements with hover definitions.
- Added four completed calendar-quarter and four completed calendar-year
  comparisons for all three statements. Backfilled four years of seasonal
  estimated operations, visibly distinguishing estimates from actual closes.
- Added immutable monthly snapshots, period-end balance reporting, and
  weighted-average shares for period and trailing twelve-month EPS.
- Added plant-by-plant original cost, useful life, age, accumulated
  depreciation, and net book value. Starting plants are already 20–65%
  through their useful lives.
- Added operating-cost breakdowns by plant type, including fuel/O&M,
  purchased power, carbon tax, and depreciation.
- Separated operating income, interest, taxes, non-cash depreciation,
  construction spending, debt settlement, dividends, and stock transactions.
- Corrected financial-window padding that caused a Tkinter error.

### Opening finances and credit

- Calibrated opening debt/book equity to 1.5× and opening actual P/E to
  approximately 10×, with normal small market noise.
- Added actual P/E and book-equity leverage displays, distinct from the
  valuation model's target multiple.
- Starts at BBB+ or A− and uses plus/minus investment and speculative grades.
  Reduced new-bond spreads and term premiums rather than raising inherited
  bond coupons.
- Bases credit leverage on outstanding debt less cash, alongside earnings
  and interest coverage, to limit borrow-and-repurchase rating manipulation.
- Makes AAA require sustained strong performance and reserves D for
  persistent cash shortfalls; upgrades retain a long memory.
- Caps total monthly new borrowing, including emergency loans, at 10% of
  opening non-cash book assets. Repaying debt does not refill that allowance.
- Retains market-value bond buybacks using remaining duration, current
  market rates and credit spreads, with execution costs and accounting for
  debt-retirement gains or losses.

### Shareholders and stock valuation

- Replaced the interim six-month low-dividend rule with a persistent,
  color-coded 0–100 shareholder-happiness meter on the main screen.
- Rewards sufficient dividends and meaningful raises; penalizes low yields,
  prolonged flat payouts, and each dividend cut by 50 points. Dismissal
  occurs at 10 points or less.
- Uses an inflation-adjusted opening-price floor for the happiness yield
  calculation, preventing intentional price crashes from gaming it.
- Added issuance and buyback controls. Combined gross activity is limited
  to 4.9% of both year-opening shares and market capitalization per year,
  with a 1% execution spread.
- Repeated issuance reduces happiness and sustained buybacks improve it;
  stopping buybacks has no additional penalty. Rewards scale with transaction
  size, and round trips do not replenish the annual allowance.
- Stock valuation now emphasizes trailing twelve-month EPS: 70% earnings,
  20% book value, and 10% dividends, with market rates, confidence, and
  smoothing still affecting prices. Negative earnings reduce valuation.
- Stock transactions update cash, shares, paid-in capital or treasury stock,
  financing cash flows, and subsequent weighted-average EPS.

### Power operations and planning

- Wholesale orders now replace a recurring monthly import/export commitment
  effective the next month, rather than producing a one-time cash adjustment.
- Exports subtract available power; imports add power. Remaining imbalances
  settle at spot prices, with bid/ask spreads preventing free round trips.
- Added separate chart series for actual production and maximum producible
  output, including natural-gas capacity.
- Added a 24-month seasonal demand forecast with growth assumptions and
  expected construction completions.
- Retains version 1 batch construction and retirement, construction tracking,
  increasing hydro-site costs, battery charge displays, carbon policy, and
  emissions reporting.

### Inflation and technology costs

- Applies a cumulative monthly inflation index to construction quotes,
  operating costs, gas-price ranges, wholesale power, retail tariffs,
  construction overruns, retirement costs, and carbon charges.
- Keeps historical asset purchase costs and nominal cash/debt balances
  unchanged by inflation; acquired assets depreciate from their recorded cost.
- Raises the opening retail tariff to $150/MWh and restores the $9 billion
  nuclear construction cost after interim development balancing.
- Starts solar/wind at $600 million/$450 million per unit, declining over
  120 months to $330 million/$275 million in opening-dollar terms, with
  annual learning-curve news. Nominal quotes also include inflation.

### Verification

- Added automated coverage for financing, physical power balances, asset
  accounting, forecasts, credit calibration, inflation, persistence,
  financial-period reconciliation, and shareholder/trading limits.
- Checked the graphical statement views, financial/construction/forecast
  windows, equity transactions, save/load, and continued monthly play.

## Version 1

Initial graphical release: grid dashboard, coal/gas/nuclear/solar/wind/hydro,
batteries, batch construction and retirement, carbon policy, bond ladders
and buybacks, construction tracking, and financial overview.
