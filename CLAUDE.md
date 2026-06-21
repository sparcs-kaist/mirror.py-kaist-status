# mirror.py-kaist-status

This repository builds a `status`-type plug-in for [mirror.py](https://github.com/sparcs-kaist/mirror.py) that emits a status JSON file in the legacy KAIST `geoul` format. The target schema is captured verbatim in [`example.json`](example.json) — the plug-in must produce output structurally identical to that file.

## What this plug-in does

mirror.py's built-in web status JSON has a different shape from the historical KAIST `ftp.kaist.ac.kr/geoul/...` schema. To keep existing consumers working, this plug-in writes its own additional file (e.g. `/var/www/mirror/kaist-status.json`) on every package status change, formatted per `example.json`. mirror.py's own `status.json` is **not** modified.

This is a textbook use case for the mirror.py plug-in framework's `status` plug-in **outputs** mode (see `reference/PLUGINS.md` Mode 3).

## Required mirror.py version

`mirror.py >= 1.0.0` — the `outputs=[StatusOutput(...)]` mode in the `status` plug-in API (introduced at rc11) is part of the stable 1.0.0 line. Earlier prereleases (rc10 and below) only supported additive `extend_*_fields`, which cannot express a different document shape.

Verified compatible with mirror.py `1.2.2` (latest as of 2026-06-21): the `status_plugin`/`StatusOutput` signatures, the `build(packages)` call contract, and all `Package`/`StatusInfo` fields used by the mapping table below are unchanged. Test suite passes (`pytest`, 20 passed).

## Distribution name

`mirror.py-kaist-status` (with the canonical dot-shaped prefix, matching the
host package). Internal plug-in `name` is `kaist-status`.

## Schema mapping (mirror.py → KAIST geoul)

Use this table when implementing the build callable. Source side is the
`mirror.structure.Package` object you receive from
`StatusOutput.build(packages: Iterable[Package])`.

| KAIST field | Source on `Package` | Notes |
|---|---|---|
| `timestamp` (top-level) | `time.time()` → ISO 8601 `+09:00` | wrap in a small helper |
| `package.<id>.id`, `name` | `pkg.pkgid`, `pkg.name` | direct copy |
| `package.<id>.hidden` | `pkg.settings.hidden` | KAIST schema uses `null` or `"true"` (string), not bool — convert |
| `package.<id>.link` | `pkg.link` (list of `Link`) | each `Link.to_dict()` already gives `{rel, href}` |
| `package.<id>.sync.source` | `pkg.settings.src` | direct copy |
| `package.<id>.sync.frequency` | `pkg.syncrate` (int seconds) | convert via `mirror.toolbox.format_iso_duration(...)` → "PT10M" etc. omit the `sync` key entirely if no source (see `geoul`/`misc`/`hangul` packages in example.json) |
| `package.<id>.status.updated.href` | `pkg.statusinfo.lastsuccesslog` | the gzipped log path |
| `package.<id>.status.updated.timestamp` | `pkg.statusinfo.lastsuccesstime` | float epoch → ISO 8601 |
| `package.<id>.status.updating.href` | `pkg.statusinfo.runninglog` | only present while syncing |
| `package.<id>.status.updating.timestamp` | derived from current sync start | timestamp the running entry |
| `package.<id>.status.failed.href` | `pkg.statusinfo.lasterrorlog` | |
| `package.<id>.status.failed.timestamp` | `pkg.statusinfo.lasterrortime` | float epoch → ISO 8601 |
| `package.<id>.status.failed.count` | `pkg.statusinfo.errorcount` | KAIST schema stores as **string** (`"29"`), not int — convert |
| `package.<id>.status.usage` | n/a | always `null` (mirror.py doesn't track yet) |
| `package.<id>.status.size` | n/a | always `null` |

Edge cases visible in `example.json`:
- A package with no `sync` block at all (e.g. `geoul`, `misc`, `hangul`) — these have no upstream. mirror.py's `local` synctype maps here; emit no `sync` key.
- `hidden` is `"true"` (the JSON string) when set, else `null`.
- `failed.count` is a string.

## Plug-in skeleton (sketch — adapt)

```python
# mirror_plugin_kaist_status/__init__.py
from datetime import datetime, timezone, timedelta

import mirror.toolbox
from mirror.plugin import status_plugin, StatusOutput

NAME = "kaist-status"
KST = timezone(timedelta(hours=9))


def _iso_kst(epoch: float) -> str:
    return datetime.fromtimestamp(epoch, KST).isoformat(timespec="seconds")


def _shape_package(pkg) -> dict:
    ...  # apply the mapping table above


def build_kaist_payload(packages) -> dict:
    return {
        "timestamp": datetime.now(KST).isoformat(timespec="seconds"),
        "package": {p.pkgid: _shape_package(p) for p in packages},
    }


def plugin():
    return status_plugin(
        name=NAME,
        outputs=[StatusOutput(
            name="kaist-status",
            default_path="/var/www/mirror/kaist-status.json",
            build=build_kaist_payload,
            config_path_key="output_path",
        )],
    )
```

`pyproject.toml` declaration:

```toml
[project]
name = "mirror.py-kaist-status"
version = "0.1.0"
dependencies = ["mirror.py>=1.0.0"]

[project.entry-points."mirror.status"]
kaist-status = "mirror_plugin_kaist_status:plugin"
```

## Reference materials in this repo

- `reference/PLUGINS.md` — verbatim snapshot of `docs/PLUGINS.md` from
  mirror.py at rc11. The authoritative source is `../mirror.py/docs/PLUGINS.md`
  if you have the sibling repo checked out; otherwise this snapshot is
  current as of 2026-05-06.
- `reference/echo-example/` — the bundled `mirror-plugin-echo` example from
  mirror.py. Useful as a structural template for `pyproject.toml`,
  `__init__.py` shape, and entry-point declaration. **Note**: echo is an
  `event` plug-in; this repo is a `status` plug-in. The framework patterns
  (factory, NAME constant, get_config, entry-point form) carry over, but the
  inner contract is different.
- `example.json` — the target output schema. Treat as the integration test
  fixture: produced JSON should structurally match this file.

## Output schema invariant

Any change to the produced JSON shape must keep `example.json` as the
canonical reference. If KAIST's downstream consumers want a new field, update
both the implementation and `example.json` together.

## Testing

Suggested approach (no integration with the mirror.py daemon required for
unit tests):

1. Pure unit tests for `_shape_package` and `build_kaist_payload` using
   `MagicMock` Package objects. Compare output to a canonical sample loaded
   from `example.json`.
2. End-to-end smoke test: install this package alongside mirror.py in a venv,
   start the daemon against a tiny config with a few packages, verify the
   output file appears and matches expected shape.

## Trust model

This plug-in runs in-process at the daemon's privilege level (no sandbox).
Avoid network calls, avoid reading sensitive paths. The build callable should
be pure-ish: it receives `Package` objects and returns a dict.

## Repository layout (to be created by the new session)

```
mirror.py-kaist-status/
├── pyproject.toml
├── README.md
├── LICENSE                        (already present)
├── example.json                   (already present — target schema)
├── CLAUDE.md                      (this file)
├── reference/
│   ├── PLUGINS.md                 (mirror.py author guide snapshot)
│   └── echo-example/              (mirror-plugin-echo reference)
├── mirror_plugin_kaist_status/
│   └── __init__.py
└── tests/
    └── test_*.py
```
