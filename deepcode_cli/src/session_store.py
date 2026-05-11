"""
Session Store — persists DeepSeek chat_id + parent_message_id to disk per workspace.

DeepSeek's API is stateful: the server stores the full conversation as long as
you reuse the same chat_session_id and chain parent_message_ids correctly.
By saving these two values we can resume a previous conversation after restart.

Storage location: ~/.deepcode/sessions/<workspace_hash>.json
"""
import os
import json
import hashlib
from pathlib import Path
from typing import Optional, Tuple


def _sessions_dir() -> Path:
    if os.name == 'nt':
        appdata = os.getenv('APPDATA')
        base = Path(appdata) / "DeepCode" if appdata else Path.home() / ".deepcode"
    else:
        base = Path.home() / ".deepcode"
    d = base / "sessions"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _session_file(workspace: str) -> Path:
    key = hashlib.md5(os.path.abspath(workspace).encode()).hexdigest()[:12]
    return _sessions_dir() / f"{key}.json"


def load_session(workspace: str) -> Tuple[Optional[str], Optional[str]]:
    path = _session_file(workspace)
    if not path.exists():
        return None, None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data.get("chat_id"), data.get("parent_message_id")
    except Exception:
        return None, None


def save_session(workspace: str, chat_id: str, parent_message_id: Optional[str]) -> None:
    path = _session_file(workspace)
    data = {
        "chat_id": chat_id,
        "parent_message_id": parent_message_id,
        "workspace": os.path.abspath(workspace),
    }
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def delete_session(workspace: str) -> bool:
    path = _session_file(workspace)
    if path.exists():
        path.unlink()
        return True
    return False


def list_sessions() -> list:
    sessions = []
    for f in _sessions_dir().glob("*.json"):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            sessions.append(data)
        except Exception:
            continue
    return sessions
