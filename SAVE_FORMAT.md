# Gridline save format and compatibility

Version 2 saves use UTF-8 JSON with format identifier `gridline-utility-save`
and schema version `1`. The gameplay version and schema version are separate:
a gameplay release need not change the schema unless compatibility changes.

## Contents

The envelope contains `format`, `schema_version`, `game_version`, `saved_at`,
`graph`, and `random_state`. The object graph records registered class names,
all instance fields, and references between model objects. References preserve
shared objects such as the economy used by the player, regulator, and calendar.

The complete session includes plants and their individual cost/depreciation
records, battery energy and degradation, ongoing construction, debt and
maturities, borrowing allowances, pending and active power contracts, cash-flow
ledgers, equity trading limits, shareholder state, credit memory, economic and
carbon-policy state, immutable monthly statements, and the remaining game
horizon. GUI saves also include graph history and the event log. Window
positions and open dialogs are not simulation state and are not saved.

The random-generator state is restored only after the save validates. With
the same game code and subsequent actions, loading continues the same random
sequence. Future releases that change simulation rules may change outcomes.

## Adding future features

1. Keep persistent gameplay state on the session or its registered model
   objects. The encoder automatically includes new instance attributes;
   avoid hidden module globals or GUI-only fields for game mechanics.
2. Use JSON-compatible scalar values, lists, tuples, dictionaries with ordinary
   string keys, or registered model objects. Register each new state class in
   `UtilityGameSession.save_classes()`. Do not store widgets or callbacks.
3. When new required fields, renamed classes, or changed meanings would make
   existing saves incomplete, increment `SCHEMA_VERSION`. Add a pure migration
   to `MIGRATIONS[old_version]` that returns the next-version document.
   Initialize new fields explicitly without discarding old history or rerolling
   economic events. Migrations run sequentially.
4. Extend `validate_loaded_game()` for new critical invariants. Unknown
   attributes on known classes should survive a load/save round trip.
5. When accounting changes, update monthly snapshots and statement
   aggregations together. Migrate historical entries or explicitly mark
   unavailable values; never fabricate old actual results.
6. Test an old-format fixture through migration, a complete current-state
   round trip, and deterministic continuation. Include pending actions,
   partially completed projects, battery charge, share-trading allowances,
   and shareholder/credit history.

Schema 1 is the first save format, so no older migrations are required yet.
Unsupported newer schemas are rejected with an explanation; extensibility
does not mean an older game can safely interpret every future mechanic.

## Integrity and safety

Saves are written to a temporary file in the target directory, flushed, then
atomically replace the destination. A failed replacement leaves the previous
save intact. The loader enforces a 64 MiB size limit, nesting/object limits,
valid references, registered class names, and essential state checks.

There is no pickle loading, execution of saved code, or importing class names
from files. Non-finite ratios use tagged JSON representations; invalid numeric
data is rejected. Invalid saves do not replace the current session or change
its random sequence.

Save files are plain text, not encrypted or cheat-proof. Keep backup copies
before upgrading or manually editing them. The repository ignores
`*.gridline.json` saves so private playthroughs are not committed by accident.
