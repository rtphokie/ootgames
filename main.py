from datetime import datetime
import os
from zoneinfo import ZoneInfo
from utils import (
    _team_logo_url,
    _last_name,
    _safe_int,
    _display_date,
    _is_within_next_hour,
    _gate_time_start,
    _normalized_timezone,
    _normalized_iso_date,
    _record_string,
    _shift_iso_date,
    _format_probability,
    _current_win_probability,
    _win_probability_trend,
    _win_probability_area_chart,
    _bust_standings_cache,
    _fetch_statsapi_json,
    _ordinal,
)

from config import MLB_SCHEDULE_URL, MLB_STANDINGS_URL, MLB_GAME_FEED_URL, MLB_SPORTS_URL

import requests
from flask import Flask, jsonify, render_template, request
from api_logging import log_statsapi_call

# MLB Stats API docs: https://github.com/toddrob99/MLB-StatsAPI/wiki/Endpoints

app = Flask(__name__)

# Track game_pks known to be final so we can bust standings cache when new games finish.
_FINAL_GAME_PKS: set[int] = set()


def _is_warmup_status(detailed_state: str | None) -> bool:
    state = (detailed_state or "").strip().lower()
    return "warm" in state


def _is_postponed_status(detailed_state: str | None) -> bool:
    state = (detailed_state or "").strip().lower()
    return "postpon" in state


def _is_cancelled_status(detailed_state: str | None) -> bool:
    state = (detailed_state or "").strip().lower()
    return "cancel" in state


_WALK_EVENTS = frozenset({"walk", "intent walk"})
_STEAL_EVENTS = frozenset({"stolen base 2b", "stolen base 3b", "stolen base home"})


def _base_indicator(all_plays: list, offense: dict, base: str) -> str:
    """Return 'W', 'S', or '' for the runner on *base* ('first'/'second'/'third').

    Logic: scan all plays in reverse to find the most recent event that placed
    this runner at their current base.  If that event was a walk → 'W'.
    If it was a stolen base → 'S'.  Any other advancement (hit, error, etc.) → ''.
    """
    runner = offense.get(base)
    if not runner:
        return ""
    runner_id = runner.get("id")
    if runner_id is None:
        return ""

    base_number = {"first": 1, "second": 2, "third": 3}.get(base)

    for play in reversed(all_plays):
        # Check runner movements within this play first.
        for runner_event in (play.get("runners") or []):
            movement = runner_event.get("movement") or {}
            details = runner_event.get("details") or {}
            person_id = (runner_event.get("details") or {}).get("runner", {}).get("id") \
                        or (runner_event.get("credits") and None)
            # runner id lives under details.runner
            person_id = ((runner_event.get("details") or {}).get("runner") or {}).get("id")
            if person_id != runner_id:
                continue
            end_base = movement.get("end")
            end_number = {"1B": 1, "2B": 2, "3B": 3}.get(end_base)
            if end_number != base_number:
                continue
            # This event placed the runner at the target base.
            event = (details.get("event") or "").lower()
            if event in _STEAL_EVENTS:
                return "S"
            # Any other movement (hit, FC, error, etc.) clears the indicator.
            return ""

        # Also check if the runner was the batter in this play and reached first via walk.
        if base_number == 1:
            matchup = play.get("matchup") or {}
            batter_id = (matchup.get("batter") or {}).get("id")
            if batter_id == runner_id:
                event = ((play.get("result") or {}).get("event") or "").lower()
                if event in _WALK_EVENTS:
                    return "W"
                # Batter reached another way — clear indicator.
                return ""

    return ""

# Division IDs to display on /standings, in render order.
# Verified against /api/v1/standings: AL West=200, AL East=201, NL West=203, NL East=204.
STANDINGS_DIVISIONS = [
    (204, "NL East"),
    (203, "NL West"),
    (201, "AL East"),
    (200, "AL West"),
]

_DIVISION_LABELS = {
    200: "AL West",
    201: "AL East",
    202: "AL Central",
    203: "NL West",
    204: "NL East",
    205: "NL Central",
}




# --- Routes ---

_ALLOWED_SPORT_NAME_FRAGMENTS = (
    "major league baseball",
    "triple-a",
    "double-a",
    "high-a",
    "single-a",
    "low-a",
    "international league",
    "independent",
)

# Lower number = shown first in the dropdown (single-A → MLB).
_SPORT_LEVEL_ORDER = (
    ("independent", 1),
    ("low-a", 2),
    ("single-a", 3),
    ("high-a", 4),
    ("double-a", 5),
    ("triple-a", 6),
    ("major league baseball", 7),
)


def _sport_level(name: str) -> int:
    name_lower = name.lower()
    for frag, level in _SPORT_LEVEL_ORDER:
        if frag in name_lower:
            return level
    return 99


@app.get("/otg")
def otg():
    """
    Schedule page — list all MLB games for the selected date.

    Query params:
      date (YYYY-MM-DD): date to display; defaults to today in the user's timezone.
      tz / timezone: IANA timezone string; defaults to America/New_York.
            sportId (int): sports id from StatsAPI /sports endpoint; defaults to 1 (MLB).
      format=json: return raw game data as JSON instead of HTML.
    """
    timezone = _normalized_timezone(
        request.args.get("tz") or request.args.get("timezone")
    )
    sport_id = _safe_int(request.args.get("sportId"), 1)
    if sport_id <= 0:
        sport_id = 1
    today_date = _normalized_iso_date(None, timezone)
    selected_date = _normalized_iso_date(request.args.get("date"), timezone)
    previous_date = _shift_iso_date(selected_date, -1)
    next_date = _shift_iso_date(selected_date, 1)
    season = selected_date.split("-")[0]

    schedule_payload, schedule_error = _fetch_statsapi_json(
        MLB_SCHEDULE_URL,
        params={
            "sportId": sport_id,
            "startDate": selected_date,
            "endDate": selected_date,
            "hydrate": "team,linescore",  # include team info and live linescore
        },
        timeout=10,
    )
    if schedule_error:
        status_code, body = schedule_error
        return jsonify(body), status_code

    sports_payload, sports_error = _fetch_statsapi_json(
        MLB_SPORTS_URL,
        params={"activeStatus": "active"},
        timeout=10,
        cache_ttl_seconds=86400,
    )

    sport_options: list[dict[str, int | str]] = []
    if not sports_error and sports_payload:
        for sport in sports_payload.get("sports", []):
            sport_raw_id = sport.get("id")
            sport_name = (sport.get("name") or "").strip()
            try:
                sport_option_id = int(sport_raw_id)
            except (TypeError, ValueError):
                continue
            if not sport_name:
                continue
            name_lower = sport_name.lower()
            if not any(frag in name_lower for frag in _ALLOWED_SPORT_NAME_FRAGMENTS):
                continue
            sport_options.append({"id": sport_option_id, "name": sport_name})

    if not sport_options:
        sport_options = [{"id": 1, "name": "Major League Baseball"}]

    known_sport_ids = {int(s["id"]) for s in sport_options}
    if sport_id not in known_sport_ids:
        sport_options.append({"id": sport_id, "name": f"Sport {sport_id}"})

    sport_options.sort(key=lambda s: (_sport_level(str(s["name"])), str(s["name"]).lower()))

    standings_payload = None
    standings_error = None
    if sport_id == 1:
        standings_payload, standings_error = _fetch_statsapi_json(
            MLB_STANDINGS_URL,
            params={
                "leagueId": "103,104",
                "standingsTypes": "regularSeason",
                "season": season,
            },
            timeout=10,
            cache_ttl_seconds=3600,
        )

    team_standings: dict[int, dict[str, str]] = {}
    if not standings_error and standings_payload:
        for division_record in standings_payload.get("records", []):
            division = division_record.get("division") or {}
            division_id = division.get("id")
            division_name = (
                _DIVISION_LABELS.get(division_id)
                or division.get("nameShort")
                or division.get("name")
                or ""
            )
            for team_record in division_record.get("teamRecords") or []:
                team = team_record.get("team") or {}
                team_id = team.get("id")
                if not team_id:
                    continue

                rank_raw = str(team_record.get("divisionRank") or "").strip()
                rank_display = ""
                if rank_raw.isdigit():
                    rank_display = _ordinal(int(rank_raw))
                elif rank_raw:
                    rank_display = rank_raw

                if rank_display and division_name:
                    division_position = f"{rank_display} {division_name}"
                elif rank_display:
                    division_position = rank_display
                else:
                    division_position = ""

                team_standings[team_id] = {
                    "record": _record_string(
                        team_record.get("wins"), team_record.get("losses")
                    ),
                    "division_position": division_position,
                }

    dates = schedule_payload.get("dates", [])
    games = []
    for day in dates:
        for game in day.get("games", []):
            status = game.get("status") or {}
            abstract_state = (status.get("abstractGameState") or "").lower()
            detailed_state = status.get("detailedState")
            is_not_started = abstract_state == "preview"
            is_live = abstract_state == "live"
            is_warmup = _is_warmup_status(detailed_state)
            is_postponed = _is_postponed_status(detailed_state)
            is_cancelled = _is_cancelled_status(detailed_state)
            suppress_diamond = is_postponed or is_cancelled
            start_time_local = _gate_time_start(game.get("gameDate"), timezone=timezone)
            starts_within_next_hour = _is_within_next_hour(
                game.get("gameDate"), timezone=timezone
            )

            teams = game.get("teams", {})
            home = teams.get("home", {})
            away = teams.get("away", {})
            linescore = game.get("linescore") or {}
            inning_state = linescore.get("inningState")
            current_inning = linescore.get("currentInning")
            home_team_id = (home.get("team") or {}).get("id")
            away_team_id = (away.get("team") or {}).get("id")

            # Build a short inning status label (e.g. "mid", "end", or the detailed state).
            if is_not_started:
                inning_display = start_time_local
            elif inning_state and current_inning:
                state_lower = inning_state.lower()
                if state_lower.startswith("mid"):
                    inning_display = "mid"
                elif state_lower.startswith("end"):
                    inning_display = "end"
                else:
                    inning_display = f"{inning_state} {current_inning}"
            else:
                inning_display = detailed_state or "Scheduled"

            home_score = home.get("score")
            away_score = away.get("score")
            offense = linescore.get("offense") or {}

            home_win_probability = None
            away_win_probability = None
            home_win_probability_trend = {"points": "", "direction": "flat"}
            away_win_probability_trend = {"points": "", "direction": "flat"}
            game_pk = game.get("gamePk")
            if is_live and game_pk:
                home_win_probability, away_win_probability = _current_win_probability(
                    game_pk,
                    home_team_id=home_team_id,
                    away_team_id=away_team_id,
                )
                home_win_probability_trend = _win_probability_trend(game_pk, "home")
                away_win_probability_trend = _win_probability_trend(game_pk, "away")

            home_team_standing = team_standings.get(home_team_id, {})
            away_team_standing = team_standings.get(away_team_id, {})

            # Determine triangle direction for top/bottom of inning indicator.
            inning_half_raw = (linescore.get("inningState") or "").lower()
            if inning_half_raw.startswith("top"):
                inning_arrow = "up"
            elif inning_half_raw.startswith("bot"):
                inning_arrow = "down"
            else:
                inning_arrow = "none"

            games.append(
                {
                    "game_pk": game_pk,
                    "status": detailed_state,
                    "home_team": (home.get("team") or {}).get("name"),
                    "home_abbr": (home.get("team") or {}).get("abbreviation")
                    or (home.get("team") or {}).get("name"),
                    "home_logo_url": _team_logo_url((home.get("team") or {}).get("id")),
                    "home_record": home_team_standing.get("record", ""),
                    "home_division_position": home_team_standing.get(
                        "division_position", ""
                    ),
                    "home_score": home_score if (not is_not_started and home_score is not None) else "",
                    "visitor_team": (away.get("team") or {}).get("name"),
                    "visitor_abbr": (away.get("team") or {}).get("abbreviation")
                    or (away.get("team") or {}).get("name"),
                    "visitor_logo_url": _team_logo_url(
                        (away.get("team") or {}).get("id")
                    ),
                    "visitor_record": away_team_standing.get("record", ""),
                    "visitor_division_position": away_team_standing.get(
                        "division_position", ""
                    ),
                    "visitor_score": away_score if (not is_not_started and away_score is not None) else "",
                    "inning_display": inning_display,
                    "inning_number": current_inning
                    or (start_time_local if is_not_started else ""),
                    "inning_arrow": inning_arrow,
                    "is_final": (
                        (detailed_state or "").lower().startswith("final")
                        or (detailed_state or "").lower().startswith("game over")
                        or (detailed_state or "").lower().startswith("completed")
                    ),
                    "is_not_started": is_not_started,
                    "is_warmup": is_warmup,
                    "is_postponed": is_postponed,
                    "is_cancelled": is_cancelled,
                    "suppress_diamond": suppress_diamond,
                    "start_time_local": start_time_local,
                    "starts_within_next_hour": (
                        starts_within_next_hour if is_not_started else False
                    ),
                    "home_wins": (
                        home_score is not None
                        and away_score is not None
                        and home_score > away_score
                    ),
                    "outs": _safe_int(linescore.get("outs"), 0),
                    "first_base": bool(offense.get("first")),
                    "second_base": bool(offense.get("second")),
                    "third_base": bool(offense.get("third")),
                    "game_date_raw": game.get("gameDate") or "",
                    "is_live": is_live,
                    "home_win_probability": _format_probability(home_win_probability),
                    "away_win_probability": _format_probability(away_win_probability),
                    "home_win_probability_trend": home_win_probability_trend,
                    "away_win_probability_trend": away_win_probability_trend,
                }
            )

    def _sort_key(g):
        date = g["game_date_raw"]
        if not g["is_not_started"] and not g["is_final"]:
            # In progress: sort group 0, reverse start time (negate)
            return (0, date and "-" + date or "")
        if g["is_not_started"]:
            # Not started: sort group 1, ascending start time
            return (1, date)
        # Final: sort group 2, ascending start time
        return (2, date)

    games.sort(key=_sort_key)

    # Bust standings cache if any games newly went final since last check.
    current_final_pks = {g["game_pk"] for g in games if g["is_final"] and g["game_pk"]}
    new_final_pks = current_final_pks - _FINAL_GAME_PKS
    if new_final_pks:
        _FINAL_GAME_PKS.update(new_final_pks)
        _bust_standings_cache()

    if request.args.get("format") == "json":
        return jsonify(
            {
                "date": selected_date,
                "timezone": timezone,
                "sportId": sport_id,
                "sportOptions": sport_options,
                "count": len(games),
                "games": games,
                "routes": [
                    "/games/<game_id>/score",
                    "/games/<game_id>",
                    "/score/<game_id>",
                ],
            }
        )

    return render_template(
        "index.html",
        selected_date_iso=selected_date,
        today_date=today_date,
        selected_date=_display_date(selected_date),
        previous_date=previous_date,
        next_date=next_date,
        timezone=timezone,
        sport_id=sport_id,
        sport_options=sport_options,
        games=games,
    )


@app.get("/")
def home():
    return render_template("home.html")


@app.get("/standings")
def standings():
    """
    Standings page — AL/NL East and West division standings.

    Query params:
      tz / timezone: IANA timezone string; used to determine current season year.
      format=json: return raw standings data as JSON instead of HTML.
    """
    timezone = _normalized_timezone(
        request.args.get("tz") or request.args.get("timezone")
    )
    season = str(datetime.now(ZoneInfo(timezone)).year)

    standings_payload, standings_error = _fetch_statsapi_json(
        MLB_STANDINGS_URL,
        params={
            "leagueId": "103,104",
            "standingsTypes": "regularSeason",
            "season": season,
        },
        timeout=10,
        cache_ttl_seconds=3600,
    )
    if standings_error:
        status_code, body = standings_error
        return jsonify(body), status_code

    # Index division records by division ID for fast lookup.
    records_by_division = {
        (record.get("division") or {}).get("id"): record
        for record in standings_payload.get("records", [])
    }

    divisions = []
    for division_id, division_name in STANDINGS_DIVISIONS:
        division_record = records_by_division.get(division_id) or {}
        teams = []
        for team_record in division_record.get("teamRecords") or []:
            team = team_record.get("team") or {}
            wins = team_record.get("wins")
            losses = team_record.get("losses")
            teams.append(
                {
                    "name": team.get("name") or "",
                    "logo_url": _team_logo_url(team.get("id")),
                    "record": _record_string(wins, losses),
                }
            )
        divisions.append({"name": division_name, "teams": teams})

    if request.args.get("format") == "json":
        return jsonify({"season": season, "timezone": timezone, "divisions": divisions})

    return render_template(
        "standings.html", season=season, timezone=timezone, divisions=divisions
    )


@app.get("/games/<int:game_id>/score")
@app.get("/games/<int:game_id>/score/")
@app.get("/games/<int:game_id>")
@app.get("/games/<int:game_id>/")
@app.get("/score/<int:game_id>")
@app.get("/score/<int:game_id>/")
def get_game_score(game_id: int):
    """
    Scoreboard page — live box score for a single game.

    Displays score, inning, count, baserunners, outs, batter/pitcher last names,
    last pitch description, and win probability for active games.

    Query params:
      format=json: return basic score data as JSON instead of HTML.
    """
    return_timezone = _normalized_timezone(
        request.args.get("tz") or request.args.get("timezone")
    )
    return_sport_id = _safe_int(request.args.get("sportId"), 1)
    if return_sport_id <= 0:
        return_sport_id = 1
    return_date = _normalized_iso_date(request.args.get("date"), return_timezone)

    try:
        response = requests.get(
            MLB_GAME_FEED_URL.format(game_pk=game_id),
            timeout=10,
        )
        log_statsapi_call(
            MLB_GAME_FEED_URL.format(game_pk=game_id),
            size_bytes=len(response.content),
        )
    except requests.RequestException as exc:
        return jsonify({"error": "Failed to reach MLB API", "details": str(exc)}), 502

    if response.status_code == 404:
        return jsonify({"error": f"Game {game_id} not found"}), 404

    if not response.ok:
        return jsonify(
            {
                "error": "MLB API request failed",
                "status_code": response.status_code,
                "body": response.text,
            }
        ), 502

    payload = response.json()

    # Top-level game metadata and team info.
    game_data = payload.get("gameData", {})
    game_info = game_data.get("gameInfo") or {}
    venue = game_data.get("venue") or {}
    venue_location = venue.get("location") or {}
    weather = game_data.get("weather") or {}
    status = (game_data.get("status") or {}).get("detailedState")
    is_warmup = _is_warmup_status(status)
    is_postponed = _is_postponed_status(status)
    is_cancelled = _is_cancelled_status(status)
    suppress_diamond = is_postponed or is_cancelled
    teams = game_data.get("teams", {})
    home_team = teams.get("home", {})
    away_team = teams.get("away", {})

    # Scores come from the linescore within liveData.
    linescore_teams = ((payload.get("liveData") or {}).get("linescore") or {}).get(
        "teams", {}
    )
    home_score = (linescore_teams.get("home") or {}).get("runs")
    away_score = (linescore_teams.get("away") or {}).get("runs")

    live_data = payload.get("liveData") or {}
    linescore = live_data.get("linescore") or {}
    offense = linescore.get("offense") or {}

    # Hide score until at least one pitch has been thrown.
    all_plays = (live_data.get("plays") or {}).get("allPlays") or []
    first_pitch_thrown = bool(all_plays)
    outs = _safe_int(linescore.get("outs"), 0)
    inning_number = linescore.get("currentInning") or ""
    inning_half = (linescore.get("inningHalf") or "").lower()
    inning_arrow = (
        "up" if inning_half == "top" else "down" if inning_half == "bottom" else "none"
    )

    # Current at-bat matchup.
    current_play = (live_data.get("plays") or {}).get("currentPlay") or {}
    matchup = current_play.get("matchup") or {}
    batter = matchup.get("batter") or {}
    pitcher = matchup.get("pitcher") or {}

    batter_last_name = _last_name(batter.get("lastName") or batter.get("fullName"))
    pitcher_last_name = _last_name(pitcher.get("lastName") or pitcher.get("fullName"))

    # Most recent pitch description and speed.
    play_events = current_play.get("playEvents") or []
    last_event = play_events[-1] if play_events else {}
    last_pitch = ((last_event.get("details") or {}).get("description")) or ""
    pitch_details = last_event.get("details") or {}
    pitch_type = (
        ((pitch_details.get("type") or {}).get("description"))
        or pitch_details.get("type")
        or ""
    )
    speed = (last_event.get("pitchData") or {}).get("startSpeed")
    last_pitch_speed = f"{speed:.1f} mph" if isinstance(speed, (int, float)) else ""
    if pitch_type and last_pitch_speed:
        last_pitch_meta = f"{pitch_type} {last_pitch_speed}"
    elif pitch_type:
        last_pitch_meta = str(pitch_type)
    elif last_pitch_speed:
        last_pitch_meta = last_pitch_speed
    else:
        last_pitch_meta = ""

    # Result description of the most recent completed play (e.g. "Strike out swinging").
    last_play_text = (
        (current_play.get("result") or {}).get("description")
    ) or last_pitch

    # Total pitches thrown by the current pitcher, sourced from the boxscore.
    pitch_count = ""
    batter_avg = ""
    batter_obp = ""
    batter_ops = ""
    batter_order = ""
    batter_id = batter.get("id")
    pitcher_id = pitcher.get("id")
    boxscore_teams = (live_data.get("boxscore") or {}).get("teams") or {}
    for side in ("home", "away"):
        players = (boxscore_teams.get(side) or {}).get("players") or {}
        if batter_id is not None:
            batter_key = f"ID{batter_id}"
            if batter_key in players:
                season = (players[batter_key].get("seasonStats") or {}).get("batting") or {}
                batter_avg = season.get("avg", "")
                batter_obp = season.get("obp", "")
                batter_ops = season.get("ops", "")
                raw_order = players[batter_key].get("battingOrder")
                if raw_order is not None:
                    try:
                        batter_order = str(int(raw_order) // 100)
                    except (TypeError, ValueError):
                        batter_order = ""
        if pitcher_id is not None:
            pitcher_key = f"ID{pitcher_id}"
            if pitcher_key in players:
                stats = (players[pitcher_key].get("stats") or {}).get("pitching") or {}
                if stats.get("numberOfPitches") is not None:
                    pitch_count = stats.get("numberOfPitches")

    home_abbr = home_team.get("abbreviation") or "HOME"
    away_abbr = away_team.get("abbreviation") or "AWAY"
    balls = _safe_int(linescore.get("balls"), 0)
    strikes = _safe_int(linescore.get("strikes"), 0)
    venue_name = venue.get("name") or ""
    venue_city = venue_location.get("city") or ""
    venue_state = venue_location.get("stateAbbrev") or venue_location.get("state") or ""
    venue_parts = [part for part in (venue_city, venue_state) if part]
    if venue_name and venue_parts:
        venue_name = f"{venue_name}, {', '.join(venue_parts)}"
    capacity_raw = game_info.get("capacity")
    capacity = ""
    if capacity_raw not in (None, ""):
        try:
            capacity = f"{int(str(capacity_raw).replace(',', '')):,}"
        except (TypeError, ValueError):
            capacity = str(capacity_raw)
    attendance_raw = game_info.get("attendance")
    attendance = ""
    if attendance_raw not in (None, ""):
        try:
            attendance = f"{int(str(attendance_raw).replace(',', '')):,}"
        except (TypeError, ValueError):
            attendance = str(attendance_raw)
    weather_condition = weather.get("condition") or ""
    weather_temp = weather.get("temp")
    if weather_temp in (None, ""):
        weather_temp = ""
    weather_wind = weather.get("wind") or ""
    review_data = game_data.get("review") or {}
    abs_data = game_data.get("absChallenges") or {}
    mound_data = game_data.get("moundVisits") or {}
    away_reviews_remaining = (review_data.get("away") or {}).get("remaining")
    away_abs_remaining = (abs_data.get("away") or {}).get("remaining")
    away_mound_remaining = (mound_data.get("away") or {}).get("remaining")
    home_reviews_remaining = (review_data.get("home") or {}).get("remaining")
    home_abs_remaining = (abs_data.get("home") or {}).get("remaining")
    home_mound_remaining = (mound_data.get("home") or {}).get("remaining")

    # Only fetch win probability for live (in-progress) games.
    is_active = (
        (game_data.get("status") or {}).get("abstractGameState") or ""
    ).lower() == "live"
    if is_active:
        home_win_probability, away_win_probability = _current_win_probability(
            payload.get("gamePk", game_id),
            home_team_id=home_team.get("id"),
            away_team_id=away_team.get("id"),
        )
    else:
        home_win_probability, away_win_probability = None, None

    home_win_probability_trend = _win_probability_trend(
        payload.get("gamePk", game_id), "home"
    )
    away_win_probability_trend = _win_probability_trend(
        payload.get("gamePk", game_id), "away"
    )
    win_probability_chart = _win_probability_area_chart(payload.get("gamePk", game_id))

    # Build top/bottom inning markers to label the chart x-axis timeline.
    inning_count = max(_safe_int(inning_number, 0), len(linescore.get("innings") or []))
    inning_count = max(1, min(inning_count, 15))
    axis_left = 36.0
    axis_width = 488.0
    inning_step = axis_width / inning_count
    chart_inning_markers = []
    for inning in range(1, inning_count + 1):
        chart_inning_markers.append(
            {
                "x": axis_left + ((inning - 1) * inning_step),
                "inning": inning,
            }
        )

    if request.args.get("format") == "json":
        return jsonify(
            {
                "game_pk": payload.get("gamePk", game_id),
                "status": status,
                "home_team": home_team.get("name"),
                "home_score": home_score,
                "attendance": attendance,
                "capacity": capacity,
                "venue": venue_name,
                "weather": weather_condition,
                "temp": weather_temp,
                "wind": weather_wind,
                "visitor_team": away_team.get("name"),
                "visitor_score": away_score,
            }
        )

    game_pk = payload.get("gamePk", game_id)

    # state_token encodes the full game state so the client can detect changes
    # and slow down the refresh interval when the game state hasn't changed.
    state_token = "|".join(
        [
            str(status),
            str(home_score),
            str(away_score),
            str(inning_number),
            str(inning_arrow),
            str(balls),
            str(strikes),
            str(outs),
            str(bool(offense.get("first"))),
            str(bool(offense.get("second"))),
            str(bool(offense.get("third"))),
            str(batter_last_name),
            str(pitcher_last_name),
            str(last_pitch),
            str(last_pitch_speed),
        ]
    )

    return render_template(
        "game.html",
        game_pk=game_pk,
        return_date=return_date,
        return_timezone=return_timezone,
        return_sport_id=return_sport_id,
        status=status,
        state_token=state_token,
        is_warmup=is_warmup,
        is_postponed=is_postponed,
        is_cancelled=is_cancelled,
        suppress_diamond=suppress_diamond,
        batter_last_name=batter_last_name,
        batter_order=batter_order,
        batter_avg=batter_avg,
        batter_obp=batter_obp,
        batter_ops=batter_ops,
        last_play_text=last_play_text,
        pitcher_last_name=pitcher_last_name,
        pitch_count=pitch_count,
        last_pitch=last_pitch,
        last_pitch_speed=last_pitch_speed,
        last_pitch_meta=last_pitch_meta,
        away_abbr=away_abbr,
        away_logo_url=_team_logo_url(away_team.get("id")),
        away_runs=away_score if (first_pitch_thrown and away_score is not None) else "",
        away_win_probability=_format_probability(away_win_probability),
        away_win_probability_trend=away_win_probability_trend,
        balls=balls,
        strikes=strikes,
        home_abbr=home_abbr,
        home_logo_url=_team_logo_url(home_team.get("id")),
        home_runs=home_score if (first_pitch_thrown and home_score is not None) else "",
        home_win_probability=_format_probability(home_win_probability),
        home_win_probability_trend=home_win_probability_trend,
        inning_number=inning_number,
        inning_arrow=inning_arrow,
        first_base=bool(offense.get("first")),
        second_base=bool(offense.get("second")),
        third_base=bool(offense.get("third")),
        first_base_indicator=_base_indicator(all_plays, offense, "first"),
        second_base_indicator=_base_indicator(all_plays, offense, "second"),
        third_base_indicator=_base_indicator(all_plays, offense, "third"),
        is_active=is_active,
        outs=outs,
        show_outs=inning_half in ("top", "bottom"),
        is_final=(
            (status or "").lower().startswith("final")
            or (status or "").lower().startswith("game over")
            or (status or "").lower().startswith("completed")
        ),
        home_wins=(
            home_score is not None
            and away_score is not None
            and home_score > away_score
        ),
        venue_name=venue_name,
        capacity=capacity,
        win_probability_chart=win_probability_chart,
        chart_inning_markers=chart_inning_markers,
        attendance=attendance,
        weather_condition=weather_condition,
        weather_temp=weather_temp,
        weather_wind=weather_wind,
        away_reviews_remaining=away_reviews_remaining,
        away_abs_remaining=away_abs_remaining,
        away_mound_remaining=away_mound_remaining,
        home_reviews_remaining=home_reviews_remaining,
        home_abs_remaining=home_abs_remaining,
        home_mound_remaining=home_mound_remaining,
    )


if __name__ == "__main__":
    app.run(debug=True, port=os.getenv("PORT", default=5000))

# if __name__ == "__main__":
# app.run(debug=True, port=os.getenv("PORT", default=5000))
