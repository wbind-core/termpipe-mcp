"""
cond.py — GreaterTouchTool Wayland window management tools.
Wraps the `cond` CLI binary. All tools return JSON where possible.
Falls back to text output with stderr suppressed.
"""

import json
import shutil
import subprocess
import time
from typing import Optional

_cond = shutil.which("cond")
_condD_PIPES = ["/tmp/cond-universal.pipe", "/tmp/cond-wlroots.pipe"]


def _cond(*args, fmt="json", timeout=15) -> dict | list | str:
    if not _cond:
        return {"error": "cond not found on PATH. Install Conduit CLI."}
    result = subprocess.run(
        [_cond, "--format", fmt, *[str(a) for a in args]],
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    if fmt == "json":
        try:
            return json.loads(result.stdout)
        except json.JSONDecodeError:
            return {"raw": result.stdout.strip(), "stderr": result.stderr.strip()}
    return result.stdout.strip() or result.stderr.strip()


def _cond_pipe(payload: dict) -> str:
    """Send JSON command directly to condd named pipe (tries universal, then wlroots)."""
    import os

    for pipe_path in _condD_PIPES:
        if os.path.exists(pipe_path):
            try:
                with open(pipe_path, "w") as f:
                    f.write(json.dumps(payload) + "\n")
                return "✅ Sent to condd"
            except Exception as e:
                return f"[Error: {e}]"
    return f"[Error: condd pipe not found at any of {_condD_PIPES}. Is condd running?]"


def register_tools(mcp):

    # ── Window info ──────────────────────────────────────────────────────────

    @mcp.tool()
    def cond_get_active() -> str:
        """Get info about the currently active/focused window."""
        return json.dumps(_cond("--get-active"), indent=2)

    @mcp.tool()
    def cond_list_windows() -> str:
        """List all available windows across all workspaces."""
        return json.dumps(_cond("--list"), indent=2)

    # ── Window operations ─────────────────────────────────────────────────────

    @mcp.tool()
    def cond_focus(target: str) -> str:
        """Focus a window by app-id or name (fuzzy match).
        Args:
            target: App ID or window title fragment
        """
        return json.dumps(_cond("--focus", target), indent=2)

    @mcp.tool()
    def cond_close(target: str) -> str:
        """Close a window by app-id or name (fuzzy match).
        Args:
            target: App ID or window title fragment
        """
        return json.dumps(_cond("--close", target), indent=2)

    @mcp.tool()
    def cond_snap(direction: str) -> str:
        """Snap active window to a screen region.
        Args:
            direction: left | right | top | bottom | maximize | center | next | prev
        """
        valid = {"left", "right", "top", "bottom", "maximize", "center", "next", "prev"}
        if direction not in valid:
            return f"[Error: direction must be one of: {', '.join(sorted(valid))}]"
        return json.dumps(_cond("--snap", direction), indent=2)

    @mcp.tool()
    def cond_move_window(window_id: str, x: str, y: str) -> str:
        """Move a window. x/y can be pixels or 0.0-1.0 percentage of screen.
        Args:
            window_id: Window ID from cond_list_windows
            x: X position (pixels or 0.0-1.0)
            y: Y position (pixels or 0.0-1.0)
        """
        return json.dumps(_cond("--move-window", window_id, x, y), indent=2)

    @mcp.tool()
    def cond_resize_window(window_id: str, w: str, h: str) -> str:
        """Resize a window. w/h can be pixels or 0.0-1.0 percentage.
        Args:
            window_id: Window ID from cond_list_windows
            w: Width (pixels or 0.0-1.0)
            h: Height (pixels or 0.0-1.0)
        """
        return json.dumps(_cond("--resize-window", window_id, w, h), indent=2)

    # ── Layout save/restore ───────────────────────────────────────────────────

    @mcp.tool()
    def cond_save_layout(slot: int) -> str:
        """Save current window layout to a numbered slot (1-9).
        Args:
            slot: Layout slot number
        """
        return json.dumps(_cond("--sl", str(slot)), indent=2)

    @mcp.tool()
    def cond_restore_layout(slot: int) -> str:
        """Restore a previously saved window layout.
        Args:
            slot: Layout slot number
        """
        return json.dumps(_cond("--rl", str(slot)), indent=2)

    # ── Input injection ───────────────────────────────────────────────────────

    @mcp.tool()
    def cond_type(text: str) -> str:
        """Type text into the active window via compositor input injection.
        Args:
            text: Text to type
        """
        return json.dumps(_cond("--type", text), indent=2)

    @mcp.tool()
    def cond_key(combo: str) -> str:
        """Send a key combination. Separate keys with space or ,,.
        Examples: 'ctrl+c', 'super,,space', 'ctrl+alt+t'
        Args:
            combo: Key combination string
        """
        return json.dumps(_cond("--key", combo), indent=2)

    @mcp.tool()
    def cond_mouse_move(coords: str) -> str:
        """Move the mouse cursor.
        Args:
            coords: 'x,y' in pixels e.g. '100,200'
        """
        return json.dumps(_cond("--move", coords), indent=2)

    @mcp.tool()
    def cond_mouse_click(button: str = "left") -> str:
        """Click a mouse button.
        Args:
            button: left | right | middle
        """
        return json.dumps(_cond("--click", button), indent=2)

    # ── App operations ────────────────────────────────────────────────────────

    @mcp.tool()
    def cond_launch(app_name: str) -> str:
        """Launch an application by name (uses cond app database, fuzzy match).
        Args:
            app_name: Application name
        """
        return json.dumps(_cond("--launch", app_name), indent=2)

    @mcp.tool()
    def cond_search_apps(pattern: str) -> str:
        """Search installed applications matching a pattern (supports regex).
        Args:
            pattern: Name pattern or regex
        """
        return json.dumps(_cond("--show-apps", pattern), indent=2)

    @mcp.tool()
    def cond_get_app_cmd(app_name: str) -> str:
        """Get the launch command for an app by name.
        Args:
            app_name: Application name
        """
        return json.dumps(_cond("--get-app-cmd", app_name), indent=2)

    # ── Clipboard ─────────────────────────────────────────────────────────────

    @mcp.tool()
    def cond_clipboard_get() -> str:
        """Get current clipboard content."""
        return _cond("--cb", fmt="text")

    @mcp.tool()
    def cond_clipboard_set(text: str) -> str:
        """Set clipboard content.
        Args:
            text: Content to place in clipboard
        """
        return json.dumps(_cond("--cb-set", text), indent=2)

    @mcp.tool()
    def cond_clipboard_paste() -> str:
        """Trigger Ctrl+V to paste current clipboard content into active window."""
        return json.dumps(_cond("--cb-paste"), indent=2)

    # ── Screenshot / OCR ──────────────────────────────────────────────────────

    @mcp.tool()
    def cond_screenshot(path: Optional[str] = None) -> str:
        """Take a full-screen screenshot. Auto-copies to clipboard.
        Args:
            path: Optional save path. If omitted, clipboard only.
        """
        args = ["--sc"]
        if path:
            args.append(path)
        return json.dumps(_cond(*args), indent=2)

    @mcp.tool()
    def cond_ocr() -> str:
        """Capture active window, run AI OCR (qwen-vl via iflow), copy result to clipboard.
        Returns the recognized text."""
        return _cond("--ocr", fmt="text")

    @mcp.tool()
    def cond_ocr_file(path: str) -> str:
        """Run AI OCR on an existing image file and copy result to clipboard.
        Args:
            path: Path to image file
        """
        return _cond("--ocr-file", path, fmt="text")

    # ── Hotkeys ───────────────────────────────────────────────────────────────

    @mcp.tool()
    def cond_list_hotkeys() -> str:
        """List all registered hotkeys."""
        return json.dumps(_cond("--list-hotkeys"), indent=2)

    @mcp.tool()
    def cond_register_hotkey_script(key: str, script: str) -> str:
        """Register a hotkey to execute a shell script.
        Args:
            key:    Key combination e.g. 'ctrl+alt+t'
            script: Shell command or script path to execute
        """
        return json.dumps(_cond("--hotkey-script", f"{key},{script}"), indent=2)

    @mcp.tool()
    def cond_register_hotkey_input(key: str, command: str) -> str:
        """Register a hotkey to execute input commands (type, key, click, etc).
        Args:
            key:     Key combination
            command: Input command string
        """
        return json.dumps(_cond("--hotkey-input", f"{key},{command}"), indent=2)

    @mcp.tool()
    def cond_clear_hotkeys() -> str:
        """Clear all registered hotkeys."""
        return json.dumps(_cond("--clear-hotkeys"), indent=2)

    @mcp.tool()
    def cond_save_hotkeys(path: str) -> str:
        """Save current hotkey config to a file.
        Args:
            path: Destination file path
        """
        return json.dumps(_cond("--save-hotkeys", path), indent=2)

    @mcp.tool()
    def cond_load_hotkeys(path: str) -> str:
        """Load hotkey config from a file.
        Args:
            path: Source file path
        """
        return json.dumps(_cond("--load-hotkeys", path), indent=2)

    # ── Event subscriptions (bounded) ─────────────────────────────────────────

    @mcp.tool()
    def cond_subscribe(topic: str, duration_ms: int = 2000) -> str:
        """Subscribe to a real-time event stream for a bounded duration.
        Collects events and returns them as a JSON list.

        Topics: window | mouse | workspace | application | input |
                menu | workflow | settings | all

        Args:
            topic:       Event topic to subscribe to
            duration_ms: How long to collect events (default 2000ms)
        """
        valid = {
            "window",
            "mouse",
            "workspace",
            "application",
            "input",
            "menu",
            "workflow",
            "settings",
            "all",
        }
        if topic not in valid:
            return f"[Error: topic must be one of: {', '.join(sorted(valid))}]"

        import threading

        flag = f"--sub-{topic}"
        proc = subprocess.Popen(
            [_cond, flag, "--format", "json"],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
        )
        events = []

        def _read():
            for line in proc.stdout:
                line = line.strip()
                if not line:
                    continue
                try:
                    events.append(json.loads(line))
                except json.JSONDecodeError:
                    events.append({"raw": line})

        t = threading.Thread(target=_read, daemon=True)
        t.start()
        t.join(timeout=duration_ms / 1000.0)
        proc.terminate()
        return json.dumps(events, indent=2)

    # ── Daemon pipe ───────────────────────────────────────────────────────────

    @mcp.tool()
    def cond_daemon_send(
        operation: str, target: Optional[str] = None, text: Optional[str] = None
    ) -> str:
        """Send a command directly to the condd daemon via named pipe.
        Faster than subprocess for high-frequency operations.

        Supported operations: getWindow, listWindows, focusWindow, closeWindow,
        maximizeWindow, minimizeWindow, typeText, keyPress, mouseMove,
        mouseClick, launchApp

        Args:
            operation: Operation name
            target:    Target app/window ID (if applicable)
            text:      Text content (for typeText, keyPress)
        """
        payload = {"operation": operation}
        if target:
            payload["appId"] = target
        if text:
            payload["text"] = text
        return _cond_pipe(payload)

    # ── Visual query (Part 6) ─────────────────────────────────────────────────

    @mcp.tool()
    def cond_visual_query(
        question: str,
        path: Optional[str] = None,
        as_schema: bool = False,
    ) -> str:
        """
        Take a screenshot and ask cond's built-in vision model to analyze it.
        Returns plain-text analysis, or structured JSON element map if as_schema=True.

        cond handles the screenshot, vision routing, and model call natively via
        --query and --schema flags. No external endpoints needed from this layer.

        Args:
            question:  What to ask. e.g. "Did the app launch correctly?"
            path:      Optional existing image file. If omitted, takes live screenshot.
            as_schema: If True, returns structured JSON with every UI element mapped
                       to its type, position, state, and the cond action to interact with it.
        """
        args = ["--query", question]
        if path:
            args = ["--ocr-file", path] + args
        if as_schema:
            args.append("--schema")
        return _cond(*args, fmt="text", timeout=35)

    @mcp.tool()
    def cond_verify_launch(
        app_name: str,
        expected_elements: Optional[str] = None,
        wait_ms: int = 1500,
    ) -> str:
        """
        Verify that an application launched successfully by taking a screenshot
        and asking qwen-vl for a structured verdict.

        Returns VERDICT: LAUNCHED|FAILED|PARTIAL + description + any error text.

        Args:
            app_name:          Name of the app
            expected_elements: Comma-separated UI elements expected to be visible
            wait_ms:           Milliseconds to wait before screenshotting (default 1500ms)
        """
        if wait_ms > 0:
            time.sleep(wait_ms / 1000.0)

        if expected_elements:
            question = (
                f"I just launched '{app_name}'. Expected elements: {expected_elements}. "
                f"Reply: VERDICT: LAUNCHED|FAILED|PARTIAL, which elements visible, "
                f"which missing, any errors (quote exactly)."
            )
        else:
            question = (
                f"I just launched '{app_name}'. "
                f"Reply: VERDICT: LAUNCHED|FAILED|PARTIAL, one-sentence description, "
                f"any visible errors (quote exactly)."
            )
        return cond_visual_query(question)
