from datetime import datetime, timezone
import json
import os
from threading import Lock
from urllib.parse import urlparse

_LOG_FILE = os.path.join(os.path.dirname(__file__), "statsapi_calls.log")
_LOG_LOCK = Lock()


def log_statsapi_call(url: str, params: dict | None = None, method: str = "GET") -> None:
    """Append a timestamped line for outbound requests to statsapi.mlb.com."""
    try:
        parsed = urlparse(url)
    except Exception:
        return

    host = (parsed.netloc or "").lower()
    if host != "statsapi.mlb.com":
        return

    timestamp = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    serialized_params = json.dumps(params or {}, sort_keys=True, separators=(",", ":"))
    line = f"{timestamp} | {method.upper()} {url} | params={serialized_params}\n"

    try:
        with _LOG_LOCK:
            with open(_LOG_FILE, "a", encoding="utf-8") as f:
                f.write(line)
    except OSError:
        # Never fail the app because logging could not be written.
        return
