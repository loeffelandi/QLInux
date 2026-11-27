"""Selbst-Update aus GitHub-Releases (docs/adr/0023 und 0024).

Dieses Modul kennt kein Qt: Suche, Vergleich, Download mit Pruefsumme,
Ersetzen von AppImage und ``QLInux.app`` sowie der Neustart laufen als
einfache Funktionen, die ``update_ui`` im Hintergrund aufruft. Fehler, die
der Nutzer lesen soll, kommen als :class:`UpdateError` mit fertigem Text.
"""

from __future__ import annotations

import hashlib
import http.client
import json
import os
import platform
import plistlib
import re
import shutil
import ssl
import stat
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol
from urllib.parse import urlsplit

from . import __version__
from .i18n import tr
from .platform_support import is_mac

REPOSITORY = "loeffelandi/QLInux"
RELEASES_URL = f"https://api.github.com/repos/{REPOSITORY}/releases/latest"
#: Hoechstens eine Suche beim Start in dieser Zeit (Sekunden).
CHECK_INTERVAL = 24 * 3600
#: Zeitlimit der Abfrage und je Leseschritt beim Download (Sekunden).
REQUEST_TIMEOUT = 5.0
DOWNLOAD_TIMEOUT = 15.0
_CHUNK = 64 * 1024
#: ``QLINUX_NO_UPDATE_CHECK=1`` schaltet die Suche beim Start ab.
DISABLE_ENV = "QLINUX_NO_UPDATE_CHECK"

KIND_APPIMAGE = "appimage"
KIND_APP = "app"

#: Nur diese Schemata sind erlaubt, auch bei Weiterleitungen. Tests lassen
#: fuer einen lokalen Server ``http`` zu.
_ALLOWED_SCHEMES: tuple[str, ...] = ("https",)

_TAG = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)$")
_DIGEST = re.compile(r"^sha256:([0-9a-fA-F]{64})$")
_ARCH = {
    "x86_64": "x86_64",
    "amd64": "x86_64",
    "aarch64": "aarch64",
    "arm64": "aarch64",
}
#: Reste eines abgebrochenen Updates neben der Datei bzw. App.
_APP_STAGING = ".QLInux-update-{pid}.app"
_APP_OLD = ".QLInux-old-{pid}.app"
_APP_LEFTOVERS = (".QLInux-update-*.app", ".QLInux-old-*.app")
_IMAGE_STAGING = ".{name}.update"


class UpdateError(Exception):
    """Ein Update ist gescheitert; ``str(error)`` ist der Text fuer den Nutzer."""


class UpdateCancelled(Exception):
    """Der Nutzer hat den Download abgebrochen."""


Progress = Callable[[int, int], None]


# --------------------------------------------------------------------------- #
# Wer sich aktualisiert
# --------------------------------------------------------------------------- #
def app_bundle() -> Path | None:
    """``QLInux.app``, wenn das Programm als gepacktes Bundle laeuft."""
    if not getattr(sys, "frozen", False):
        return None
    for parent in Path(sys.executable).resolve().parents:
        if parent.suffix == ".app":
            return parent
    return None


def install_kind() -> str | None:
    """``appimage`` oder ``app``; ``None`` fuer Quelltext und andere Installationen."""
    if is_mac():
        return KIND_APP if app_bundle() is not None else None
    path = os.environ.get("APPIMAGE")
    if path and Path(path).is_file():
        return KIND_APPIMAGE
    return None


def is_updatable() -> bool:
    return install_kind() is not None


def install_path(kind: str) -> Path:
    """Die Datei bzw. App, die ein Update ersetzt."""
    if kind == KIND_APP:
        bundle = app_bundle()
        if bundle is None:
            raise UpdateError(tr("QLInux.app wurde nicht gefunden."))
        return bundle
    return Path(os.environ.get("APPIMAGE", ""))


# --------------------------------------------------------------------------- #
# Version und Datei der Release
# --------------------------------------------------------------------------- #
def parse_version(text: str) -> tuple[int, int, int] | None:
    """``v0.5.0`` oder ``0.5.0`` als Zahlentupel; alles andere ist ``None``."""
    match = _TAG.match(str(text).strip())
    if match is None:
        return None
    return int(match.group(1)), int(match.group(2)), int(match.group(3))


def asset_name(kind: str, version: str, machine: str) -> str | None:
    """Dateiname der Release fuer diese Installation (``None``: keine passende)."""
    arch = _ARCH.get(machine.lower())
    if kind == KIND_APP:
        return f"QLInux-{version}-arm64.dmg" if arch == "aarch64" else None
    if arch is None:
        return None
    return f"QLInux-{version}-{arch}.AppImage"


@dataclass(frozen=True)
class Update:
    version: str
    name: str
    url: str
    sha256: str
    size: int
    page: str


@dataclass(frozen=True)
class CheckResult:
    """Ergebnis einer Abfrage.

    ``update`` ist gesetzt, wenn eine neuere Release samt Datei und Pruefsumme
    da ist. ``pending``: die Release ist neuer, ihre Datei fehlt noch (die
    Workflows laden sie erst nach der Veroeffentlichung hoch).
    """

    update: Update | None = None
    pending: bool = False


def evaluate(
    release: Mapping[str, object],
    current: str,
    kind: str,
    machine: str,
) -> CheckResult:
    """Bewertet die Antwort von ``releases/latest``."""
    if release.get("draft") or release.get("prerelease"):
        return CheckResult()
    tag = str(release.get("tag_name") or "")
    latest = parse_version(tag)
    installed = parse_version(current)
    if latest is None or installed is None or latest <= installed:
        return CheckResult()
    version = ".".join(str(part) for part in latest)
    name = asset_name(kind, version, machine)
    if name is None:
        return CheckResult()
    assets = release.get("assets")
    for asset in assets if isinstance(assets, list) else []:
        if not isinstance(asset, dict) or asset.get("name") != name:
            continue
        digest = _DIGEST.match(str(asset.get("digest") or ""))
        url = str(asset.get("browser_download_url") or "")
        if digest is None or not url:
            break
        size = asset.get("size")
        return CheckResult(
            update=Update(
                version=version,
                name=name,
                url=url,
                sha256=digest.group(1).lower(),
                size=size if isinstance(size, int) else 0,
                page=str(release.get("html_url") or ""),
            )
        )
    return CheckResult(pending=True)


# --------------------------------------------------------------------------- #
# Wann gesucht wird
# --------------------------------------------------------------------------- #
class _CheckSettings(Protocol):
    @property
    def update_check_on_start(self) -> bool: ...

    @property
    def update_last_check(self) -> float: ...


def check_due(settings: _CheckSettings, now: float | None = None) -> bool:
    """Soll der Start nach einem Update suchen?"""
    if not is_updatable() or os.environ.get(DISABLE_ENV) == "1":
        return False
    if not settings.update_check_on_start:
        return False
    moment = time.time() if now is None else now
    return moment - settings.update_last_check >= CHECK_INTERVAL


# --------------------------------------------------------------------------- #
# Netzwerk
# --------------------------------------------------------------------------- #
def _ssl_context() -> ssl.SSLContext:
    try:
        import certifi
    except ImportError:  # pragma: no cover - Entwicklungsumgebung ohne certifi
        return ssl.create_default_context()
    return ssl.create_default_context(cafile=certifi.where())


def _require_secure(url: str) -> None:
    if urlsplit(url).scheme not in _ALLOWED_SCHEMES:
        raise UpdateError(
            tr("Unverschlüsselte Adresse abgelehnt: {url}").format(url=url)
        )


class _SecureRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        _require_secure(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _open(url: str, accept: str, timeout: float):
    _require_secure(url)
    opener = urllib.request.build_opener(
        _SecureRedirects(), urllib.request.HTTPSHandler(context=_ssl_context())
    )
    request = urllib.request.Request(
        url, headers={"User-Agent": f"QLInux/{__version__}", "Accept": accept}
    )
    return opener.open(request, timeout=timeout)


def fetch_latest() -> dict:
    """Die neueste veroeffentlichte Release von GitHub."""
    try:
        with _open(RELEASES_URL, "application/vnd.github+json", REQUEST_TIMEOUT) as r:
            data = json.loads(r.read(2_000_000).decode("utf-8"))
    except UpdateError:
        raise
    except (OSError, http.client.HTTPException, ValueError) as exc:
        raise UpdateError(
            tr("GitHub ist nicht erreichbar: {error}").format(error=exc)
        ) from exc
    if not isinstance(data, dict):
        raise UpdateError(tr("Unerwartete Antwort von GitHub."))
    return data


def check(machine: str | None = None) -> CheckResult:
    """Abfragen und bewerten; ohne gepackte Installation gibt es kein Ergebnis."""
    kind = install_kind()
    if kind is None:
        return CheckResult()
    return evaluate(fetch_latest(), __version__, kind, machine or platform.machine())


def download(
    url: str,
    target: Path,
    sha256: str,
    *,
    progress: Progress | None = None,
    cancel: threading.Event | None = None,
) -> None:
    """Datei laden und gegen ``sha256`` pruefen; bei jedem Fehler ist ``target`` weg."""
    digest = hashlib.sha256()
    done = 0
    total = 0
    try:
        with _open(url, "application/octet-stream", DOWNLOAD_TIMEOUT) as response:
            total = int(response.headers.get("Content-Length") or 0)
            with open(target, "wb") as out:
                while True:
                    if cancel is not None and cancel.is_set():
                        raise UpdateCancelled
                    chunk = response.read(_CHUNK)
                    if not chunk:
                        break
                    out.write(chunk)
                    digest.update(chunk)
                    done += len(chunk)
                    if progress is not None:
                        progress(done, total)
        if total and done != total:
            raise UpdateError(tr("Der Download ist unvollständig."))
        if digest.hexdigest() != sha256.lower():
            raise UpdateError(
                tr(
                    "Die Prüfsumme der Datei stimmt nicht. Das Update wird nicht installiert."
                )
            )
    except (UpdateError, UpdateCancelled):
        target.unlink(missing_ok=True)
        raise
    except (OSError, http.client.HTTPException, ValueError) as exc:
        target.unlink(missing_ok=True)
        raise UpdateError(
            tr("Der Download ist fehlgeschlagen: {error}").format(error=exc)
        ) from exc
    except BaseException:
        target.unlink(missing_ok=True)
        raise


# --------------------------------------------------------------------------- #
# Ersetzen
# --------------------------------------------------------------------------- #
def ensure_writable(target: Path) -> None:
    """Vor dem Download klaeren, ob die Datei bzw. App ersetzbar ist."""
    if not os.access(target.parent, os.W_OK):
        raise UpdateError(
            tr("In den Ordner {path} darf QLInux nicht schreiben.").format(
                path=target.parent
            )
        )


def staging_path(target: Path) -> Path:
    """Wo ein neues AppImage entsteht: neben dem alten, im selben Dateisystem."""
    return target.with_name(_IMAGE_STAGING.format(name=target.name))


def install_appimage(downloaded: Path, target: Path) -> None:
    """Das neue AppImage in einem Schritt an die Stelle des alten setzen."""
    try:
        mode = stat.S_IMODE(target.stat().st_mode) if target.exists() else 0o755
        os.chmod(downloaded, mode | 0o111)
        os.replace(downloaded, target)
    except OSError as exc:
        downloaded.unlink(missing_ok=True)
        raise UpdateError(
            tr("{path} konnte nicht ersetzt werden: {error}").format(
                path=target, error=exc
            )
        ) from exc


def _run(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, capture_output=True, text=True, check=False)


def _fail(step: str, result: subprocess.CompletedProcess[str]) -> UpdateError:
    detail = (result.stderr or result.stdout or "").strip().splitlines()
    return UpdateError(
        tr("{step} ist fehlgeschlagen: {error}").format(
            step=step, error=detail[-1] if detail else result.returncode
        )
    )


def install_app(dmg: Path, app: Path, expected_version: str) -> None:
    """Die App aus der ``.dmg`` an die Stelle der laufenden ``QLInux.app`` setzen.

    Kopieren, pruefen und umbenennen: schlaegt etwas fehl, bleibt die alte App
    an ihrem Platz und es liegt nichts Halbes daneben.
    """
    mountpoint = Path(tempfile.mkdtemp(prefix="qlinux-update-"))
    staging = app.with_name(_APP_STAGING.format(pid=os.getpid()))
    attached = False
    try:
        result = _run(
            [
                "hdiutil",
                "attach",
                "-nobrowse",
                "-readonly",
                "-noverify",
                "-noautoopen",
                "-mountpoint",
                str(mountpoint),
                str(dmg),
            ]
        )
        if result.returncode != 0:
            raise _fail(tr("Das Öffnen der .dmg"), result)
        attached = True
        source = mountpoint / "QLInux.app"
        if not source.is_dir():
            raise UpdateError(tr("In der .dmg liegt keine QLInux.app."))
        shutil.rmtree(staging, ignore_errors=True)
        result = _run(["ditto", str(source), str(staging)])
        if result.returncode != 0:
            raise _fail(tr("Das Kopieren der App"), result)
        _check_app(staging, expected_version)
        _swap(staging, app)
    finally:
        if attached:
            _run(["hdiutil", "detach", "-force", str(mountpoint)])
        shutil.rmtree(staging, ignore_errors=True)
        shutil.rmtree(mountpoint, ignore_errors=True)


def _check_app(staging: Path, expected_version: str) -> None:
    try:
        info = plistlib.loads((staging / "Contents" / "Info.plist").read_bytes())
    except (OSError, plistlib.InvalidFileException, ValueError) as exc:
        raise UpdateError(tr("Die neue App ist unvollständig.")) from exc
    found = str(info.get("CFBundleShortVersionString", ""))
    if found != expected_version:
        raise UpdateError(
            tr("Die neue App hat die Version {found}, erwartet war {expected}.").format(
                found=found or "?", expected=expected_version
            )
        )
    result = _run(["codesign", "--verify", "--deep", str(staging)])
    if result.returncode != 0:
        raise _fail(tr("Die Prüfung der Signatur"), result)


def _swap(staging: Path, app: Path) -> None:
    old = app.with_name(_APP_OLD.format(pid=os.getpid()))
    try:
        os.rename(app, old)
    except OSError as exc:
        raise UpdateError(
            tr("{path} konnte nicht ersetzt werden: {error}").format(
                path=app, error=exc
            )
        ) from exc
    try:
        os.rename(staging, app)
    except OSError as exc:
        os.rename(old, app)
        raise UpdateError(
            tr("{path} konnte nicht ersetzt werden: {error}").format(
                path=app, error=exc
            )
        ) from exc
    shutil.rmtree(old, ignore_errors=True)


def cleanup_leftovers(kind: str) -> None:
    """Reste eines abgebrochenen Updates neben der Datei bzw. App wegraeumen."""
    try:
        target = install_path(kind)
    except UpdateError:
        return
    if kind == KIND_APP:
        for pattern in _APP_LEFTOVERS:
            for path in target.parent.glob(pattern):
                shutil.rmtree(path, ignore_errors=True)
    else:
        staging_path(target).unlink(missing_ok=True)


def cleanup_stale() -> None:
    """Beim Start: Reste wegraeumen, wenn dies eine ersetzbare Installation ist."""
    kind = install_kind()
    if kind is not None:
        cleanup_leftovers(kind)


# --------------------------------------------------------------------------- #
# Neustart
# --------------------------------------------------------------------------- #
_WAIT_THEN_RUN = 'while kill -0 "$1" 2>/dev/null; do sleep 0.2; done; shift; exec "$@"'


def restart_command(kind: str, target: Path, files: list[str], pid: int) -> list[str]:
    """Hilfsprozess: wartet auf das Ende von ``pid``, startet dann die neue Datei."""
    if kind == KIND_APP:
        launcher = ["open", "-n", str(target), "--args", *files]
    else:
        launcher = [str(target), *files]
    return ["sh", "-c", _WAIT_THEN_RUN, "sh", str(pid), *launcher]


def _fresh_environment() -> dict[str, str]:
    """Umgebung ohne die Reste des alten AppImage (Bibliothekspfade, Mount)."""
    env = dict(os.environ)
    for name in ("APPIMAGE", "APPDIR", "ARGV0", "OWD"):
        env.pop(name, None)
    original = env.pop("LD_LIBRARY_PATH_ORIG", None)
    if original is None:
        env.pop("LD_LIBRARY_PATH", None)
    else:
        env["LD_LIBRARY_PATH"] = original
    return env


def start_restart(command: list[str]) -> None:
    """Hilfsprozess losloesen; er lebt weiter, wenn QLInux beendet ist."""
    subprocess.Popen(
        command,
        start_new_session=True,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        env=_fresh_environment(),
        close_fds=True,
    )
