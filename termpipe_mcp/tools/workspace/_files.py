"""
File-system helpers — artifact dirs, versioned writes, metadata.
"""
import json
from pathlib import Path
from datetime import datetime, timezone

try:
    from termpipe_mcp.helpers import TERMPIPE_DIR
    from termpipe_mcp.tools.workspace._bus import _ARTIFACTS_ROOT
except ImportError:
    from helpers import TERMPIPE_DIR
    from _bus import _ARTIFACTS_ROOT

# ---------------------------------------------------------------------------
# File-layer (human-readable + .resolved.N versioned snapshots)
# ---------------------------------------------------------------------------

def _artifact_dir(project_name: str) -> Path:
    d = _ARTIFACTS_ROOT / project_name
    d.mkdir(parents=True, exist_ok=True)
    return d


def _write_artifact_files(project_name: str, name: str, content: str, version: int) -> Path:
    d = _artifact_dir(project_name)
    main = d / name
    main.write_text(content, encoding="utf-8")
    snapshot = d / f"{name}.resolved.{version}"
    snapshot.write_text(content, encoding="utf-8")
    return main


def _write_metadata(
    project_name: str, name: str, artifact_type: str,
    summary: str | None, version: int
) -> None:
    d = _artifact_dir(project_name)
    meta = {
        "artifactType": artifact_type,
        "summary": summary or "",
        "updatedAt": datetime.now(timezone.utc).isoformat(),
        "version": str(version),
    }
    (d / f"{name}.metadata.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")


