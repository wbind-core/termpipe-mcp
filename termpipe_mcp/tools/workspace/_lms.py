"""
_lms.py — Local Inference client via kb-bus transport.

Uses llama-cpp-python via kb-lms-daemon.
Transport: kernclip-bus (lms.inference.request / lms.inference.response.<id>)

Public API:
  lms_query()        — sync inference
  lms_query_async()  — fire-and-forget with callback
  lms_available()    — daemon health check
  lms_model()        — current loaded model name
"""
import json
import threading
import uuid
from typing import Callable, Optional

from ._bus import _bus_pub, _bus_get, _bus_poll, _TOPIC_HB

_TOPIC_REQ    = "lms.inference.request"
_POLL_TIMEOUT = 45000  # ms


def lms_available() -> bool:
    """Return True if kb-lms-daemon is up (heartbeat fresher than 30s)."""
    import time
    data = _bus_get(_TOPIC_HB)
    if not data:
        return False
    try:
        hb = json.loads(data)
        return hb.get("status") == "ready" and (time.time() - hb.get("ts", 0)) < 30
    except Exception:
        return False


def lms_model() -> Optional[str]:
    """Return the currently loaded model name from the daemon heartbeat."""
    data = _bus_get(_TOPIC_HB)
    if not data:
        return None
    try:
        return json.loads(data).get("model")
    except Exception:
        return None


def lms_query(
    prompt: str,
    system: str = "",
    max_tokens: int = 256,
    temperature: float = 0.3,
    timeout_ms: int = _POLL_TIMEOUT,
) -> Optional[str]:
    """
    Synchronous inference via kb-lms-daemon.
    Returns response string or None on any failure.
    """
    req_id = uuid.uuid4().hex[:12]
    resp_topic = f"lms.inference.response.{req_id}"

    # Publish request
    ok = _bus_pub(_TOPIC_REQ, json.dumps({
        "id": req_id,
        "prompt": prompt,
        "system": system,
        "max_tokens": max_tokens,
        "temperature": temperature
    }), mime="application/json")
    
    if not ok:
        return None

    # Wait for response via sub-based poll
    res = _bus_poll([resp_topic], timeout_ms=timeout_ms)
    if res:
        topic, data = res
        try:
            resp = json.loads(data)
            if "error" in resp:
                return None
            return resp.get("result")
        except Exception:
            return None
    
    return None


def lms_query_async(
    prompt: str,
    callback: Callable[[Optional[str]], None],
    system: str = "",
    max_tokens: int = 256,
    temperature: float = 0.3,
) -> None:
    """
    Fire-and-forget inference. Calls callback(result) on completion.
    Never blocks the caller.
    """
    def _run():
        result = lms_query(prompt, system=system, max_tokens=max_tokens, temperature=temperature)
        try:
            callback(result)
        except Exception:
            pass
    threading.Thread(target=_run, daemon=True).start()
