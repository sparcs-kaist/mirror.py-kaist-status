"""mirror.py status plug-in producing a KAIST geoul-format status JSON file.

This plug-in registers an additional ``StatusOutput`` that mirror.py writes on
every package status change. The shape matches the legacy
``ftp.kaist.ac.kr/geoul`` status document captured in ``example.json``.
"""
from __future__ import annotations

from datetime import datetime, timezone, timedelta
from typing import Iterable, Optional

import mirror.toolbox
from mirror.plugin import StatusOutput, status_plugin

NAME = "kaist-status"
DEFAULT_OUTPUT_PATH = "/var/www/mirror/kaist-status.json"
CONFIG_PATH_KEY = "output_path"
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


def build_updated_block(statusinfo) -> Optional[dict]:
    """Render the ``status.updated`` entry, or None if the package never synced.

    Args:
        statusinfo: ``Package.StatusInfo`` exposing ``lastsuccesstime`` and ``lastsuccesslog``.

    Return:
        block(dict | None): ``{"href": ..., "timestamp": ...}`` when at least one
            success indicator is present, otherwise None.
    """
    last_time = statusinfo.lastsuccesstime or 0.0
    last_log = statusinfo.lastsuccesslog
    if last_time <= 0 and not last_log:
        return None
    return {
        "href": last_log,
        "timestamp": format_iso_kst(last_time) if last_time > 0 else None,
    }


def build_updating_block(pkg) -> Optional[dict]:
    """Render the ``status.updating`` entry, or None if no sync is in progress.

    The ``updating.timestamp`` is derived from ``pkg.timestamp`` (milliseconds),
    which mirror.py sets at the moment a status transition occurs.

    Args:
        pkg: ``mirror.structure.Package`` instance.

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
        "href": running,
        "timestamp": format_iso_kst(timestamp_seconds) if timestamp_seconds > 0 else None,
    }


def build_failed_block(statusinfo) -> Optional[dict]:
    """Render the ``status.failed`` entry, or None if the package has no error history.

    Args:
        statusinfo: ``Package.StatusInfo`` instance.

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
        "href": last_error_log,
        "timestamp": format_iso_kst(last_error_time) if last_error_time > 0 else None,
        "count": str(error_count),
    }


def build_status_block(pkg) -> dict:
    """Compose the per-package ``status`` block per KAIST schema.

    Args:
        pkg: ``mirror.structure.Package`` instance.

    Return:
        block(dict): Mapping with ``updated``/``updating``/``failed``/``usage``/``size`` keys.
    """
    return {
        "updated": build_updated_block(pkg.statusinfo),
        "updating": build_updating_block(pkg),
        "failed": build_failed_block(pkg.statusinfo),
        "usage": None,
        "size": None,
    }


def shape_package(pkg) -> dict:
    """Convert a mirror.py Package into the KAIST geoul package dict.

    Args:
        pkg: ``mirror.structure.Package`` instance.

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

    payload["status"] = build_status_block(pkg)
    return payload


def build_kaist_payload(packages: Iterable) -> dict:
    """Build the top-level KAIST status JSON payload.

    Args:
        packages(Iterable): Iterable of ``mirror.structure.Package`` instances.

    Return:
        payload(dict): Top-level KAIST status document with ``timestamp`` and
            ``package`` keys, where ``package`` is keyed by ``pkgid``.
    """
    return {
        "timestamp": format_now_iso_kst(),
        "package": {pkg.pkgid: shape_package(pkg) for pkg in packages},
    }


def plugin():
    """Entry-point factory consumed by mirror.plugin.load_external_plugins.

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
    )
