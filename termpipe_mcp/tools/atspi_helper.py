#!/usr/bin/env python3
"""
AT-SPI Helper Script for TermPipe.
Runs under the system Python to access PyGObject and Atspi.
Usage:
  atspi_helper.py query_domain <domain> <app_name>
  atspi_helper.py remote_control <element_id> <action> [payload]
  atspi_helper.py read_state <element_id>
"""

import sys
import json
import time

try:
    import gi
    gi.require_version('Atspi', '2.0')
    from gi.repository import Atspi
except ImportError:
    print(json.dumps({"error": "PyGObject or Atspi not found in this python environment."}))
    sys.exit(1)

# Initialize Atspi
Atspi.init()

DOMAIN_ROLES = {
    "typing": [Atspi.Role.ENTRY, Atspi.Role.TEXT, Atspi.Role.TERMINAL, Atspi.Role.DOCUMENT_TEXT, Atspi.Role.PASSWORD_TEXT],
    "buttons": [Atspi.Role.PUSH_BUTTON, Atspi.Role.TOGGLE_BUTTON, Atspi.Role.RADIO_BUTTON],
    "navigation_menus": [Atspi.Role.MENU_ITEM, Atspi.Role.MENU, Atspi.Role.LINK, Atspi.Role.PAGE_TAB],
    "windows": [Atspi.Role.WINDOW, Atspi.Role.FRAME, Atspi.Role.DIALOG],
    "toggles": [Atspi.Role.CHECK_BOX, Atspi.Role.RADIO_BUTTON, Atspi.Role.TOGGLE_BUTTON],
    "all": []
}

def get_desktop():
    return Atspi.get_desktop(0)

def find_app(name):
    desktop = get_desktop()
    if not desktop:
        return None
    for i in range(desktop.get_child_count()):
        app = desktop.get_child_at_index(i)
        if app and app.get_name() and name.lower() in app.get_name().lower():
            return app
    return None

def find_focused_app():
    desktop = get_desktop()
    if not desktop:
        return None
    for i in range(desktop.get_child_count()):
        app = desktop.get_child_at_index(i)
        if app:
            state = app.get_state_set()
            if state.contains(Atspi.StateType.ACTIVE):
                return app
    return None

def traverse_and_filter(node, target_roles, elements_list, path_prefix=""):
    if not node:
        return
        
    role = node.get_role()
    name = node.get_name()
    if not name:
        name = ""
        
    # If it's a target role, add to list
    if (not target_roles or role in target_roles) and name.strip():
        # Generate a stable ID based on path
        elements_list.append({
            "id": path_prefix,
            "name": name,
            "role": node.get_role_name()
        })
        
    for i in range(node.get_child_count()):
        child = node.get_child_at_index(i)
        new_prefix = f"{path_prefix}_{i}" if path_prefix else str(i)
        traverse_and_filter(child, target_roles, elements_list, new_prefix)

def query_domain(domain, app_name):
    if app_name and app_name.lower() != "focused":
        app = find_app(app_name)
    else:
        app = find_focused_app()
        
    if not app:
        return {"error": "Application not found or no focused application."}
        
    target_roles = DOMAIN_ROLES.get(domain, [])
    elements = []
    
    # Prefix IDs with an identifier for the app index, but for simplicity we just start from root
    traverse_and_filter(app, target_roles, elements, "")
    
    # Shrink the path IDs to something simple like b1, b2, t1, t2 based on domain
    prefix_map = {
        "typing": "t",
        "buttons": "b",
        "navigation_menus": "m",
        "windows": "w",
        "toggles": "x",
        "all": "e"
    }
    short_prefix = prefix_map.get(domain, "e")
    
    simplified = []
    for idx, el in enumerate(elements):
        short_id = f"{short_prefix}{idx+1}"
        simplified.append({
            "id": short_id,
            "name": el["name"],
            "role": el["role"],
            "real_path": el["id"]
        })
        
    return {
        "app": app.get_name(),
        "elements": simplified
    }

def resolve_node_by_path(app, path_str):
    if not path_str:
        return app
    parts = path_str.split('_')
    current = app
    for part in parts:
        if not part: continue
        try:
            idx = int(part)
            current = current.get_child_at_index(idx)
            if not current:
                return None
        except:
            return None
    return current

def remote_control(real_path, action, payload=None):
    app = find_focused_app()
    if not app:
        return {"error": "No focused application."}
        
    node = resolve_node_by_path(app, real_path)
    if not node:
        return {"error": f"Node {real_path} not found."}
        
    try:
        if action == "click":
            action_iface = node.get_action()
            if action_iface and action_iface.get_n_actions() > 0:
                action_iface.do_action(0)
                return {"success": True, "message": "Clicked."}
            else:
                return {"error": "Node does not support click action."}
        elif action == "type":
            editable_iface = node.get_editable_text()
            if editable_iface:
                text_iface = node.get_text()
                if text_iface:
                    editable_iface.delete_text(0, text_iface.get_character_count())
                editable_iface.insert_text(0, str(payload) if payload else "", -1)
                return {"success": True, "message": f"Typed '{payload}'"}
            else:
                comp = node.get_component()
                if comp: comp.grab_focus()
                return {"success": True, "message": "Focused for typing (keyboard synthesis unsupported without layout)."}
        elif action == "focus":
            comp = node.get_component()
            if comp:
                comp.grab_focus()
                return {"success": True, "message": "Focused."}
            return {"error": "Cannot focus node."}
        elif action == "close":
            return {"error": "Close not implemented. Use 'cond key alt+F4' instead."}
        else:
            return {"error": f"Unknown action: {action}"}
    except Exception as e:
        return {"error": str(e)}

def read_state(real_path):
    app = find_focused_app()
    if not app:
        return {"error": "No focused application."}
        
    node = resolve_node_by_path(app, real_path)
    if not node:
        return {"error": f"Node {real_path} not found."}
        
    state_set = node.get_state_set()
    states = state_set.get_states()
    state_names = [Atspi.state_type_get_name(s) for s in states]
    
    text_val = ""
    text_iface = node.get_text()
    if text_iface:
        text_val = text_iface.get_text(0, -1)
        
    return {
        "name": node.get_name(),
        "role": node.get_role_name(),
        "text": text_val,
        "states": state_names
    }

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(json.dumps({"error": "Missing command."}))
        sys.exit(1)
        
    cmd = sys.argv[1]
    
    if cmd == "query_domain":
        domain = sys.argv[2] if len(sys.argv) > 2 else "all"
        app_name = sys.argv[3] if len(sys.argv) > 3 else "focused"
        print(json.dumps(query_domain(domain, app_name)))
        
    elif cmd == "remote_control":
        path = sys.argv[2] if len(sys.argv) > 2 else ""
        action = sys.argv[3] if len(sys.argv) > 3 else ""
        payload = sys.argv[4] if len(sys.argv) > 4 else ""
        print(json.dumps(remote_control(path, action, payload)))
        
    elif cmd == "read_state":
        path = sys.argv[2] if len(sys.argv) > 2 else ""
        print(json.dumps(read_state(path)))
        
    else:
        print(json.dumps({"error": f"Unknown command {cmd}"}))
        
    Atspi.exit()
