import requests
from config import MLB_WIN_PROBABILITY_URL
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo


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


def _current_win_probability(game_pk: int | None) -> tuple[float | None, float | None]:
    if not game_pk:
        return None, None

    try:
        response = requests.get(
            MLB_WIN_PROBABILITY_URL.format(game_pk=game_pk),
            timeout=3,
        )
    except requests.RequestException:
        return None, None

    if not response.ok:
        return None, None

    payload = response.json()
    if isinstance(payload, list) and payload:
        latest = payload[-1] or {}
    elif isinstance(payload, dict):
        latest = payload
    else:
        return None, None

    home_probability = latest.get("homeTeamWinProbability")
    away_probability = latest.get("awayTeamWinProbability")

    if not isinstance(home_probability, (int, float)) or not isinstance(
        away_probability, (int, float)
    ):
        return None, None

    return float(home_probability), float(away_probability)


def _record_string(wins, losses) -> str:
    if wins is None or losses is None:
        return ""
    return f"{wins}-{losses}"


# --- Helpers ---


def _team_logo_url(team_id: int | None) -> str:
    """Return the MLB dark-cap SVG logo URL for a team, or empty string if no ID."""
    if not team_id:
        return ""
    return f"https://www.mlbstatic.com/team-logos/team-cap-on-dark/{team_id}.svg"


def _last_name(name: str | None) -> str:
    """Return the last word of a full name string, or empty string."""
    if not name:
        return ""
    parts = name.strip().split()
    return parts[-1] if parts else ""


def _safe_int(value, default=0):
    """Coerce value to int, returning default on failure."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _gate_time_start(
    game_date_raw: str | None, timezone: str = "America/New_York"
) -> str:
    """Convert an ISO 8601 UTC game start datetime to a local time string like '7:05 PM ET'."""
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
    """Validate and return a timezone string, falling back to default if invalid."""
    timezone = (timezone_raw or "").strip() or default
    try:
        ZoneInfo(timezone)
    except Exception:
        return default
    return timezone


def _today_iso_in_timezone(timezone: str) -> str:
    """Return today's date as YYYY-MM-DD in the given timezone."""
    return datetime.now(ZoneInfo(timezone)).date().isoformat()


def _normalized_iso_date(date_raw: str | None, timezone: str) -> str:
    """Parse a YYYY-MM-DD date string, defaulting to today in the given timezone."""
    if not date_raw:
        return _today_iso_in_timezone(timezone)
    try:
        return datetime.strptime(date_raw, "%Y-%m-%d").date().isoformat()
    except ValueError:
        return _today_iso_in_timezone(timezone)


def _shift_iso_date(date_raw: str, days: int) -> str:
    """Return a YYYY-MM-DD date shifted by the given number of days."""
    base_date = datetime.strptime(date_raw, "%Y-%m-%d").date()
    return (base_date + timedelta(days=days)).isoformat()


def _display_date(date_raw: str | None) -> str:
    """Format a YYYY-MM-DD string as a human-readable date, e.g. 'Mon, Apr 20, 2026'."""
    if not date_raw:
        return ""
    try:
        parsed_date = datetime.strptime(date_raw, "%Y-%m-%d")
    except ValueError:
        return date_raw
    return parsed_date.strftime("%a, %b %d, %Y")


def _format_probability(value) -> str:
    """Round a 0–100 float win probability to an integer percent string, e.g. '63%'."""
    if isinstance(value, (int, float)):
        return f"{int(round(value))}%"
    return ""


def _current_win_probability(game_pk: int | None) -> tuple[float | None, float | None]:
    """
    Fetch the latest win probability for a live game from the MLB API.

    Returns (home_probability, away_probability) as floats on the 0–100 scale,
    or (None, None) on any failure.
    """
    if not game_pk:
        return None, None

    try:
        response = requests.get(
            MLB_WIN_PROBABILITY_URL.format(game_pk=game_pk),
            timeout=3,
        )
    except requests.RequestException:
        return None, None

    if not response.ok:
        return None, None

    payload = response.json()
    # The endpoint returns a list of play-by-play entries; the last entry is the most recent.
    if isinstance(payload, list) and payload:
        latest = payload[-1] or {}
    elif isinstance(payload, dict):
        latest = payload
    else:
        return None, None

    home_probability = latest.get("homeTeamWinProbability")
    away_probability = latest.get("awayTeamWinProbability")

    if not isinstance(home_probability, (int, float)) or not isinstance(
        away_probability, (int, float)
    ):
        return None, None

    return float(home_probability), float(away_probability)


def _record_string(wins, losses) -> str:
    """Format wins and losses as 'W-L', or empty string if either value is missing."""
    if wins is None or losses is None:
        return ""
    return f"{wins}-{losses}"
