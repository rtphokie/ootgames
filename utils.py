import json
import os
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import requests

from config import MLB_WIN_PROBABILITY_URL

_WIN_PROB_MIN_FETCH_SECONDS = 3
_WIN_PROB_TREND_WINDOW_SECONDS = 1800
_WIN_PROB_TREND_MAX_POINTS = 24
_WIN_PROB_MAX_GAMES_PER_TEAM = 2

_CACHE_FILE = os.path.join(os.path.dirname(__file__), "win_prob_cache.json")

# In-memory mirror of the disk cache, loaded once at startup.
_WIN_PROB_CACHE: dict = {"games": {}, "team_games": {}}


def _load_disk_cache() -> None:
    """Load the disk cache into memory. Called once at import time."""
    global _WIN_PROB_CACHE
    try:
        with open(_CACHE_FILE, "r") as f:
            data = json.load(f)
        if isinstance(data, dict) and "games" in data and "team_games" in data:
            # Restore history tuples (JSON stores them as lists).
            for entry in data["games"].values():
                entry["history"] = [tuple(s) for s in entry.get("history", [])]
            _WIN_PROB_CACHE = data
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        pass


def _save_disk_cache() -> None:
    """Persist the in-memory cache to disk."""
    try:
        with open(_CACHE_FILE, "w") as f:
            json.dump(_WIN_PROB_CACHE, f)
    except OSError:
        pass


def _prune_cache(home_team_id: int | None, away_team_id: int | None, game_pk: int) -> None:
    """Ensure each team retains at most _WIN_PROB_MAX_GAMES_PER_TEAM game entries."""
    team_games = _WIN_PROB_CACHE["team_games"]
    games = _WIN_PROB_CACHE["games"]
    key = str(game_pk)

    for team_id in filter(None, [home_team_id, away_team_id]):
        tid = str(team_id)
        known = team_games.get(tid, [])
        if key not in known:
            known.append(key)
        # Keep only the most recent N game_pks (last N in insertion order).
        if len(known) > _WIN_PROB_MAX_GAMES_PER_TEAM:
            removed = known[: len(known) - _WIN_PROB_MAX_GAMES_PER_TEAM]
            known = known[len(known) - _WIN_PROB_MAX_GAMES_PER_TEAM :]
            # Remove games no longer referenced by any team.
            all_referenced = {pk for pks in team_games.values() for pk in pks}
            for old_pk in removed:
                if old_pk not in all_referenced:
                    games.pop(old_pk, None)
        team_games[tid] = known


_load_disk_cache()


def _team_logo_url(team_id: int | None) -> str:
    if not team_id:
        return ""
    return f"https://www.mlbstatic.com/team-logos/team-cap-on-dark/{team_id}.svg"


def _last_name(name: str | None) -> str:
    if not name:
        return ""
    parts = name.strip().split()
    return parts[-1] if parts else ""


def _safe_int(value, default=0):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _gate_time_start(
    game_date_raw: str | None, timezone: str = "America/New_York"
) -> str:
    if not game_date_raw:
        return ""
    try:
        game_dt_utc = datetime.fromisoformat(game_date_raw.replace("Z", "+00:00"))
    except ValueError:
        return ""
    try:
        game_dt_local = game_dt_utc.astimezone(ZoneInfo(timezone))
    except Exception:
        return ""
    return game_dt_local.strftime("%I:%M %p %Z").lstrip("0")


def _normalized_timezone(
    timezone_raw: str | None, default: str = "America/New_York"
) -> str:
    timezone = (timezone_raw or "").strip() or default
    try:
        ZoneInfo(timezone)
    except Exception:
        return default
    return timezone


def _today_iso_in_timezone(timezone: str) -> str:
    return datetime.now(ZoneInfo(timezone)).date().isoformat()


def _normalized_iso_date(date_raw: str | None, timezone: str) -> str:
    if not date_raw:
        return _today_iso_in_timezone(timezone)
    try:
        return datetime.strptime(date_raw, "%Y-%m-%d").date().isoformat()
    except ValueError:
        return _today_iso_in_timezone(timezone)


def _shift_iso_date(date_raw: str, days: int) -> str:
    base_date = datetime.strptime(date_raw, "%Y-%m-%d").date()
    return (base_date + timedelta(days=days)).isoformat()


def _display_date(date_raw: str | None) -> str:
    if not date_raw:
        return ""
    try:
        parsed_date = datetime.strptime(date_raw, "%Y-%m-%d")
    except ValueError:
        return date_raw
    return parsed_date.strftime("%a, %b %d, %Y")


def _format_probability(value) -> str:
    if isinstance(value, (int, float)):
        return f"{int(round(value))}%"
    return ""


def _record_string(wins, losses) -> str:
    if wins is None or losses is None:
        return ""
    return f"{wins}-{losses}"


def _sparkline_points(
    values: list[float], width: int = 64, height: int = 18, padding: int = 2
) -> str:
    if len(values) < 2:
        return ""

    min_value = min(values)
    max_value = max(values)
    if max_value == min_value:
        y = (height - padding) - ((height - (2 * padding)) / 2)
        step = (width - (2 * padding)) / (len(values) - 1)
        return " ".join(
            f"{padding + (idx * step):.2f},{y:.2f}" for idx in range(len(values))
        )

    step = (width - (2 * padding)) / (len(values) - 1)
    points = []
    for idx, value in enumerate(values):
        normalized = (value - min_value) / (max_value - min_value)
        x = padding + (idx * step)
        y = (height - padding) - (normalized * (height - (2 * padding)))
        points.append(f"{x:.2f},{y:.2f}")
    return " ".join(points)


def _current_win_probability(
    game_pk: int | None,
    home_team_id: int | None = None,
    away_team_id: int | None = None,
) -> tuple[float | None, float | None]:
    if not game_pk:
        return None, None

    now = time.time()
    key = str(game_pk)
    cache_entry = _WIN_PROB_CACHE["games"].get(key)
    if cache_entry and (now - cache_entry.get("fetched_at", 0)) < _WIN_PROB_MIN_FETCH_SECONDS:
        return cache_entry.get("home"), cache_entry.get("away")

    try:
        response = requests.get(
            MLB_WIN_PROBABILITY_URL.format(game_pk=game_pk),
            timeout=3,
        )
    except requests.RequestException:
        if cache_entry:
            return cache_entry.get("home"), cache_entry.get("away")
        return None, None

    if not response.ok:
        if cache_entry:
            return cache_entry.get("home"), cache_entry.get("away")
        return None, None

    payload = response.json()
    if isinstance(payload, list) and payload:
        latest = payload[-1] or {}
    elif isinstance(payload, dict):
        latest = payload
    else:
        if cache_entry:
            return cache_entry.get("home"), cache_entry.get("away")
        return None, None

    home_probability = latest.get("homeTeamWinProbability")
    away_probability = latest.get("awayTeamWinProbability")

    if not isinstance(home_probability, (int, float)) or not isinstance(
        away_probability, (int, float)
    ):
        if cache_entry:
            return cache_entry.get("home"), cache_entry.get("away")
        return None, None

    home_probability = float(home_probability)
    away_probability = float(away_probability)

    history = list((cache_entry or {}).get("history", []))
    history.append((now, home_probability, away_probability))

    cutoff = now - _WIN_PROB_TREND_WINDOW_SECONDS
    history = [sample for sample in history if sample[0] >= cutoff]
    history = history[-_WIN_PROB_TREND_MAX_POINTS:]

    _WIN_PROB_CACHE["games"][key] = {
        "fetched_at": now,
        "home": home_probability,
        "away": away_probability,
        "history": history,
    }

    _prune_cache(home_team_id, away_team_id, game_pk)
    _save_disk_cache()

    return home_probability, away_probability


def _win_probability_trend(game_pk: int | None, team: str) -> dict[str, str]:
    if not game_pk:
        return {"points": "", "direction": "flat"}

    cache_entry = _WIN_PROB_CACHE["games"].get(str(game_pk))
    if not cache_entry:
        return {"points": "", "direction": "flat"}

    history = cache_entry.get("history", [])
    if not history:
        return {"points": "", "direction": "flat"}

    team_index = 1 if team == "home" else 2
    values = [float(sample[team_index]) for sample in history if len(sample) > team_index]
    if len(values) < 2:
        return {"points": "", "direction": "flat"}

    delta = values[-1] - values[0]
    if delta > 0.25:
        direction = "up"
    elif delta < -0.25:
        direction = "down"
    else:
        direction = "flat"

    return {"points": _sparkline_points(values), "direction": direction}
