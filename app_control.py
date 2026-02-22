import json
import os
import re
import string
import subprocess
import time
from dataclasses import dataclass
from typing import Optional, List, Tuple
import keyboard

from rapidfuzz import fuzz
import difflib
import pygetwindow as gw

# ✅ NEW: robust Win32 focus fallback
import win32con
import win32gui
import win32com.client

# -----------------------
# Cache config
# -----------------------
CACHE_TTL_SECONDS = 7 * 24 * 3600  # 7 days
CACHE_PATH = os.path.join(os.environ.get("LOCALAPPDATA", "."), "lumo_app_catalog.json")

# -----------------------
# Utilities
# -----------------------
def _run_powershell_json(command: str):
    """
    Runs a PowerShell command that outputs JSON and parses it.
    """
    r = subprocess.run(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", command],
        capture_output=True,
        text=True,
    )
    if r.returncode != 0:
        raise RuntimeError(r.stderr.strip() or "PowerShell command failed")
    out = r.stdout.strip()
    if not out:
        return []
    return json.loads(out)

def clean_app_name(name: str) -> str:
    # Important: assign the cleaned string (Whisper often adds punctuation like "firefox.")
    name = name.strip().strip(string.punctuation)
    name = re.sub(r"\s+", " ", name)
    return name

def normalize_spoken_app(s: str) -> str:
    """
    Fix common Whisper confusions so focus/open behave better.
    Extend this with your own common errors.
    """
    s = clean_app_name(s).lower()

    # Common STT confusions
    s = s.replace("vs core", "vs code")
    s = s.replace("v s code", "vs code")
    s = s.replace("visual studio code", "vs code")  # helps match short queries too

    return s

def _similarity(a: str, b: str) -> float:
    a = a.lower().strip()
    b = b.lower().strip()
    try:
        # Debug (optional)
        # print(f"Comparing '{a}' to '{b}'")

        # Best for window titles with extra words:
        s1 = fuzz.partial_ratio(a, b) / 100.0
        s2 = fuzz.token_set_ratio(a, b) / 100.0

        score = max(s1, s2)
        # print(f"Similarity: {score:.2f}") 
        return score

    except Exception:
        return difflib.SequenceMatcher(None, a, b).ratio()


@dataclass(frozen=True)
class AppEntry:
    name: str
    app_id: str  # StartApps AppID

# -----------------------
# Catalog building
# -----------------------
def build_startapps_catalog() -> List[AppEntry]:
    """
    Uses `Get-StartApps` which returns apps visible in Start Menu.
    This is the BEST list for voice commands because it is launchable.
    """
    data = _run_powershell_json(
        r"Get-StartApps | Select-Object Name, AppID | ConvertTo-Json"
    )

    # PowerShell returns either dict (single item) or list
    if isinstance(data, dict):
        data = [data]

    catalog: List[AppEntry] = []
    for item in data:
        name = (item.get("Name") or "").strip()
        app_id = (item.get("AppID") or "").strip()
        if name and app_id:
            catalog.append(AppEntry(name=name, app_id=app_id))

    uniq = {(a.name, a.app_id): a for a in catalog}
    return sorted(uniq.values(), key=lambda x: x.name.lower())

def load_or_refresh_catalog(force_refresh: bool = False) -> List[AppEntry]:
    """
    Loads cached catalog or refreshes if cache is old/missing.
    """
    if not force_refresh and os.path.exists(CACHE_PATH):
        try:
            with open(CACHE_PATH, "r", encoding="utf-8") as f:
                cached = json.load(f)
            ts = float(cached.get("timestamp", 0))
            if (time.time() - ts) < CACHE_TTL_SECONDS:
                return [AppEntry(**x) for x in cached.get("catalog", [])]
        except Exception:
            pass  # fall through to rebuild

    catalog = build_startapps_catalog()
    try:
        with open(CACHE_PATH, "w", encoding="utf-8") as f:
            json.dump(
                {"timestamp": time.time(), "catalog": [a.__dict__ for a in catalog]},
                f,
                ensure_ascii=False,
                indent=2,
            )
    except Exception:
        pass
    return catalog

def list_all_software_names() -> List[str]:
    catalog = load_or_refresh_catalog()
    return [a.name for a in catalog]

# -----------------------
# Fuzzy resolving
# -----------------------
def resolve_app(
    spoken: str, catalog: List[AppEntry], min_score: float = 0.72
) -> Optional[Tuple[AppEntry, float]]:
    spoken = clean_app_name(spoken)
    if not spoken:
        return None

    best: Optional[AppEntry] = None
    best_score = 0.0

    for app in catalog:
        score = _similarity(spoken, app.name)
        if score > best_score:
            best_score = score
            best = app

    if best and best_score >= min_score:
        return best, best_score
    return None

# -----------------------
# OPEN (launch)
# -----------------------
def launch_app_by_appid(app_id: str) -> None:
    """
    Launch via shell AppsFolder using Start-Process (works very reliably).
    """
    target = f"shell:AppsFolder\\{app_id}"
    subprocess.Popen(
        ["powershell", "-NoProfile", "-Command", f'Start-Process "{target}"'],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

def launch_app_fallback(name: str) -> None:
    """
    Fallback for some desktop apps: try `start "" "<name>"`.
    """
    name = clean_app_name(name)
    subprocess.Popen(f'start "" "{name}"', shell=True)

def open_any_app(spoken_name: str, catalog: List[AppEntry]) -> bool:
    """
    Open/launch an app (does NOT focus; it may open a new window depending on the app).
    """
    spoken_name = clean_app_name(spoken_name)

    hit = resolve_app(spoken_name, catalog)
    if hit:
        app, score = hit
        print(f"🟢 OPEN matched '{spoken_name}' → '{app.name}' (score={score:.2f})")
        try:
            launch_app_by_appid(app.app_id)
            return True
        except Exception:
            launch_app_fallback(app.name)
            return True

    print(f"❌ OPEN no confident match for: {spoken_name}")
    return False

# -----------------------
# FOCUS (bring existing window to front)
# -----------------------
def _window_is_usable(w) -> bool:
    if not getattr(w, "title", ""):
        return False

    width = getattr(w, "width", None)
    height = getattr(w, "height", None)
    if isinstance(width, int) and isinstance(height, int):
        if width <= 1 or height <= 1:
            return False

    return True

def _force_foreground(hwnd: int) -> None:
    """
    More reliable than pygetwindow.activate() by bypassing Windows 
    focus-stealing restrictions.
    """
    try:
        # 1. Restore the window if it's minimized
        if win32gui.IsIconic(hwnd):
            win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)

        # 2. The "Alt-Key Hack": 
        # Windows often blocks SetForegroundWindow unless the calling 
        # process is the active one. Simulating an ALT keypress bypasses this.
        shell = win32com.client.Dispatch("WScript.Shell")
        shell.SendKeys('%') # Sends the "Alt" key

        # 3. Force the window to the front
        win32gui.SetForegroundWindow(hwnd)
        win32gui.BringWindowToTop(hwnd)
        
    except Exception as e:
        print(f"⚠️ Internal focus error: {e}")

def focus_any_app(spoken_name: str) -> bool:
    # ✅ normalize Whisper mistakes (vs core -> vs code etc.)
    target = normalize_spoken_app(spoken_name)

    if(target=="desktop"):
        # Special case for "focus desktop"
        focus_desktop()
        return True
    if(target=="apps"):
        # Special case for "focus app switcher"
        focus_apps()
        return True
    if not target:
        return False

    windows = [w for w in gw.getAllWindows() if _window_is_usable(w)]
    if not windows:
        print("❌ FOCUS: no usable windows found")
        return False

    # ✅ Adaptive threshold for short targets
    min_score = 0.65 if len(target) <= 6 else 0.75

    best = None
    best_score = 0.0

    for w in windows:
        score = _similarity(target, w.title)
        if score > best_score:
            best_score = score
            best = w

    if not best or best_score < min_score:
        print(
            f"❌ FOCUS no match for '{target}' "
            f"(best_score={best_score:.2f}, min_score={min_score:.2f})"
        )
        return False

    try:
        # ✅ Use Win32 HWND for reliable focusing
        hwnd = getattr(best, "_hWnd", None)
        if hwnd:
            _force_foreground(hwnd)
        else:
            # Fallback
            if getattr(best, "isMinimized", False):
                best.restore()
                time.sleep(0.05)
            best.activate()

        print(f"🟢 FOCUSED '{best.title}' (score={best_score:.2f})")
        return True

    except Exception as e:
        # This can happen due to Windows focus rules even when window exists
        print(f"❌ FOCUS failed for '{target}': {e}")
        return False

def close_any_app(spoken_name: str) -> bool:
    target = normalize_spoken_app(spoken_name)
    if not target:
        return False
    
    if target == "this" or target == "it":
        # Special case for "close this" or "close it"
        keyboard.send("alt+f4")
        print("🟢 SENT close command to focused window")
        return True

    windows = [w for w in gw.getAllWindows() if _window_is_usable(w)]
    if not windows:
        print("❌ CLOSE: no usable windows found")
        return False

    best = None
    best_score = 0.0

    for w in windows:
        score = _similarity(target, w.title)
        if score > best_score:
            best_score = score
            best = w

    if not best or best_score < 0.7:
        print(f"❌ CLOSE no match for '{target}' (best_score={best_score:.2f})")
        return False

    try:
        best.close()
        print(f"🟢 CLOSED '{best.title}' (score={best_score:.2f})")
        return True
    except Exception as e:
        print(f"❌ CLOSE failed for '{target}': {e}")
        return False
    
# -----------------------
# Unified entry point (your assistant can call this)
# -----------------------
def handle_app_action(action: str, target: str, catalog: List[AppEntry]) -> bool:
    action = action.lower().strip()
    target = clean_app_name(target)

    if action == "focus":
        return focus_any_app(target)

    if action == "open":
        return open_any_app(target, catalog)
    
    if action == "close":
        return close_any_app(target)

    if action == "maximize":
        # Maximize is a bit more complex since it requires finding the window and sending a maximize command
        # For simplicity, we can try to focus it first and then send Win+Up to maximize
        if target == "this" or target == "it":
            keyboard.send("win+up")
            print("🟢 MAXIMIZED focused window")
            return True
        if focus_any_app(target):
            keyboard.send("win+up")
            print(f"🟢 MAXIMIZED '{target}'")
            return True
        else:
            print(f"❌ MAXIMIZE failed: couldn't find '{target}' to maximize")
            return False

    if action == "minimize":
        # Minimize is a bit more complex since it requires finding the window and sending a minimize command
        # For simplicity, we can try to focus it first and then send Win+Down to minimize
        if target == "this" or target == "it":
            keyboard.send("win+down")
            print("🟢 MINIMIZED focused window")
            return True
        if focus_any_app(target):
            keyboard.send("win+down")
            print(f"🟢 MINIMIZED '{target}'")
            return True
        else:
            print(f"❌ MINIMIZE failed: couldn't find '{target}' to minimize")
            return False

    raise ValueError(f"Unknown action: {action}")

# Special case for "focus desktop" command since "desktop" isn't a real window title

def focus_desktop():
    try:
        keyboard.send("win+d")
        print("🟢 FOCUSED desktop")
    except Exception as e:
        print(f"❌ FOCUS desktop failed: {e}")

def focus_apps():
    try:
        keyboard.send("win+tab")
        print("🟢 FOCUSED app switcher")
    except Exception as e:
        print(f"❌ FOCUS app switcher failed: {e}")

# -----------------------
# CLI usage (optional)
# -----------------------
if __name__ == "__main__":
    catalog = load_or_refresh_catalog()
    print(f"Loaded {len(catalog)} apps (cache: {CACHE_PATH})\n")

    for name in list_all_software_names()[:50]:
        print(name)
    print("\n(Showing first 50.)")

    # Examples:
    # handle_app_action("open", "fire fox.", catalog)
    # handle_app_action("focus", "vs core", catalog)


