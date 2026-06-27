"""Manages a local Ollama instance for Writher.

Startup sequence (runs in a background thread):
  1. If Ollama is already reachable at OLLAMA_URL → skip server setup,
     only pull the model if missing.
  2. Look for ollama.exe in known system locations (system install, PATH,
     our managed copy in DATA_DIR/ollama/).
  3. If not found anywhere → download the Windows AMD64 zip from GitHub
     releases and extract it to DATA_DIR/ollama/.
  4. Launch ollama.exe serve as a hidden subprocess.
  5. Pull the configured model if it is not already present.

Only the process WE started is stopped on app quit. A pre-existing
user-managed Ollama server is never touched.
"""

import io
import json
import os
import shutil
import subprocess
import threading
import time
import zipfile

import requests

import config
from logger import log
from paths import DATA_DIR

# ── Paths ─────────────────────────────────────────────────────────────────

_MANAGED_DIR = os.path.join(DATA_DIR, "ollama")
_MANAGED_EXE = os.path.join(_MANAGED_DIR, "ollama.exe")

_RELEASES_API = "https://api.github.com/repos/ollama/ollama/releases/latest"
_FALLBACK_URL = (
    "https://github.com/ollama/ollama/releases/latest/download/"
    "ollama-windows-amd64.zip"
)

# ── Module state ──────────────────────────────────────────────────────────

_managed_proc: "subprocess.Popen | None" = None
_ready = False
_lock = threading.Lock()


# ── Public API ────────────────────────────────────────────────────────────

def is_ready() -> bool:
    """True once Ollama is running and the configured model is available."""
    return _ready


def is_reachable() -> bool:
    """True if Ollama answers on the configured URL (any instance)."""
    try:
        r = requests.get(f"{config.OLLAMA_URL}/api/tags", timeout=2)
        return r.status_code == 200
    except Exception:
        return False


def ensure_ready(on_ollama_download=None, on_model_pull=None):
    """Ensure Ollama is running and the configured model is available.

    Runs in a background thread. Callbacks:
      on_ollama_download(pct: float)            — 0.0–1.0 during binary download
      on_model_pull(pct: float | None, status: str) — during model pull
    """
    global _ready
    with _lock:
        if not _ensure_server(on_ollama_download):
            return
        if not _ensure_model(on_model_pull):
            return
        _ready = True
        log.info("Ollama ready (model: %s).", config.OLLAMA_MODEL)


def stop():
    """Terminate the process we started (if any). Called on app quit."""
    global _managed_proc
    if _managed_proc is None:
        return
    log.info("Stopping managed Ollama (PID %d)...", _managed_proc.pid)
    try:
        _managed_proc.terminate()
        _managed_proc.wait(timeout=5)
        log.info("Managed Ollama stopped.")
    except Exception:
        try:
            _managed_proc.kill()
        except Exception:
            pass
    _managed_proc = None


# ── Server setup ──────────────────────────────────────────────────────────

def _ensure_server(on_download=None) -> bool:
    if is_reachable():
        log.info("Ollama already running at %s.", config.OLLAMA_URL)
        return True

    exe = _find_exe()
    if exe is None:
        log.info("Ollama binary not found — downloading...")
        if not _download(on_progress=on_download):
            log.error("Ollama download failed; assistant unavailable.")
            return False
        exe = _MANAGED_EXE

    return _start(exe)


def _find_exe() -> "str | None":
    """Return path to an existing ollama.exe, checking common locations."""
    if os.path.isfile(_MANAGED_EXE):
        return _MANAGED_EXE
    # Default Windows installer target
    local_app = os.environ.get("LOCALAPPDATA", "")
    system_exe = os.path.join(local_app, "Programs", "Ollama", "ollama.exe")
    if os.path.isfile(system_exe):
        return system_exe
    # Anywhere on PATH
    return shutil.which("ollama")


def _get_download_url() -> str:
    """Fetch the Windows AMD64 zip URL from GitHub releases API."""
    try:
        resp = requests.get(_RELEASES_API, timeout=10,
                            headers={"Accept": "application/vnd.github+json"})
        if resp.status_code == 200:
            for asset in resp.json().get("assets", []):
                name = asset.get("name", "").lower()
                if "windows" in name and "amd64" in name and name.endswith(".zip"):
                    url = asset["browser_download_url"]
                    log.info("Ollama download URL: %s", url)
                    return url
    except Exception as exc:
        log.warning("Could not query GitHub releases API: %s", exc)
    return _FALLBACK_URL


def _download(on_progress=None) -> bool:
    """Download and extract ollama.exe to _MANAGED_DIR."""
    os.makedirs(_MANAGED_DIR, exist_ok=True)
    url = _get_download_url()
    try:
        log.info("Downloading Ollama from %s", url)
        resp = requests.get(url, stream=True, timeout=180)
        resp.raise_for_status()

        total = int(resp.headers.get("content-length") or 0)
        downloaded = 0
        chunks: list[bytes] = []

        for chunk in resp.iter_content(chunk_size=65536):
            if chunk:
                chunks.append(chunk)
                downloaded += len(chunk)
                if on_progress and total:
                    on_progress(downloaded / total)

        with zipfile.ZipFile(io.BytesIO(b"".join(chunks))) as zf:
            zf.extractall(_MANAGED_DIR)

        log.info("Ollama extracted to %s", _MANAGED_DIR)
        return os.path.isfile(_MANAGED_EXE)
    except Exception as exc:
        log.error("Ollama download failed: %s", exc)
        return False


def _start(exe: str) -> bool:
    """Launch ollama serve as a hidden background process."""
    global _managed_proc
    try:
        log.info("Starting Ollama from %s", exe)
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        _managed_proc = subprocess.Popen(
            [exe, "serve"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=flags,
        )
        for _ in range(24):          # wait up to 12 s
            time.sleep(0.5)
            if is_reachable():
                log.info("Managed Ollama started (PID %d).", _managed_proc.pid)
                return True
        log.error("Ollama process started but not reachable after 12 s.")
        return False
    except Exception as exc:
        log.error("Could not start Ollama: %s", exc)
        return False


# ── Model management ──────────────────────────────────────────────────────

def _model_is_available(model: str) -> bool:
    try:
        r = requests.get(f"{config.OLLAMA_URL}/api/tags", timeout=5)
        if r.status_code == 200:
            names = [m["name"] for m in r.json().get("models", [])]
            return any(model in n or n in model for n in names)
    except Exception:
        pass
    return False


def _list_available_models() -> list[str]:
    try:
        r = requests.get(f"{config.OLLAMA_URL}/api/tags", timeout=5)
        if r.status_code == 200:
            return [m["name"] for m in r.json().get("models", [])]
    except Exception:
        pass
    return []


def _ensure_model(on_progress=None) -> bool:
    model = config.OLLAMA_MODEL
    if _model_is_available(model):
        log.info("Model '%s' already available.", model)
        return True

    # Before pulling, check if any model is already present and use it.
    available = _list_available_models()
    if available:
        fallback = available[0]
        log.info(
            "Model '%s' not found; using existing model '%s' instead of pulling.",
            model, fallback,
        )
        config.OLLAMA_MODEL = fallback
        return True

    log.info("No models found; pulling '%s'...", model)
    return _pull_model(model, on_progress)


def _pull_model(model: str, on_progress=None) -> bool:
    try:
        with requests.post(
            f"{config.OLLAMA_URL}/api/pull",
            json={"name": model, "stream": True},
            stream=True,
            timeout=1800,
        ) as resp:
            resp.raise_for_status()
            for raw in resp.iter_lines():
                if not raw:
                    continue
                try:
                    data = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                status = data.get("status", "")
                total = data.get("total", 0)
                completed = data.get("completed", 0)
                pct = (completed / total) if total else None
                if on_progress:
                    on_progress(pct, status)
                if status == "success":
                    log.info("Model '%s' pulled.", model)
                    return True
        return True
    except Exception as exc:
        log.error("Model pull failed: %s", exc)
        return False
