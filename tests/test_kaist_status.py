"""Unit tests for mirror_plugin_kaist_status.

Each test reproduces a representative package from ``example.json`` using
``SimpleNamespace`` stand-ins for ``mirror.structure.Package`` and asserts
that ``shape_package`` (and ``build_kaist_payload``) produces the identical
dictionary as the example fixture.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Optional

from mirror_plugin_kaist_status import (
    build_kaist_payload,
    build_failed_block,
    build_sync_block,
    build_updated_block,
    build_updating_block,
    convert_log_href,
    format_hidden_flag,
    format_iso_kst,
    format_links,
    plugin,
    shape_package,
)


EXAMPLE_FIXTURE = Path(__file__).resolve().parent.parent / "reference" / "example.json"


def load_fixture() -> dict:
    """Load the canonical ``example.json`` fixture."""
    with EXAMPLE_FIXTURE.open(encoding="utf-8") as fp:
        return json.load(fp)


def parse_iso_to_epoch(iso: str) -> float:
    """Parse an ISO 8601 KST timestamp from the fixture back into POSIX epoch seconds."""
    return datetime.fromisoformat(iso).timestamp()


def make_link(rel: str, href: str) -> SimpleNamespace:
    """Create a stand-in for ``Package.Link``."""
    return SimpleNamespace(rel=rel, href=href)


def make_status_info(
    *,
    lastsuccesslog: Optional[str] = None,
    lastsuccesstime: float = 0.0,
    runninglog: Optional[str] = None,
    lasterrorlog: Optional[str] = None,
    lasterrortime: float = 0.0,
    errorcount: int = 0,
) -> SimpleNamespace:
    """Create a stand-in for ``Package.StatusInfo``."""
    return SimpleNamespace(
        lastsuccesslog=lastsuccesslog,
        lastsuccesstime=lastsuccesstime,
        runninglog=runninglog,
        lasterrorlog=lasterrorlog,
        lasterrortime=lasterrortime,
        errorcount=errorcount,
    )


def make_settings(*, hidden: bool = False, src: str = "") -> SimpleNamespace:
    """Create a stand-in for ``PackageSettings``."""
    return SimpleNamespace(hidden=hidden, src=src)


def make_package(
    *,
    pkgid: str,
    name: str,
    synctype: str = "rsync",
    syncrate: int = 0,
    src: str = "",
    hidden: bool = False,
    link: Optional[list] = None,
    statusinfo: Optional[SimpleNamespace] = None,
    timestamp: float = 0.0,
) -> SimpleNamespace:
    """Create a stand-in ``Package`` object with the attributes the plug-in reads."""
    return SimpleNamespace(
        pkgid=pkgid,
        name=name,
        synctype=synctype,
        syncrate=syncrate,
        link=link or [],
        settings=make_settings(hidden=hidden, src=src),
        statusinfo=statusinfo or make_status_info(),
        timestamp=timestamp,
    )


def test_format_hidden_flag():
    assert format_hidden_flag(True) == "true"
    assert format_hidden_flag(False) is None


def test_format_iso_kst_round_trip():
    iso = "2026-05-06T10:42:07+09:00"
    assert format_iso_kst(parse_iso_to_epoch(iso)) == iso


def test_format_links_preserves_order():
    links = [make_link("home", "http://x"), make_link("HTTP", "http://y")]
    assert format_links(links) == [
        {"rel": "home", "href": "http://x"},
        {"rel": "HTTP", "href": "http://y"},
    ]


def test_build_sync_block_with_frequency():
    pkg = make_package(
        pkgid="ArchLinux",
        name="ArchLinux",
        synctype="rsync",
        syncrate=600,
        src="rsync://ftp.gwdg.de/pub/linux/archlinux/",
    )
    assert build_sync_block(pkg) == {
        "source": "rsync://ftp.gwdg.de/pub/linux/archlinux/",
        "frequency": "PT10M",
    }


def test_build_sync_block_without_frequency_when_syncrate_zero():
    pkg = make_package(
        pkgid="CentOS",
        name="CentOS",
        synctype="rsync",
        syncrate=0,
        src="rsync://ftp.riken.jp/centos",
    )
    assert build_sync_block(pkg) == {"source": "rsync://ftp.riken.jp/centos"}


def test_build_sync_block_returns_none_for_local_synctype():
    pkg = make_package(pkgid="geoul", name="Geoul", synctype="local", src="")
    assert build_sync_block(pkg) is None


def test_build_sync_block_returns_none_when_src_blank():
    pkg = make_package(pkgid="weird", name="Weird", synctype="rsync", src="")
    assert build_sync_block(pkg) is None


def test_build_updated_block_returns_none_when_never_updated():
    info = make_status_info()
    assert build_updated_block(info) is None


def test_build_updated_block_populated():
    iso = "2026-05-06T10:42:07+09:00"
    info = make_status_info(
        lastsuccesslog="http://example/log.gz",
        lastsuccesstime=parse_iso_to_epoch(iso),
    )
    assert build_updated_block(info) == {
        "href": "http://example/log.gz",
        "timestamp": iso,
    }


def test_build_updating_block_uses_package_timestamp_milliseconds():
    iso = "2026-05-06T08:12:01+09:00"
    pkg = make_package(
        pkgid="CRAN",
        name="CRAN",
        synctype="rsync",
        statusinfo=make_status_info(runninglog="http://example/running.log"),
        timestamp=parse_iso_to_epoch(iso) * 1000.0,
    )
    assert build_updating_block(pkg) == {
        "href": "http://example/running.log",
        "timestamp": iso,
    }


def test_build_updating_block_returns_none_without_running_log():
    pkg = make_package(pkgid="quiet", name="quiet")
    assert build_updating_block(pkg) is None


def test_build_failed_block_renders_count_as_string():
    iso = "2026-05-02T06:55:34+09:00"
    info = make_status_info(
        lasterrorlog="http://example/err.gz",
        lasterrortime=parse_iso_to_epoch(iso),
        errorcount=29,
    )
    assert build_failed_block(info) == {
        "href": "http://example/err.gz",
        "timestamp": iso,
        "count": "29",
    }


def test_build_failed_block_returns_none_when_clean():
    assert build_failed_block(make_status_info()) is None


def fixture_package(pkgid: str) -> dict:
    """Helper to fetch a single package dict from the fixture."""
    return load_fixture()["package"][pkgid]


def test_shape_archlinux_matches_fixture():
    fixture = fixture_package("ArchLinux")
    pkg = make_package(
        pkgid="ArchLinux",
        name="ArchLinux",
        synctype="rsync",
        syncrate=600,
        src="rsync://ftp.gwdg.de/pub/linux/archlinux/",
        link=[
            make_link("home", "http://www.archlinux.org/"),
            make_link("HTTP", "http://ftp.kaist.ac.kr/ArchLinux"),
            make_link("FTP", "ftp://ftp.kaist.ac.kr/ArchLinux"),
        ],
        statusinfo=make_status_info(
            lastsuccesslog=fixture["status"]["updated"]["href"],
            lastsuccesstime=parse_iso_to_epoch(fixture["status"]["updated"]["timestamp"]),
        ),
    )
    assert shape_package(pkg) == fixture


def test_shape_geoul_local_synctype_omits_sync_block():
    fixture = fixture_package("geoul")
    pkg = make_package(
        pkgid="geoul",
        name="Geoul system metadata",
        synctype="local",
        hidden=True,
        link=[],
    )
    shaped = shape_package(pkg)
    assert "sync" not in shaped
    assert shaped == fixture


def test_shape_chicken_no_sync_no_status():
    fixture = fixture_package("chicken")
    pkg = make_package(
        pkgid="chicken",
        name="Chicken",
        synctype="local",
        link=[
            make_link("HTTP", "http://ftp.kaist.ac.kr/chicken"),
            make_link("FTP", "ftp://ftp.kaist.ac.kr/chicken"),
        ],
    )
    assert shape_package(pkg) == fixture


def test_shape_openbsd_with_failed_block():
    fixture = fixture_package("OpenBSD")
    pkg = make_package(
        pkgid="OpenBSD",
        name="OpenBSD",
        synctype="rsync",
        syncrate=86400,
        src="rsync://ftp.usa.openbsd.org/ftp/",
        link=[
            make_link("list", "http://www.openbsd.org/ftp.html"),
            make_link("HTTP", "http://ftp.kaist.ac.kr/OpenBSD"),
            make_link("FTP", "ftp://ftp.kaist.ac.kr/OpenBSD"),
        ],
        statusinfo=make_status_info(
            lastsuccesslog=fixture["status"]["updated"]["href"],
            lastsuccesstime=parse_iso_to_epoch(fixture["status"]["updated"]["timestamp"]),
            lasterrorlog=fixture["status"]["failed"]["href"],
            lasterrortime=parse_iso_to_epoch(fixture["status"]["failed"]["timestamp"]),
            errorcount=29,
        ),
    )
    assert shape_package(pkg) == fixture


def test_shape_cran_with_updating_block():
    fixture = fixture_package("CRAN")
    pkg = make_package(
        pkgid="CRAN",
        name="CRAN",
        synctype="rsync",
        syncrate=86400,
        src="rsync://cran.r-project.org/CRAN/",
        link=[
            make_link("home", "http://cran.r-project.org"),
            make_link("HTTP", "http://ftp.kaist.ac.kr/CRAN"),
            make_link("FTP", "ftp://ftp.kaist.ac.kr/CRAN"),
        ],
        statusinfo=make_status_info(
            lastsuccesslog=fixture["status"]["updated"]["href"],
            lastsuccesstime=parse_iso_to_epoch(fixture["status"]["updated"]["timestamp"]),
            runninglog=fixture["status"]["updating"]["href"],
        ),
        timestamp=parse_iso_to_epoch(fixture["status"]["updating"]["timestamp"]) * 1000.0,
    )
    assert shape_package(pkg) == fixture


def test_shape_centos_omits_frequency_when_syncrate_zero():
    fixture = fixture_package("CentOS")
    pkg = make_package(
        pkgid="CentOS",
        name="CentOS",
        synctype="rsync",
        syncrate=0,
        src="rsync://ftp.riken.jp/centos",
        link=[
            make_link("home", "http://www.centos.org"),
            make_link("mirrors list", "http://www.centos.org/download/mirrors/"),
            make_link("mirror status", "http://mirror-status.centos.org/"),
            make_link("HTTP", "http://ftp.kaist.ac.kr/CentOS"),
            make_link("FTP", "ftp://ftp.kaist.ac.kr/CentOS"),
        ],
        statusinfo=make_status_info(
            lastsuccesslog=fixture["status"]["updated"]["href"],
            lastsuccesstime=parse_iso_to_epoch(fixture["status"]["updated"]["timestamp"]),
        ),
    )
    assert shape_package(pkg) == fixture
    assert "frequency" not in shape_package(pkg)["sync"]


def test_build_kaist_payload_top_level_shape():
    pkg = make_package(
        pkgid="x",
        name="X",
        synctype="local",
    )
    payload = build_kaist_payload([pkg])
    assert set(payload.keys()) == {"timestamp", "package"}
    assert set(payload["package"].keys()) == {"x"}
    parsed = datetime.fromisoformat(payload["timestamp"])
    assert parsed.utcoffset() == timedelta(hours=9)


LOG_BASE_PATH = "/var/log/mirror/packages"
LOG_BASE_URL = "http://ftp.kaist.ac.kr/geoul/sync"


def test_convert_log_href_rewrites_base_prefix():
    href = "/var/log/mirror/packages/2026/05/06/10:42:01.154793368.ArchLinux.log.gz"
    assert convert_log_href(href, LOG_BASE_PATH, LOG_BASE_URL) == (
        "http://ftp.kaist.ac.kr/geoul/sync/2026/05/06/10:42:01.154793368.ArchLinux.log.gz"
    )


def test_convert_log_href_normalizes_slashes():
    href = "/var/log/mirror/packages/x.log.gz"
    assert convert_log_href(href, "/var/log/mirror/packages/", LOG_BASE_URL + "/") == (
        "http://ftp.kaist.ac.kr/geoul/sync/x.log.gz"
    )


def test_convert_log_href_passthrough_when_no_base_url():
    href = "/var/log/mirror/packages/x.log.gz"
    assert convert_log_href(href, LOG_BASE_PATH, None) == href


def test_convert_log_href_passthrough_when_outside_base():
    href = "/srv/other/x.log.gz"
    assert convert_log_href(href, LOG_BASE_PATH, LOG_BASE_URL) == href


def test_convert_log_href_none_and_empty():
    assert convert_log_href(None, LOG_BASE_PATH, LOG_BASE_URL) is None
    assert convert_log_href("", LOG_BASE_PATH, LOG_BASE_URL) == ""


def test_build_updated_block_rewrites_href():
    iso = "2026-05-06T10:42:07+09:00"
    info = make_status_info(
        lastsuccesslog="/var/log/mirror/packages/2026/05/06/x.log.gz",
        lastsuccesstime=parse_iso_to_epoch(iso),
    )
    assert build_updated_block(info, LOG_BASE_PATH, LOG_BASE_URL) == {
        "href": "http://ftp.kaist.ac.kr/geoul/sync/2026/05/06/x.log.gz",
        "timestamp": iso,
    }


def test_build_failed_block_rewrites_href():
    iso = "2026-05-02T06:55:34+09:00"
    info = make_status_info(
        lasterrorlog="/var/log/mirror/packages/2026/05/02/e.log.gz",
        lasterrortime=parse_iso_to_epoch(iso),
        errorcount=29,
    )
    assert build_failed_block(info, LOG_BASE_PATH, LOG_BASE_URL) == {
        "href": "http://ftp.kaist.ac.kr/geoul/sync/2026/05/02/e.log.gz",
        "timestamp": iso,
        "count": "29",
    }


def test_build_updating_block_rewrites_href():
    iso = "2026-05-06T08:12:01+09:00"
    pkg = make_package(
        pkgid="CRAN",
        name="CRAN",
        synctype="rsync",
        statusinfo=make_status_info(
            runninglog="/var/log/mirror/packages/2026/05/06/r.log"
        ),
        timestamp=parse_iso_to_epoch(iso) * 1000.0,
    )
    assert build_updating_block(pkg, LOG_BASE_PATH, LOG_BASE_URL) == {
        "href": "http://ftp.kaist.ac.kr/geoul/sync/2026/05/06/r.log",
        "timestamp": iso,
    }


def test_shape_package_rewrites_log_hrefs():
    iso = "2026-05-06T10:42:07+09:00"
    pkg = make_package(
        pkgid="ArchLinux",
        name="ArchLinux",
        synctype="rsync",
        syncrate=600,
        src="rsync://ftp.gwdg.de/pub/linux/archlinux/",
        statusinfo=make_status_info(
            lastsuccesslog="/var/log/mirror/packages/2026/05/06/a.log.gz",
            lastsuccesstime=parse_iso_to_epoch(iso),
        ),
    )
    shaped = shape_package(pkg, LOG_BASE_PATH, LOG_BASE_URL)
    assert shaped["status"]["updated"]["href"] == (
        "http://ftp.kaist.ac.kr/geoul/sync/2026/05/06/a.log.gz"
    )


def test_shape_package_without_base_url_keeps_posix():
    iso = "2026-05-06T10:42:07+09:00"
    posix = "/var/log/mirror/packages/2026/05/06/a.log.gz"
    pkg = make_package(
        pkgid="ArchLinux",
        name="ArchLinux",
        synctype="rsync",
        syncrate=600,
        src="rsync://ftp.gwdg.de/pub/linux/archlinux/",
        statusinfo=make_status_info(
            lastsuccesslog=posix,
            lastsuccesstime=parse_iso_to_epoch(iso),
        ),
    )
    shaped = shape_package(pkg)
    assert shaped["status"]["updated"]["href"] == posix


def test_plugin_record_declares_output_and_config_filename():
    record = plugin()
    assert record.type == "status"
    assert record.config_filename == "kaist.json"
    output = record.outputs[0]
    assert output.name == "kaist-status"
    assert output.default_path == "/var/www/mirror/kaist-status.json"
    assert output.config_path_key == "output_path"
