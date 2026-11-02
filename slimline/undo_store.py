import json
import subprocess

def save_edit_for_undo(session_id: str, old_content: str, path: str):
    """
    Saves an edit for undo by pushing it to the kernclip-bus (kb) under an incrementing topic.
    """
    try:
        # First, find the current head or list topics to find the highest ollama.tooluse.NNN
        res = subprocess.run(["kb", "kc_topics"], capture_output=True, text=True, check=True)
        topics = [t.strip() for t in res.stdout.splitlines() if t.strip().startswith("ollama.tooluse.")]
        
        highest = 0
        for t in topics:
            try:
                num = int(t.split(".")[-1])
                highest = max(highest, num)
            except ValueError:
                pass
                
        next_num = highest + 1
        topic_name = f"ollama.tooluse.{next_num:03d}"
        
        payload = json.dumps({
            "session_id": session_id,
            "path": path,
            "old_content": old_content
        })
        
        # Publish the undo data to the bus
        subprocess.run(["kb", "pub", topic_name, payload], check=True, capture_output=True)
        
        # Optionally, clean up oldest if > 50 edits
        if next_num > 50:
            # We don't have a direct "delete topic" in standard kb, 
            # but we can overwrite it with empty data to save space if needed.
            # In an immutable bus, it rolls off automatically based on daemon retention,
            # or we just rely on the bus's own ring buffer settings.
            pass

    except Exception as e:
        # Fallback logging if the bus fails
        print(f"Warning: Failed to push undo state to bus: {e}")

def pop_last_edits(session_id: str, n: int = 1):
    """
    Retrieves the last `n` edits for the session from the bus and returns them,
    or None if unable to retrieve.
    Returns a list of dicts: [{"path": "...", "old_content": "..."}]
    """
    try:
        res = subprocess.run(["kb", "kc_topics"], capture_output=True, text=True, check=True)
        topics = [t.strip() for t in res.stdout.splitlines() if t.strip().startswith("ollama.tooluse.")]
        
        # Sort by suffix number
        topics.sort(key=lambda t: int(t.split(".")[-1]))
        
        edits = []
        # Pop the last N topics
        to_retrieve = topics[-n:]
        
        for topic in to_retrieve:
            get_res = subprocess.run(["kb", "get", topic], capture_output=True, text=True, check=True)
            data_str = get_res.stdout.strip()
            if data_str:
                data = json.loads(data_str)
                if data.get("session_id") == session_id:
                    edits.append(data)
                    
        return edits
        
    except Exception as e:
        print(f"Warning: Failed to fetch undo state from bus: {e}")
        return []
