# Utility Simulator — Version 2

A desktop utility-management game where you operate a power grid, manage a
generation portfolio, finance long-lived infrastructure, and respond to fuel,
economic, demand, and carbon-policy changes.

## Run the game

Python 3 with Tkinter is required; version 2 was tested with Python 3.13 on
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

## Version 2 gameplay

- Opening retail tariff of $150/MWh, debt/book equity of 1.5×, approximately
  10× P/E, and a BBB+ or A− credit rating.
- Plus/minus credit grades, net-debt leverage, slow credit recovery, and a
  shared monthly borrowing ceiling of 10% of opening non-cash asset value.
- Recurring wholesale purchases and sales that start the next month and
  physically affect the power balance.
- Cumulative inflation for new construction, operating costs, wholesale
  prices, retail tariffs, and other current-dollar costs.
- Nuclear construction at $9 billion per 1,200 MW unit. Solar and wind start
  at $600 million and $450 million per unit, then decline over ten years to
  $330 million and $275 million in opening-dollar terms. Inflation still
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
- Retail rate cases, wholesale power trading, and dividend management
- Credit ratings, term debt, bond ladders, and market-value bond buybacks
- Construction and financial screens with detailed operating information

The simulation starts with a leveraged, partially depreciated fossil-heavy
fleet and no renewable generation. The player must maintain reliability while
financing a cleaner portfolio before carbon costs and rising demand erode
the company's position.

## Tests and release notes

```bash
python3 -m unittest discover -p 'test_utility*.py'
```

[Version 2 release notes](CHANGELOG.md) describe the changes since version 1,
including the accounting, power-trading, and inflation improvements.
