# Utility Simulator — Version 1

A desktop utility-management game where you operate a power grid, manage a
generation portfolio, finance long-lived infrastructure, and respond to fuel,
economic, demand, and carbon-policy changes.

## Run the game

Python 3 with Tkinter is required. Tkinter is included with standard Python
installations on macOS and Windows.

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

## Version 1 features

- Graphical grid dashboard with animated power flow and battery charge state
- Coal, gas, nuclear, solar, wind, hydro, and four-hour battery storage
- Batch construction and retirement with project schedules and cost overruns
- Demand growth, economic cycles, fuel-price shocks, and seasonal conditions
- Randomly enacted and escalating carbon tax with emissions reporting
- Retail rate cases, wholesale power trading, and dividend management
- Credit ratings, term debt, bond ladders, and market-value bond buybacks
- Construction and financial screens with detailed operating information

The simulation starts with a leveraged fossil-heavy fleet. The player must
maintain reliability while financing a cleaner portfolio before carbon costs
and rising demand erode the company's position.
