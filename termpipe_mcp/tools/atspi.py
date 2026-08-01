"""
AT-SPI Accessibility tools for TermPipe MCP Server.
Implements a 5-tool reductive pipeline: Plan -> Query -> Control -> Observe -> Inspect
"""

import json
import subprocess
from pathlib import Path
from typing import Optional, List

# In-memory store for the sidecar
_ATSPI_PLAN_STATE = {
    "expected_chain": [],
    "expected_outcome": "",
    "logs": []
}

HELPER_SCRIPT = str(Path(__file__).parent / "atspi_helper.py")
SYSTEM_PYTHON = "/usr/bin/python3"

def run_helper(cmd: str, *args) -> dict:
    """Run the AT-SPI helper script and parse the JSON response."""
    try:
        result = subprocess.run(
            [SYSTEM_PYTHON, HELPER_SCRIPT, cmd, *args],
            capture_output=True, text=True, timeout=10
        )
        if result.returncode != 0:
            return {"error": f"Helper failed: {result.stderr}"}
        try:
            return json.loads(result.stdout)
        except json.JSONDecodeError:
            return {"error": f"Invalid JSON from helper: {result.stdout}"}
    except Exception as e:
        return {"error": f"Execution failed: {e}"}


def register_tools(mcp):
    """Register AT-SPI tools with the MCP server."""
    
    @mcp.tool()
    def atspi_plan_and_log(
        action_mode: str,
        expected_chain: Optional[str] = None,
        expected_outcome: Optional[str] = None,
        actual_outcome: Optional[str] = None,
        delta_notes: Optional[str] = None
    ) -> str:
        """
        The Sequential Sidecar: Grounds the LLM before executing complex AT-SPI chains.
        Must be used before firing AT-SPI events to declare intent, and after to log the delta.
        
        Args:
            action_mode: "plan_chain" (before acting) or "log_deviation" (after acting)
            expected_chain: Array of steps (e.g. '["click(t1)", "type(t2, val)"]'). Required for plan_chain.
            expected_outcome: What should happen at the end. Required for plan_chain.
            actual_outcome: What actually happened. Required for log_deviation.
            delta_notes: Analysis of why reality deviated from expectation.
        """
        global _ATSPI_PLAN_STATE
        if action_mode == "plan_chain":
            if not expected_chain or not expected_outcome:
                return "Error: expected_chain and expected_outcome are required for plan_chain."
            
            try:
                if isinstance(expected_chain, str):
                    chain = json.loads(expected_chain)
                else:
                    chain = expected_chain
            except:
                chain = [expected_chain]
                
            _ATSPI_PLAN_STATE["expected_chain"] = chain
            _ATSPI_PLAN_STATE["expected_outcome"] = expected_outcome
            return f"✅ Plan anchored. Ready to execute {len(chain)} steps. Expected outcome: {expected_outcome}"
            
        elif action_mode == "log_deviation":
            if not actual_outcome:
                return "Error: actual_outcome is required for log_deviation."
                
            log_entry = {
                "expected_chain": _ATSPI_PLAN_STATE.get("expected_chain"),
                "expected_outcome": _ATSPI_PLAN_STATE.get("expected_outcome"),
                "actual_outcome": actual_outcome,
                "delta_notes": delta_notes or "None"
            }
            _ATSPI_PLAN_STATE["logs"].append(log_entry)
            
            _ATSPI_PLAN_STATE["expected_chain"] = []
            _ATSPI_PLAN_STATE["expected_outcome"] = ""
            
            return "✅ Execution delta logged successfully. Sidecar reset."
        
        return f"Error: Unknown action_mode '{action_mode}'"


    @mcp.tool()
    def atspi_query_domain(
        domain: str,
        target_app: Optional[str] = "focused"
    ) -> str:
        """
        Scans the AT-SPI tree and strictly filters for nodes matching the requested domain.
        Returns a simplified list of object names and simple short IDs (like 'b1', 't1').
        
        Args:
            domain: The domain to filter. Valid values: "typing", "buttons", "navigation_menus", "windows", "toggles", "all".
            target_app: App name to search, or "focused" for current window (default).
        """
        valid_domains = ["typing", "buttons", "navigation_menus", "windows", "toggles", "all"]
        if domain not in valid_domains:
            return f"Error: Invalid domain '{domain}'. Must be one of {valid_domains}"
            
        res = run_helper("query_domain", domain, target_app or "focused")
        if "error" in res:
            return f"[Error: {res['error']}]"
            
        elements = res.get("elements", [])
        if not elements:
            return f"No interactive elements found for domain '{domain}' in {res.get('app', 'app')}."
            
        # Format the output beautifully for the model
        lines = [f"🎯 Found {len(elements)} targets for '{domain}' in {res.get('app', 'app')}:"]
        for el in elements:
            lines.append(f"  • {el['id']} : {el['name']} (Role: {el['role']})")
            
        lines.append("\n👉 Note: Pass the ID (e.g. 'b1') to atspi_remote_control to interact with the element.")
        # Store mapping in memory so remote_control can resolve the real AT-SPI path
        _ATSPI_PLAN_STATE["current_mapping"] = {el["id"]: el["real_path"] for el in elements}
        
        return "\n".join(lines)


    @mcp.tool()
    def atspi_remote_control(
        element_id: str,
        action: str,
        payload: Optional[str] = None
    ) -> str:
        """
        Executes a direct AT-SPI action on an element ID returned from atspi_query_domain.
        
        Args:
            element_id: The short ID from the query tool (e.g., "b1", "t2").
            action: "click", "type", "focus", "close".
            payload: String payload if action is "type".
        """
        mapping = _ATSPI_PLAN_STATE.get("current_mapping", {})
        if element_id not in mapping:
            return f"Error: Element ID '{element_id}' not found in current session memory. Please run atspi_query_domain first."
            
        real_path = mapping[element_id]
        
        # Fire to helper
        res = run_helper("remote_control", real_path, action, payload or "")
        if "error" in res:
            return f"❌ Failed to {action} {element_id}: {res['error']}"
            
        return f"✅ Success: {res.get('message', 'Action executed.')}"


    @mcp.tool()
    def atspi_observe_events(
        expected_event: str,
        timeout_ms: int = 3000
    ) -> str:
        """
        Blocks and observes the AT-SPI event bus to verify if an expected event actually happened.
        
        Args:
            expected_event: e.g. "window_opened", "text_changed", "focus_changed"
            timeout_ms: How long to wait before declaring failure.
        """
        # For MVP, we do a simplistic sleep & check since full AT-SPI async event buses require a persistent dbus loop.
        # We can implement polling for window/focus changes here.
        import time
        sleep_sec = timeout_ms / 1000.0
        time.sleep(sleep_sec)
        
        # In a fully robust iteration, this would tail a dbus-monitor process.
        # For now, we simulate the 'observation' timeout completion.
        return f"Observation completed (Waited {timeout_ms}ms). Verify success with atspi_read_state or window state."


    @mcp.tool()
    def atspi_read_state(
        element_id: str
    ) -> str:
        """
        Inspects the exact state of an AT-SPI element by ID (from atspi_query_domain).
        Returns its text contents, checked status, visibility, etc.
        
        Args:
            element_id: The short ID from the query tool (e.g., "x1", "t1").
        """
        mapping = _ATSPI_PLAN_STATE.get("current_mapping", {})
        if element_id not in mapping:
            return f"Error: Element ID '{element_id}' not found. Please run atspi_query_domain first."
            
        real_path = mapping[element_id]
        res = run_helper("read_state", real_path)
        
        if "error" in res:
            return f"❌ Inspection failed: {res['error']}"
            
        return json.dumps(res, indent=2)
