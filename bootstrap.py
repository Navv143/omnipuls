"""Installs missing packages and starts the app in its own window.

Used automatically when you run `python app.py` (or the launchers). Uses only
the standard library, so it works before anything else is installed.
"""
import importlib.metadata as md
import os
import re
import shutil
import socket
import subprocess
import sys
import time
import urllib.request
import webbrowser
from pathlib import Path

HERE = Path(__file__).resolve().parent
REQ_FILE = HERE / "requirements.txt"
LOG_FILE = HERE / "navv.log"
PORT = 8501
IS_WIN = os.name == "nt"
# Started without a console (pythonw.exe from the desktop shortcut)?
WINDOWLESS = sys.stdout is None or Path(sys.executable).name.lower().startswith("pythonw")


def _ver(v: str) -> tuple:
    return tuple(int(x) for x in re.findall(r"\d+", v)[:3])


def _requirements() -> list[tuple[str, str]]:
    reqs = []
    for line in REQ_FILE.read_text().splitlines():
        line = line.split("#")[0].strip()
        if not line:
            continue
        m = re.match(r"([A-Za-z0-9_.\-]+)\s*(?:>=\s*([\d.]+))?", line)
        if m:
            reqs.append((m.group(1), m.group(2) or "0"))
    return reqs


def missing() -> list[str]:
    out = []
    for name, minimum in _requirements():
        try:
            if _ver(md.version(name)) < _ver(minimum):
                out.append(f"{name}>={minimum}")
        except md.PackageNotFoundError:
            out.append(f"{name}>={minimum}")
    return out


def _say(msg: str):
    if not WINDOWLESS:
        print(msg, flush=True)


def message_box(text: str, title: str = "Omnipuls"):
    """A visible message even when there is no console."""
    if IS_WIN:
        try:
            import ctypes
            ctypes.windll.user32.MessageBoxW(0, text, title, 0x40)
            return
        except Exception:
            pass
    _say(text)


def console_python() -> str:
    """python.exe next to pythonw.exe, so installs can show progress in a console."""
    exe = Path(sys.executable)
    if exe.name.lower().startswith("pythonw"):
        alt = exe.with_name(exe.name.lower().replace("pythonw", "python"))
        if alt.exists():
            return str(alt)
    return sys.executable


# Generous network settings so a slow or patchy connection finishes instead of failing.
# pip keeps finished downloads in its cache, so each retry only fetches what is left.
PIP_NET = ["--timeout", "120", "--retries", "15", "--prefer-binary"]
ROUNDS = 3


def _pip(args: list[str]) -> bool:
    return subprocess.call([sys.executable, "-m", "pip", "install", "--upgrade", *PIP_NET, *args]) == 0


def ensure() -> None:
    need = missing()
    if not need:
        return
    if WINDOWLESS and IS_WIN:
        # No console here: run the installer in a visible window and wait for it.
        subprocess.call([console_python(), str(HERE / "app.py"), "--install-only"], cwd=str(HERE),
                        creationflags=getattr(subprocess, "CREATE_NEW_CONSOLE", 0))
        if missing():
            message_box("Omnipuls could not finish installing its packages. Check your internet connection "
                        "and start it again; it continues from where it stopped.")
            sys.exit(1)
        return
    _say("\nOmnipuls: installing " + ", ".join(need) +
         "\nThis happens once. On a fast connection it takes a minute or two; on a slow one it can take"
         "\n20-40 minutes. 'Connection timed out' warnings are normal: pip resumes the download by itself."
         "\nPlease keep this window open.\n")
    subprocess.call([sys.executable, "-m", "ensurepip", "--upgrade"],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    in_venv = sys.prefix != getattr(sys, "base_prefix", sys.prefix)
    variants = [[]] if in_venv else [[], ["--user"], ["--user", "--break-system-packages"]]
    for rnd in range(1, ROUNDS + 1):
        for extra in variants:
            need = missing()
            if not need:
                break
            _pip([*extra, *need])
        if not missing():
            _say("\nAll packages installed.\n")
            return
        if rnd < ROUNDS:
            _say(f"\nThe download was interrupted. Trying again ({rnd + 1} of {ROUNDS}), "
                 "continuing from what is already downloaded...\n")
            time.sleep(5)
    _say("\nCould not finish installing the packages. This is almost always a slow or blocked internet "
         "connection.\nEverything downloaded so far is saved, so starting the app again continues from here."
         "\nIf it keeps failing, try another network such as a phone hotspot, or run this yourself:\n"
         f"  {sys.executable} -m pip install --timeout 120 --retries 15 -r requirements.txt\n")
    if not WINDOWLESS:
        try:
            input("Press Enter to close.")
        except EOFError:
            pass
    sys.exit(1)

def make_shortcut() -> bool:
    """Windows: a 'Omnipuls' desktop shortcut that starts the app without a console window."""
    if not IS_WIN:
        return False
    pyw = Path(sys.executable).with_name("pythonw.exe")
    if not pyw.exists():
        return False
    ps = ("$d=[Environment]::GetFolderPath('Desktop'); $l=Join-Path $d 'Omnipuls.lnk';"
          "$old=Join-Path $d 'Navv Markets.lnk'; if (Test-Path $old) { Remove-Item $old };"
          "$s=(New-Object -ComObject WScript.Shell).CreateShortcut($l);"
          "$s.TargetPath=$env:NAVV_PYW; $s.Arguments=('\"' + $env:NAVV_APP + '\"');"
          "$s.WorkingDirectory=$env:NAVV_DIR; $s.Description='Omnipuls'; $s.IconLocation=$env:NAVV_ICO; $s.Save()")
    env = dict(os.environ, NAVV_PYW=str(pyw), NAVV_APP=str(HERE / "app.py"), NAVV_DIR=str(HERE),
               NAVV_ICO=str(HERE / "assets" / "omnipuls.ico"))
    try:
        return subprocess.call(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps],
                               env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=30) == 0
    except Exception:
        return False


# ---------------------------------------------------------------- start the app


def server_up(port: int) -> bool:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/_stcore/health", timeout=2) as r:
            return r.status == 200
    except Exception:
        return False


def port_free(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind(("127.0.0.1", port))
            return True
        except OSError:
            return False


def _browser_candidates() -> list[str]:
    if IS_WIN:
        pf = [os.environ.get(k, "") for k in ("PROGRAMFILES(X86)", "PROGRAMFILES", "LOCALAPPDATA")]
        paths = []
        for base in pf:
            if base:
                paths += [os.path.join(base, "Microsoft", "Edge", "Application", "msedge.exe"),
                          os.path.join(base, "Google", "Chrome", "Application", "chrome.exe")]
        return [p for p in paths if os.path.exists(p)]
    if sys.platform == "darwin":
        return [p for p in ("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
                            "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge") if os.path.exists(p)]
    return [p for p in (shutil.which("google-chrome"), shutil.which("chromium"), shutil.which("microsoft-edge")) if p]


def open_window(url: str):
    """Open the app in its own window (Edge/Chrome app mode), or a normal browser tab."""
    for exe in _browser_candidates():
        try:
            subprocess.Popen([exe, f"--app={url}", "--window-size=1500,950"],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return
        except Exception:
            continue
    webbrowser.open(url)


def launch(app_file: str) -> None:
    """Start the Streamlit server, wait until it answers, then open the app window."""
    if server_up(PORT):  # already running (e.g. started earlier): just show it
        open_window(f"http://localhost:{PORT}")
        _say(f"Omnipuls is already running at http://localhost:{PORT}")
        return
    port = next((p for p in range(PORT, PORT + 20) if port_free(p)), PORT)
    url = f"http://localhost:{port}"
    args = [sys.executable, "-m", "streamlit", "run", str(Path(app_file).resolve()),
            "--server.headless", "true", "--server.port", str(port), "--server.address", "0.0.0.0",
            "--browser.gatherUsageStats", "false"]
    log = open(LOG_FILE, "w", encoding="utf-8")
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if WINDOWLESS else 0
    proc = subprocess.Popen(args, cwd=str(HERE), stdout=log, stderr=subprocess.STDOUT, creationflags=flags)
    _say("\nStarting Omnipuls", )
    t0 = time.time()
    while time.time() - t0 < 180:
        if proc.poll() is not None:
            break
        if server_up(port):
            break
        time.sleep(0.5)
        if not WINDOWLESS:
            print(".", end="", flush=True)
    if not server_up(port):
        log.close()
        tail = ""
        try:
            tail = "\n".join(LOG_FILE.read_text(encoding="utf-8", errors="ignore").strip().splitlines()[-12:])
        except Exception:
            pass
        message_box("Omnipuls could not start.\n\n" + (tail or "No details were written.") +
                    f"\n\nFull details: {LOG_FILE}")
        if proc.poll() is None:
            proc.terminate()
        sys.exit(1)

    open_window(url)
    _say(f"\n\nOmnipuls is open in its own window.\nIf it didn't appear, open {url} in your browser.\n"
         "Keep this window open while you use the app; close it (or press Ctrl+C) to stop.\n"
         "Next time, use the 'Omnipuls' shortcut on your desktop to start without this window.\n")
    if WINDOWLESS:
        return  # the server keeps running; stop it with "Quit Omnipuls" in the app's sidebar
    try:
        proc.wait()
    except KeyboardInterrupt:
        proc.terminate()
