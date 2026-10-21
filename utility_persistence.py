"""Versioned, atomic JSON saves. Never unpickle or import classes from a save.

Every instance attribute is serialized automatically, including future additions.
Schema changes belong in MIGRATIONS; new required fields need explicit defaults in
the relevant migration. Unknown attributes on known objects survive a round trip.
"""

import json
import math
import os
import random
import tempfile
from datetime import datetime, timezone

FORMAT = 'gridline-utility-save'
SCHEMA_VERSION = 1
MAX_SAVE_BYTES = 64 * 1024 * 1024
MIGRATIONS = {}  # old version -> function returning the next-version document


class SaveError(ValueError):
    pass


def encode_graph(root, classes):
    allowed = {cls: name for name, cls in classes.items()}
    objects, seen = [], {}
    def encode(value, depth=0):
        if depth > 100:
            raise SaveError('Save data is nested too deeply.')
        if value is None or isinstance(value, (str, bool, int)):
            return value
        if isinstance(value, float):
            if math.isnan(value):
                raise SaveError('Cannot save a non-numeric account value.')
            return value if math.isfinite(value) else {'$float': 'inf' if value > 0 else '-inf'}
        if isinstance(value, tuple):
            return {'$tuple': [encode(item, depth + 1) for item in value]}
        if isinstance(value, list):
            return [encode(item, depth + 1) for item in value]
        if isinstance(value, dict):
            if any(not isinstance(key, str) or key.startswith('$') for key in value):
                raise SaveError('Save dictionaries must have ordinary string keys.')
            return {key: encode(item, depth + 1) for key, item in value.items()}
        if type(value) not in allowed:
            raise SaveError(f'Unsupported game-state type: {type(value).__name__}')
        if id(value) in seen:
            return {'$ref': seen[id(value)]}
        index = len(objects)
        seen[id(value)] = index
        record = {'type': allowed[type(value)], 'fields': {}}
        objects.append(record)
        record['fields'] = encode(vars(value), depth + 1)
        return {'$ref': index}
    root_ref = encode(root)
    return {'root': root_ref, 'objects': objects}


def decode_graph(graph, classes):
    records = graph['objects']
    if not isinstance(records, list) or len(records) > 100_000:
        raise SaveError('Invalid object count.')
    objects = []
    for record in records:
        name = record['type']
        if name not in classes:
            raise SaveError(f'This game version does not support saved type {name!r}.')
        objects.append(classes[name].__new__(classes[name]))
    def decode(value, depth=0):
        if depth > 100:
            raise SaveError('Save data is nested too deeply.')
        if isinstance(value, list):
            return [decode(item, depth + 1) for item in value]
        if isinstance(value, dict):
            if '$ref' in value:
                index = value['$ref']
                if type(index) is not int or not 0 <= index < len(objects):
                    raise SaveError('Invalid saved reference.')
                return objects[index]
            if '$float' in value:
                if value['$float'] not in ('inf', '-inf'):
                    raise SaveError('Invalid ratio value.')
                return float(value['$float'])
            if '$tuple' in value:
                return tuple(decode(item, depth + 1) for item in value['$tuple'])
            if any(key.startswith('$') for key in value):
                raise SaveError('Unsupported save encoding.')
            return {key: decode(item, depth + 1) for key, item in value.items()}
        if isinstance(value, float) and not math.isfinite(value):
            raise SaveError('Invalid JSON numeric value.')
        return value
    for obj, record in zip(objects, records):
        fields = decode(record['fields'])
        if not isinstance(fields, dict) or any(key.startswith('__') for key in fields):
            raise SaveError('Invalid object fields.')
        if any(callable(getattr(type(obj), key, None)) for key in fields):
            raise SaveError('A saved field cannot replace a game method.')
        obj.__dict__.update(fields)
    return decode(graph['root'])


def save_game(session, path, classes, game_version):
    document = dict(format=FORMAT, schema_version=SCHEMA_VERSION, game_version=game_version,
                    saved_at=datetime.now(timezone.utc).isoformat(),
                    graph=encode_graph(session, classes),
                    random_state=encode_graph(random.getstate(), classes))
    encoded = json.dumps(document, ensure_ascii=False, allow_nan=False, separators=(',', ':'))
    if len(encoded.encode('utf-8')) > MAX_SAVE_BYTES:
        raise SaveError('Save exceeds the supported size limit.')
    target = os.path.abspath(os.fspath(path))
    temp_path = None
    try:
        with tempfile.NamedTemporaryFile('w', encoding='utf-8', dir=os.path.dirname(target),
                                         prefix='.gridline-save-', suffix='.tmp', delete=False) as stream:
            temp_path = stream.name
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp_path, target)  # interrupted writes do not corrupt the previous save
    finally:
        if temp_path is not None and os.path.exists(temp_path):
            os.unlink(temp_path)


def load_game(path, classes, validate):
    try:
        with open(path, 'r', encoding='utf-8') as stream:
            raw = stream.read(MAX_SAVE_BYTES + 1)
        if len(raw.encode('utf-8')) > MAX_SAVE_BYTES:
            raise SaveError('Save exceeds the supported size limit.')
        document = json.loads(raw)
        if document.get('format') != FORMAT:
            raise SaveError('This is not a Gridline save file.')
        version = document['schema_version']
        if type(version) is not int or version < 1 or version > SCHEMA_VERSION:
            raise SaveError('Unsupported save version. A newer game may be required.')
        while version < SCHEMA_VERSION:
            if version not in MIGRATIONS:
                raise SaveError('This older save requires a migration that is not installed.')
            document = MIGRATIONS[version](document)
            version += 1
            document['schema_version'] = version
        session = decode_graph(document['graph'], classes)
        # Random-state tuples contain no class objects; use the same safe decoder.
        rng = decode_graph(document['random_state'], classes)
        random.Random().setstate(rng)  # validate without touching the running game
        validate(session)
        random.setstate(rng)
        return session
    except SaveError:
        raise
    except (ValueError, KeyError, TypeError, AttributeError, IndexError, RecursionError) as exc:
        raise SaveError('The save is incomplete or damaged; the current game was not replaced.') from exc
