"""speak tools — realtime TTS on Craig's box.

Thin client for the Hank TTS daemon (127.0.0.1:8011). Engine, voice, and
language come from the daemon's user defaults
(~/.config/speak/defaults.json) — change them any time with the
interactive panel:

    /home/craig/.voiceai-venv/bin/python /home/craig/Hank/tts_daemon.py -i

This tool takes no flags or extra params by design: just the text.

Both paths are thin: no audio files cross the wire to the caller; playback
happens on this machine's speakers.

speak() pings the daemon before queueing anything: if it cannot be
reached, the call fails fast and nothing is spoken into an empty room.

Ambient layer (added 2026-10-01 at Craig's direction): after a text is
queued, speak() checks whether his Muse client — the CherryStudio
mini-app wrapping muse.ai — has a window on the desktop. Speech is
the attention layer when the client is not open, so if the window is
absent, speak() also fires a rich kb notification (detached,
throttled) carrying the spoken text, a reply box, and buttons. The
reply publishes to kb topic "hank.reply", which a Hank-side hook
surfaces into the chat record. Button actions: Open Muse Mini sends his
mini-app hotkey (wput --key shift+super+h, cmd:); Open in Browser and
Dismiss remain stubs (topic: hank.stub.*) until he assigns the real
commands. Presence is
probed with cond --list (window-level: the Electron process can
linger with no window, and the window is what matters), published to
kb topic "Hank.appstate" on every probe; the process scan is only a
fallback if cond fails. This layer must never break or delay speech:
every failure inside it is swallowed.
"""
import glob
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request

from mcp.server.fastmcp import FastMCP

DAEMON = "http://127.0.0.1:8011"  # Hank TTS daemon
KB = "/home/craig/.local/bin/kb"
COND = "/home/craig/.local/bin/cond"
CHERRY_ARGV0 = "/opt/Cherry Studio/CherryStudio"
APPSTATE_TOPIC = "Hank.appstate"
APPSTATE_RUNNING = "Remote Hank Client Running"
APPSTATE_NOT_RUNNING = "Remote Hank Client Not Running"
REPLY_TOPIC = "hank.reply"
NOTIFY_THREAD = "hank-speak"
NOTIFY_MIN_INTERVAL_S = 180.0
NOTIFY_STATE = "/tmp/hank_speak_notify_state.json"
NOTIFY_TIMEOUT_S = 300
NOTIFY_BODY_MAX = 600
KB_BIN = KB

TTS_TOPICS = ("speak.tts.engine", "speak.tts.voice", "speak.tts.voice_design",
              "speak.tts.speed", "speak.tts.ref_wav")
TTS_KEYS = ("engine", "voice", "voice_design", "speed", "ref_wav")


def kb_defaults():
    """speak.tts.* p-c topics as a dict; {} when kb is unreachable."""
    try:
        out = subprocess.run(
            [KB_BIN, "get", "--topics", ",".join(TTS_TOPICS)],
            capture_output=True, text=True, timeout=5).stdout
        out = re.sub(r"\x1b\[[0-9;]*m", "", out)
        vals = out.split("\n")
        if vals and vals[-1] == "":
            vals.pop()
        vals += [""] * (len(TTS_KEYS) - len(vals))
        return {k: v.strip() for k, v in zip(TTS_KEYS, vals) if v.strip()}
    except Exception:
        return {}


def kb_pub(child, value):
    """Publish one child value under speak.tts. Returns True on success."""
    try:
        subprocess.run([KB_BIN, "pub-pc", "speak.tts", child, value or ""],
                       capture_output=True, text=True, timeout=5, check=True)
        return True
    except Exception:
        return False



def _unreachable() -> str:
    return (
        f"[speak: TTS daemon not reachable at {DAEMON} — not spoken. "
        "Start it with: /home/craig/.voiceai-venv/bin/python /home/craig/Hank/tts_daemon.py start]"
    )


def _ping(timeout: float = 2.0) -> bool:
    """True only if the TTS daemon answers /health with a 200."""
    try:
        with urllib.request.urlopen(DAEMON + "/health", timeout=timeout) as resp:
            return resp.status == 200
    except Exception:
        return False


def _post(path: str, payload: dict, timeout: float = 10.0) -> str:
    req = urllib.request.Request(
        DAEMON + path,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read().decode()
    except urllib.error.URLError:
        return _unreachable()


def _cherry_running() -> bool:
    """True if the CherryStudio client process is alive on this box."""
    for cmdline_path in glob.glob("/proc/[0-9]*/cmdline"):
        try:
            with open(cmdline_path, "rb") as fh:
                argv0 = fh.read().split(b"\x00", 1)[0].decode(errors="replace")
            if argv0 == CHERRY_ARGV0:
                return True
        except Exception:
            continue
    return False


def _probe_client() -> bool:
    """Window-level presence: True if a CherryStudio window exists.

    Primary signal is cond --list: the window is the presence that
    matters, and the Electron process can linger without one. Falls
    back to the process scan if cond itself fails. Publishes the
    result to kb topic Hank.appstate, in Craig's wording, on every
    probe, so any component can read the state off the bus.
    """
    running = None
    try:
        out = subprocess.run(
            [COND, "--list"], capture_output=True, text=True, timeout=4
        ).stdout
        windows = json.loads(out)
        running = any(
            "cherry" in str(w.get("wm_class", "")).lower()
            or "cherry" in str(w.get("title", "")).lower()
            for w in windows
        )
    except Exception:
        running = None
    if running is None:
        running = _cherry_running()
    try:
        subprocess.Popen(
            [
                KB,
                "pub",
                APPSTATE_TOPIC,
                APPSTATE_RUNNING if running else APPSTATE_NOT_RUNNING,
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    except Exception:
        pass
    return running


def _notify_due() -> bool:
    """Throttle: at most one client-absent notification per interval."""
    try:
        with open(NOTIFY_STATE) as fh:
            last = float(json.load(fh).get("last", 0.0))
    except Exception:
        last = 0.0
    return (time.time() - last) >= NOTIFY_MIN_INTERVAL_S


def _mark_notified() -> None:
    try:
        with open(NOTIFY_STATE, "w") as fh:
            json.dump({"last": time.time()}, fh)
    except Exception:
        pass


def _maybe_notify_client_absent(text: str) -> str:
    """Fire the ambient kb notification when CherryStudio is not running.

    Returns a short suffix for speak()'s result string, or "" when no
    notification was fired. Never raises: speech is the primary job.
    """
    try:
        if _probe_client():
            return ""
        if not _notify_due():
            return ""
        body = text if len(text) <= NOTIFY_BODY_MAX else text[: NOTIFY_BODY_MAX - 3] + "..."
        cmd = [
            KB,
            "notify",
            "Hank",
            "--body",
            body,
            "--app-name",
            "Hank",
            "--thread",
            NOTIFY_THREAD,
            "--reply",
            "--reply-topic",
            REPLY_TOPIC,
            "--timeout",
            str(NOTIFY_TIMEOUT_S),
            "--button",
            "Open Muse Mini:cmd:/home/craig/.local/bin/wput --key shift+super+h",
            "--button",
            "Open in Browser:topic:hank.stub.open_browser",
            "--button",
            "Dismiss:topic:hank.stub.dismiss",
        ]
        subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        _mark_notified()
        return " [client absent: kb notify fired]"
    except Exception:
        return ""


def register_tools(mcp: FastMCP):
    @mcp.tool()
    def speak(text: str) -> str:
        """
        Speak text aloud on this machine, in realtime.

        Takes only the text — no flags, no extra params. Engine, voice,
        voice-design description, speed, and clone-ref-wav come from the
        speak.tts.* topics on the kb bus; change them any time with the
        interactive panel:
        /home/craig/.voiceai-venv/bin/python /home/craig/Hank/tts_daemon.py -i

        Pings the daemon first: if unreachable, returns a not-spoken error
        and queues nothing. Returns as soon as the text is queued; playback
        happens on the box's speakers. If the CherryStudio Muse client is
        not running, also fires a throttled kb notification carrying the
        text, a reply box (kb topic hank.reply), and stub buttons.
        """
        if not _ping():
            return _unreachable()
        d = kb_defaults()
        engine = (d.get("engine") or "sopro").strip().lower()
        if engine not in ("sopro", "qwen3", "supertonic"):
            engine = "sopro"
        payload = {"text": text, "engine": engine}
        if engine == "qwen3":
            if d.get("voice_design"):
                payload["voice"] = d["voice_design"]
        elif d.get("voice"):
            payload["voice"] = d["voice"]
        if d.get("speed"):
            payload["speed"] = d["speed"]
        if d.get("ref_wav"):
            payload["ref_wav"] = d["ref_wav"]
        resp = _post("/speak", payload)
        if resp.startswith("[speak:"):
            return resp
        note = _maybe_notify_client_absent(text)
        preview = text[:80] + ("..." if len(text) > 80 else "")
        return f"queued for speech ({engine}): {preview}{note}"

    @mcp.tool()
    def speak_stop() -> str:
        """Stop current speech playback and clear the speak queue."""
        return _post("/stop", {})
