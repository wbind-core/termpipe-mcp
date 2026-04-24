import subprocess
import platform
import time
from pathlib import Path

def paste_macos():
    """
    Programmatic paste for macOS leveraging native AppleScript accessibility.
    Simulates: Command + V
    """
    script = 'tell application "System Events" to key code 9 using command down'
    subprocess.run(["osascript", "-e", script], check=True)


def paste_windows(win_exe_path: str = None):
    """
    Programmatic paste for Windows harnessing the C fast-paste binary.
    If no fast-paste binary is specified/found, falls back to PowerShell SendKeys.
    """
    if win_exe_path and Path(win_exe_path).exists():
        try:
            subprocess.run([win_exe_path], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return
        except subprocess.CalledProcessError:
            pass # fallback to powershell on failure

    # Fallback to PowerShell
    script = "[void][System.Reflection.Assembly]::LoadWithPartialName('System.Windows.Forms');[System.Windows.Forms.SendKeys]::SendWait('^v')"
    subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-WindowStyle", "Hidden", "-ExecutionPolicy", "Bypass", "-Command", script], check=True)


def paste_linux():
    """
    Programmatic paste placeholder for Linux. In the primary implementation, we typically
    utilize 'wtype' (Wayland) or 'xdotool' (X11) or the ydotool daemon.
    """
    # Prefer wbind natively if available
    try:
        subprocess.run(["wbind", "--key", "ctrl+v"], check=True)
        return
    except (subprocess.CalledProcessError, FileNotFoundError):
        pass

    try:
        subprocess.run(["xdotool", "key", "ctrl+v"], check=True)
    except (subprocess.CalledProcessError, FileNotFoundError):
        pass
