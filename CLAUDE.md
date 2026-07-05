# mirror.py-kaist-status

This repository builds a `status`-type plug-in for [mirror.py](https://github.com/sparcs-kaist/mirror.py) that emits a status JSON file in the legacy KAIST `geoul` format. The target schema is captured verbatim in [`example.json`](example.json) — the plug-in must produce output structurally identical to that file.

## What this plug-in does

mirror.py's built-in web status JSON has a different shape from the historical KAIST `ftp.kaist.ac.kr/geoul/...` schema. To keep existing consumers working, this plug-in writes its own additional file (default `/var/www/mirror/kaist-status.json`) on every package status change, formatted per `example.json`. mirror.py's own `status.json` is **not** modified.

This is a textbook use case for the mirror.py plug-in framework's `status` plug-in **outputs** mode (see `reference/PLUGINS.md` Mode 3).

## Required mirror.py version

`mirror.py >= 1.3.0`. The core `outputs=[StatusOutput(...)]` mode dates back to
1.0.0 (introduced at rc11), but the plug-in now also declares `api_version=(1,0)`
and implements the `create_config` callback — both are **1.3.0-only** APIs
(passing them to the factories on older cores raises `TypeError`, and
`ConfigCreateResult` does not exist there). Hence the dependency floor is `>=1.3.0`.

Verified compatible with mirror.py `1.3.0`: the `status_plugin`/`StatusOutput`
signatures, the `build(packages)` call contract, all `Package`/`StatusInfo`
fields used by the mapping table below, the `api_version` gate
(`PLUGIN_API_VERSION == (1, 0)`), and the `create_config` contract are as
expected. Test suite passes (`pytest`, 36 passed).

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
| `package.<id>.status.updated.href` | `pkg.statusinfo.lastsuccesslog` | the gzipped log path — rewritten to the public URL (see "Log href rewriting") |
| `package.<id>.status.updated.timestamp` | `pkg.statusinfo.lastsuccesstime` | float epoch → ISO 8601 |
| `package.<id>.status.updating.href` | `pkg.statusinfo.runninglog` | only present while syncing — rewritten to the public URL |
| `package.<id>.status.updating.timestamp` | derived from current sync start | timestamp the running entry |
| `package.<id>.status.failed.href` | `pkg.statusinfo.lasterrorlog` | rewritten to the public URL |
| `package.<id>.status.failed.timestamp` | `pkg.statusinfo.lasterrortime` | float epoch → ISO 8601 |
| `package.<id>.status.failed.count` | `pkg.statusinfo.errorcount` | KAIST schema stores as **string** (`"29"`), not int — convert |
| `package.<id>.status.usage` | n/a | always `null` (mirror.py doesn't track yet) |
| `package.<id>.status.size` | n/a | always `null` |

Edge cases visible in `example.json`:
- A package with no `sync` block at all (e.g. `geoul`, `misc`, `hangul`) — these have no upstream. mirror.py's `local` synctype maps here; emit no `sync` key.
- `hidden` is `"true"` (the JSON string) when set, else `null`.
- `failed.count` is a string.

## Log href rewriting

The `lastsuccesslog`/`runninglog`/`lasterrorlog` values mirror.py records are
**local POSIX paths** under the daemon's `logger.packagefileformat.base`
directory. These must never be written verbatim to the public status document —
the schema's `href` fields are URLs served externally through nginx.

The plug-in rewrites each log `href` by swapping the local base prefix for the
operator-configured public URL base, preserving the per-package
folder/filename tail:

```
base (mirror.conf.logger.packagefileformat.base): /var/log/mirror/packages
log_base_url (this plug-in's config):              http://ftp.kaist.ac.kr/geoul/sync

/var/log/mirror/packages/2026/05/06/10:42:01.154793368.ArchLinux.log.gz
  -> http://ftp.kaist.ac.kr/geoul/sync/2026/05/06/10:42:01.154793368.ArchLinux.log.gz
```

- The local base is read automatically from `mirror.conf.logger["packagefileformat"]["base"]`; the operator only configures the public URL base.
- When `log_base_url` is unset (or an href is not under the base), the original value passes through unchanged.

## Plug-in configuration

Recent mirror.py (commits on `feat/plugin-config-files`, post-1.2.2) moved
per-plug-in settings **out of `config.json`** into a separate file. The
`config` sub-key under `settings.plugins.<name>` is no longer supported.

1. **Enable the plug-in** in `config.json` — enable-only shape, no `config` key:

   ```json
   "settings": {
     "plugins": {
       "kaist-status": { "enabled": true }
     }
   }
   ```

2. **Put settings in a sibling file** next to `config.json`, named
   `kaist.json` (the plug-in sets `config_filename="kaist.json"`, so for a
   `/etc/mirror/config.json` deployment the config file is
   `/etc/mirror/kaist.json`). `get_config()` reads it lazily on every status
   update — no daemon restart needed for value changes:

   ```json
   {
     "output_path": "/var/www/mirror/kaist-status.json",
     "log_base_url": "http://ftp.kaist.ac.kr/geoul/sync"
   }
   ```

| Key | Default | Meaning |
|---|---|---|
| `output_path` | `/var/www/mirror/kaist-status.json` | Where the generated KAIST status JSON is written (overrides `StatusOutput.default_path` via `config_path_key`). |
| `log_base_url` | unset | Public URL base that replaces the local `packagefileformat.base` prefix in every log `href`. |

Note the two distinct files: `/etc/mirror/kaist.json` is the plug-in's **config
input** (variables defined here), while `output_path` points at the **generated
output** the plug-in writes (the geoul status document nginx serves).

The plug-in reads both values through `mirror.plugin.get_config("kaist-status")`.

### Scaffolding the config file

Rather than hand-writing `kaist.json`, operators can generate a placeholder via
the 1.3.0 CLI:

```
mirror plugin config create kaist-status [--config /etc/mirror/config.json] [--force]
```

This calls the plug-in's `create_config` callback, which writes
`<config dir>/kaist.json` (the `config.json` directory, falling back to
`/etc/mirror` when the CLI does not expose `CONFIG_PATH`). The generated file
carries placeholder values — `output_path` defaults to
`/var/www/mirror/kaist-status.json` and `log_base_url` is empty, so log hrefs
pass through as local paths until the operator fills it in. An existing file is
left untouched unless `--force` is given.

### API version

The plug-in declares `api_version=(1, 0)` (== `PLUGIN_API_VERSION` on 1.3.0), so
`load_external_plugins` accepts it without the "does not declare api_version"
deprecation warning.

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
        config_filename="kaist.json",
    )
```

`pyproject.toml` declaration:

```toml
[project]
name = "mirror.py-kaist-status"
version = "0.1.0"
dependencies = ["mirror.py>=1.3.0"]

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
