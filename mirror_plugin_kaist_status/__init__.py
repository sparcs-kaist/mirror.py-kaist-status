"""mirror.py status plug-in producing a KAIST geoul-format status JSON file.

This plug-in registers an additional ``StatusOutput`` that mirror.py writes on
every package status change. The shape matches the legacy
``ftp.kaist.ac.kr/geoul`` status document captured in ``example.json``.

Log paths recorded by mirror.py are local POSIX paths under the daemon's
``packagefileformat.base`` directory. They must never be written verbatim to
the public status document. When the operator sets ``log_base_url`` in the
plug-in config, every log ``href`` has its local base prefix swapped for that
externally exposed (nginx-served) URL base, keeping the per-package
folder/filename tail intact.
"""
from __future__ import annotations

from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Iterable, Optional

import mirror.toolbox
from mirror.plugin import StatusOutput, status_plugin

NAME = "kaist-status"
DEFAULT_OUTPUT_PATH = "/var/www/mirror/kaist-status.json"
CONFIG_FILENAME = "kaist.json"
CONFIG_PATH_KEY = "output_path"
LOG_BASE_URL_KEY = "log_base_url"
KST = timezone(timedelta(hours=9))


def format_iso_kst(epoch: float) -> str:
    """Convert a POSIX epoch timestamp to an ISO 8601 string in KST.

    Args:
        epoch(float): POSIX epoch seconds.

    Return:
        iso(str): ISO 8601 timestamp with second precision and ``+09:00`` offset.
    """
    return datetime.fromtimestamp(epoch, KST).isoformat(timespec="seconds")


def format_now_iso_kst() -> str:
    """Return the current time as an ISO 8601 KST timestamp.

    Return:
        iso(str): Current time formatted with second precision and ``+09:00`` offset.
    """
    return datetime.now(KST).isoformat(timespec="seconds")


def format_hidden_flag(hidden: bool) -> Optional[str]:
    """Convert a boolean hidden flag to KAIST schema representation.

    Args:
        hidden(bool): Whether the package is hidden.

    Return:
        value(str | None): The string ``"true"`` when hidden, otherwise None.
    """
    return "true" if hidden else None


def format_links(links: Iterable) -> list[dict]:
    """Render a sequence of Package.Link instances into KAIST link dicts.

    Args:
        links(Iterable): Iterable of objects exposing ``rel`` and ``href`` attributes.

    Return:
        items(list[dict]): List of ``{"rel": ..., "href": ...}`` dicts in input order.
    """
    return [{"rel": link.rel, "href": link.href} for link in links]


def resolve_log_base_path() -> Optional[str]:
    """Read the daemon's local log base directory from mirror.py config.

    The value is taken from ``mirror.conf.logger["packagefileformat"]["base"]``
    and resolved to an absolute path so it matches the resolved log paths that
    mirror.py stores in ``StatusInfo``.

    Return:
        base(str | None): Absolute local log base path, or None when the config
            is unavailable or unset.
    """
    try:
        import mirror

        base = mirror.conf.logger["packagefileformat"]["base"]
    except (AttributeError, KeyError, TypeError):
        return None
    if not base:
        return None
    return str(Path(base).resolve(strict=False))


def get_log_base_url() -> Optional[str]:
    """Read the externally exposed log URL base from the plug-in config.

    Return:
        base_url(str | None): The operator-configured ``log_base_url`` value, or
            None when the plug-in has no config block or the key is unset.
    """
    try:
        import mirror.plugin

        cfg = mirror.plugin.get_config(NAME)
    except (KeyError, AttributeError, TypeError):
        return None
    return cfg.get(LOG_BASE_URL_KEY) or None


def convert_log_href(
    href: Optional[str],
    base_path: Optional[str],
    base_url: Optional[str],
) -> Optional[str]:
    """Rewrite a local POSIX log path into an externally exposed URL.

    The local ``base_path`` prefix is swapped for ``base_url`` while the
    per-package folder/filename tail is preserved. When ``base_url`` is unset,
    or the href does not live under ``base_path``, the original value is
    returned unchanged.

    Args:
        href(str | None): Local log path recorded by mirror.py.
        base_path(str | None): Absolute local log base directory to strip.
        base_url(str | None): External URL base to prepend.

    Return:
        href(str | None): Rewritten URL, or the original href when no rewrite applies.
    """
    if not href or not base_url:
        return href
    if base_path and href.startswith(base_path):
        remainder = href[len(base_path):]
        return base_url.rstrip("/") + "/" + remainder.lstrip("/")
    return href


def build_sync_block(pkg) -> Optional[dict]:
    """Render the ``sync`` block for a package, or None when no upstream exists.

    Args:
        pkg: ``mirror.structure.Package`` instance.

    Return:
        block(dict | None): ``{"source": ..., "frequency": ...}`` mapping with the
            ``frequency`` key omitted when ``syncrate`` is 0; None when the package
            has no upstream (synctype is ``local`` or ``settings.src`` is empty).
    """
    src = getattr(pkg.settings, "src", None) or ""
    if pkg.synctype == "local" or not src:
        return None

    block: dict = {"source": src}
    syncrate = getattr(pkg, "syncrate", 0) or 0
    if syncrate > 0:
        block["frequency"] = mirror.toolbox.format_iso_duration(syncrate)
    return block


def build_updated_block(
    statusinfo,
    base_path: Optional[str] = None,
    base_url: Optional[str] = None,
) -> Optional[dict]:
    """Render the ``status.updated`` entry, or None if the package never synced.

    Args:
        statusinfo: ``Package.StatusInfo`` exposing ``lastsuccesstime`` and ``lastsuccesslog``.
        base_path(str | None): Local log base path to rewrite (see convert_log_href).
        base_url(str | None): External log URL base to rewrite to.

    Return:
        block(dict | None): ``{"href": ..., "timestamp": ...}`` when at least one
            success indicator is present, otherwise None.
    """
    last_time = statusinfo.lastsuccesstime or 0.0
    last_log = statusinfo.lastsuccesslog
    if last_time <= 0 and not last_log:
        return None
    return {
        "href": convert_log_href(last_log, base_path, base_url),
        "timestamp": format_iso_kst(last_time) if last_time > 0 else None,
    }


def build_updating_block(
    pkg,
    base_path: Optional[str] = None,
    base_url: Optional[str] = None,
) -> Optional[dict]:
    """Render the ``status.updating`` entry, or None if no sync is in progress.

    The ``updating.timestamp`` is derived from ``pkg.timestamp`` (milliseconds),
    which mirror.py sets at the moment a status transition occurs.

    Args:
        pkg: ``mirror.structure.Package`` instance.
        base_path(str | None): Local log base path to rewrite (see convert_log_href).
        base_url(str | None): External log URL base to rewrite to.

    Return:
        block(dict | None): ``{"href": ..., "timestamp": ...}`` when a running log
            is present, otherwise None.
    """
    running = pkg.statusinfo.runninglog
    if not running:
        return None

    timestamp_ms = getattr(pkg, "timestamp", 0.0) or 0.0
    timestamp_seconds = timestamp_ms / 1000.0 if timestamp_ms else 0.0
    return {
        "href": convert_log_href(running, base_path, base_url),
        "timestamp": format_iso_kst(timestamp_seconds) if timestamp_seconds > 0 else None,
    }


def build_failed_block(
    statusinfo,
    base_path: Optional[str] = None,
    base_url: Optional[str] = None,
) -> Optional[dict]:
    """Render the ``status.failed`` entry, or None if the package has no error history.

    Args:
        statusinfo: ``Package.StatusInfo`` instance.
        base_path(str | None): Local log base path to rewrite (see convert_log_href).
        base_url(str | None): External log URL base to rewrite to.

    Return:
        block(dict | None): ``{"href": ..., "timestamp": ..., "count": str}``
            when at least one error indicator is present, otherwise None.
            ``count`` is rendered as a string per KAIST schema.
    """
    error_count = statusinfo.errorcount or 0
    last_error_time = statusinfo.lasterrortime or 0.0
    last_error_log = statusinfo.lasterrorlog
    if error_count <= 0 and last_error_time <= 0 and not last_error_log:
        return None
    return {
        "href": convert_log_href(last_error_log, base_path, base_url),
        "timestamp": format_iso_kst(last_error_time) if last_error_time > 0 else None,
        "count": str(error_count),
    }


def build_status_block(
    pkg,
    base_path: Optional[str] = None,
    base_url: Optional[str] = None,
) -> dict:
    """Compose the per-package ``status`` block per KAIST schema.

    Args:
        pkg: ``mirror.structure.Package`` instance.
        base_path(str | None): Local log base path to rewrite (see convert_log_href).
        base_url(str | None): External log URL base to rewrite to.

    Return:
        block(dict): Mapping with ``updated``/``updating``/``failed``/``usage``/``size`` keys.
    """
    return {
        "updated": build_updated_block(pkg.statusinfo, base_path, base_url),
        "updating": build_updating_block(pkg, base_path, base_url),
        "failed": build_failed_block(pkg.statusinfo, base_path, base_url),
        "usage": None,
        "size": None,
    }


def shape_package(
    pkg,
    base_path: Optional[str] = None,
    base_url: Optional[str] = None,
) -> dict:
    """Convert a mirror.py Package into the KAIST geoul package dict.

    Args:
        pkg: ``mirror.structure.Package`` instance.
        base_path(str | None): Local log base path to rewrite (see convert_log_href).
        base_url(str | None): External log URL base to rewrite to.

    Return:
        payload(dict): The KAIST per-package representation.
    """
    payload: dict = {
        "id": pkg.pkgid,
        "name": pkg.name,
        "hidden": format_hidden_flag(getattr(pkg.settings, "hidden", False)),
        "link": format_links(pkg.link),
    }

    sync_block = build_sync_block(pkg)
    if sync_block is not None:
        payload["sync"] = sync_block

    payload["status"] = build_status_block(pkg, base_path, base_url)
    return payload


def build_kaist_payload(packages: Iterable) -> dict:
    """Build the top-level KAIST status JSON payload.

    Log hrefs are rewritten from local POSIX paths to the externally exposed
    URL base when the operator has configured ``log_base_url``.

    Args:
        packages(Iterable): Iterable of ``mirror.structure.Package`` instances.

    Return:
        payload(dict): Top-level KAIST status document with ``timestamp`` and
            ``package`` keys, where ``package`` is keyed by ``pkgid``.
    """
    base_path = resolve_log_base_path()
    base_url = get_log_base_url()
    return {
        "timestamp": format_now_iso_kst(),
        "package": {
            pkg.pkgid: shape_package(pkg, base_path, base_url) for pkg in packages
        },
    }


def plugin():
    """Entry-point factory consumed by mirror.plugin.load_external_plugins.

    The per-plug-in config (``output_path``, ``log_base_url``) is read from
    ``kaist.json`` sitting next to the daemon's ``config.json`` (i.e.
    ``/etc/mirror/kaist.json`` for a ``/etc/mirror/config.json`` deployment),
    via the ``config_filename`` override.

    Return:
        record(mirror.plugin.PluginRecord): Status plug-in record declaring a
            single ``StatusOutput`` whose target path can be overridden through
            the plug-in config's ``output_path`` key.
    """
    return status_plugin(
        name=NAME,
        outputs=[
            StatusOutput(
                name=NAME,
                default_path=DEFAULT_OUTPUT_PATH,
                build=build_kaist_payload,
                config_path_key=CONFIG_PATH_KEY,
            ),
        ],
        config_filename=CONFIG_FILENAME,
    )
