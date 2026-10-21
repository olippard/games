# Utility simulator maintenance

- Preserve user changes and keep changes scoped to the requested game work.
- Treat save compatibility as part of every gameplay change. Read
  `SAVE_FORMAT.md` before modifying persistent state.
- Keep useful game state on registered session/model instances so it is
  automatically saved. Do not leave mechanics only in GUI widgets or globals.
- For new required fields or changed state semantics, increment the save schema
  and add explicit migrations and tests. Preserve unknown fields and old
  financial history. Never load arbitrary classes or pickle data from saves.
- Extend immutable monthly snapshots, period reports, and accounting
  reconciliation tests when adding financial transactions.
- Verify new features survive save/load and deterministic continued play.
- Run `python3 -m unittest discover -p 'test_utility*.py'` before release.
- Keep `utility.py`, `utility_reports.py`, and `utility_persistence.py` together.
  Do not commit personal saves, caches, or generated temporary files.
