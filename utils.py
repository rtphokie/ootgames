import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import requests

from config import MLB_WIN_PROBABILITY_URL

_WIN_PROB_CACHE: dict[int, dict] = {}
_WIN_PROB_MIN_FETCH_SECONDS = 3
_WIN_PROB_TREND_WINDOW_SECONDS = 1800
_WIN_PROB_TREND_MAX_POINTS = 24


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


def _current_win_probability(game_pk: int | None) -> tuple[float | None, float | None]:
    if not game_pk:
        return None, None

    now = time.time()
    cache_entry = _WIN_PROB_CACHE.get(game_pk)
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

    _WIN_PROB_CACHE[game_pk] = {
        "fetched_at": now,
        "home": home_probability,
        "away": away_probability,
        "history": history,
    }

    return home_probability, away_probability


def _win_probability_trend(game_pk: int | None, team: str) -> dict[str, str]:
    if not game_pk:
        return {"points": "", "direction": "flat"}

    cache_entry = _WIN_PROB_CACHE.get(game_pk)
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
