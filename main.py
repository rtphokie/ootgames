from datetime import datetime
import os
import time
from zoneinfo import ZoneInfo
from utils import (
    _team_logo_url,
    _last_name,
    _safe_int,
    _display_date,
    _gate_time_start,
    _normalized_timezone,
    _normalized_iso_date,
    _record_string,
    _shift_iso_date,
    _format_probability,
    _current_win_probability,
    _win_probability_trend,
)

from config import MLB_SCHEDULE_URL, MLB_STANDINGS_URL, MLB_GAME_FEED_URL

import requests
from flask import Flask, jsonify, render_template, request

# MLB Stats API docs: https://github.com/toddrob99/MLB-StatsAPI/wiki/Endpoints

app = Flask(__name__)

# Simple in-memory cache for relatively static StatsAPI resources.
_MLB_CACHE: dict[tuple[str, tuple[tuple[str, str], ...]], dict] = {}

# Track game_pks known to be final so we can bust standings cache when new games finish.
_FINAL_GAME_PKS: set[int] = set()


def _bust_standings_cache() -> None:
    """Remove all standings entries from the in-memory cache."""
    keys_to_delete = [k for k in _MLB_CACHE if k[0] == MLB_STANDINGS_URL]
    for k in keys_to_delete:
        del _MLB_CACHE[k]

# Division IDs to display on /standings, in render order.
# Verified against /api/v1/standings: AL West=200, AL East=201, NL West=203, NL East=204.
STANDINGS_DIVISIONS = [
    (204, "NL East"),
    (203, "NL West"),
    (201, "AL East"),
    (200, "AL West"),
]


def _cache_key(url: str, params: dict | None) -> tuple[str, tuple[tuple[str, str], ...]]:
    if not params:
        return (url, ())
    normalized = tuple(sorted((str(k), str(v)) for k, v in params.items()))
    return (url, normalized)


def _fetch_statsapi_json(
    url: str,
    *,
    params: dict | None = None,
    timeout: int = 10,
    cache_ttl_seconds: int = 0,
):
    key = _cache_key(url, params)
    cached = _MLB_CACHE.get(key)

    if cache_ttl_seconds > 0 and cached:
        age_seconds = time.time() - cached["fetched_at"]
        if age_seconds < cache_ttl_seconds:
            return cached["payload"], None

    try:
        response = requests.get(
            url,
            params=params,
            timeout=timeout,
        )
    except requests.RequestException as exc:
        # If refresh fails but we have a previous value, serve stale cache.
        if cached:
            return cached["payload"], None
        return None, (502, {"error": "Failed to reach MLB API", "details": str(exc)})

    if not response.ok:
        # If API is temporarily unhealthy, fall back to last known cached value.
        if cached:
            return cached["payload"], None
        return (
            None,
            (
                502,
                {
                    "error": "MLB API request failed",
                    "status_code": response.status_code,
                    "body": response.text,
                },
            ),
        )

    payload = response.json()
    if cache_ttl_seconds > 0:
        _MLB_CACHE[key] = {"payload": payload, "fetched_at": time.time()}

    return payload, None


# --- Routes ---


@app.get("/")
def index():
    """
    Schedule page — list all MLB games for the selected date.

    Query params:
      date (YYYY-MM-DD): date to display; defaults to today in the user's timezone.
      tz / timezone: IANA timezone string; defaults to America/New_York.
      format=json: return raw game data as JSON instead of HTML.
    """
    timezone = _normalized_timezone(
        request.args.get("tz") or request.args.get("timezone")
    )
    selected_date = _normalized_iso_date(request.args.get("date"), timezone)
    previous_date = _shift_iso_date(selected_date, -1)
    next_date = _shift_iso_date(selected_date, 1)

    schedule_payload, schedule_error = _fetch_statsapi_json(
        MLB_SCHEDULE_URL,
        params={
            "sportId": 1,
            "startDate": selected_date,
            "endDate": selected_date,
            "hydrate": "team,linescore",  # include team info and live linescore
        },
        timeout=10,
    )
    if schedule_error:
        status_code, body = schedule_error
        return jsonify(body), status_code

    dates = schedule_payload.get("dates", [])
    games = []
    for day in dates:
        for game in day.get("games", []):
            status = game.get("status") or {}
            abstract_state = (status.get("abstractGameState") or "").lower()
            detailed_state = status.get("detailedState")
            is_not_started = abstract_state == "preview"
            is_live = abstract_state == "live"
            start_time_et = _gate_time_start(game.get("gameDate"), timezone=timezone)

            teams = game.get("teams", {})
            home = teams.get("home", {})
            away = teams.get("away", {})
            linescore = game.get("linescore") or {}
            inning_state = linescore.get("inningState")
            current_inning = linescore.get("currentInning")

            # Build a short inning status label (e.g. "mid", "end", or the detailed state).
            if is_not_started:
                inning_display = start_time_et
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
                    game_pk
                )
                home_win_probability_trend = _win_probability_trend(game_pk, "home")
                away_win_probability_trend = _win_probability_trend(game_pk, "away")

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
                    "home_score": home_score if home_score is not None else "",
                    "visitor_team": (away.get("team") or {}).get("name"),
                    "visitor_abbr": (away.get("team") or {}).get("abbreviation")
                    or (away.get("team") or {}).get("name"),
                    "visitor_logo_url": _team_logo_url(
                        (away.get("team") or {}).get("id")
                    ),
                    "visitor_score": away_score if away_score is not None else "",
                    "inning_display": inning_display,
                    "inning_number": current_inning
                    or (start_time_et if is_not_started else ""),
                    "inning_arrow": inning_arrow,
                    "is_final": (
                        (detailed_state or "").lower().startswith("final")
                        or (detailed_state or "").lower().startswith("game over")
                        or (detailed_state or "").lower().startswith("completed")
                    ),
                    "is_not_started": is_not_started,
                    "start_time_et": start_time_et,
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
        "games_list.html",
        selected_date=_display_date(selected_date),
        previous_date=previous_date,
        next_date=next_date,
        timezone=timezone,
        games=games,
    )


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
    try:
        response = requests.get(
            MLB_GAME_FEED_URL.format(game_pk=game_id),
            timeout=10,
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
    status = (game_data.get("status") or {}).get("detailedState")
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
    pitcher_id = pitcher.get("id")
    if pitcher_id is not None:
        boxscore_teams = (live_data.get("boxscore") or {}).get("teams") or {}
        for side in ("home", "away"):
            players = (boxscore_teams.get(side) or {}).get("players") or {}
            key = f"ID{pitcher_id}"
            if key in players:
                stats = (players[key].get("stats") or {}).get("pitching") or {}
                if stats.get("numberOfPitches") is not None:
                    pitch_count = stats.get("numberOfPitches")
                break

    home_abbr = home_team.get("abbreviation") or "HOME"
    away_abbr = away_team.get("abbreviation") or "AWAY"
    balls = _safe_int(linescore.get("balls"), 0)
    strikes = _safe_int(linescore.get("strikes"), 0)

    # Only fetch win probability for live (in-progress) games.
    is_active = (
        (game_data.get("status") or {}).get("abstractGameState") or ""
    ).lower() == "live"
    if is_active:
        home_win_probability, away_win_probability = _current_win_probability(
            payload.get("gamePk", game_id)
        )
    else:
        home_win_probability, away_win_probability = None, None

    home_win_probability_trend = _win_probability_trend(
        payload.get("gamePk", game_id), "home"
    )
    away_win_probability_trend = _win_probability_trend(
        payload.get("gamePk", game_id), "away"
    )

    if request.args.get("format") == "json":
        return jsonify(
            {
                "game_pk": payload.get("gamePk", game_id),
                "status": status,
                "home_team": home_team.get("name"),
                "home_score": home_score,
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
        "scoreboard.html",
        game_pk=game_pk,
        status=status,
        state_token=state_token,
        batter_last_name=batter_last_name,
        last_play_text=last_play_text,
        pitcher_last_name=pitcher_last_name,
        pitch_count=pitch_count,
        last_pitch=last_pitch,
        last_pitch_speed=last_pitch_speed,
        last_pitch_meta=last_pitch_meta,
        away_abbr=away_abbr,
        away_logo_url=_team_logo_url(away_team.get("id")),
        away_runs=away_score if away_score is not None else "",
        away_win_probability=_format_probability(away_win_probability),
        away_win_probability_trend=away_win_probability_trend,
        balls=balls,
        strikes=strikes,
        home_abbr=home_abbr,
        home_logo_url=_team_logo_url(home_team.get("id")),
        home_runs=home_score if home_score is not None else "",
        home_win_probability=_format_probability(home_win_probability),
        home_win_probability_trend=home_win_probability_trend,
        inning_number=inning_number,
        inning_arrow=inning_arrow,
        first_base=bool(offense.get("first")),
        second_base=bool(offense.get("second")),
        third_base=bool(offense.get("third")),
        is_active=is_active,
        outs=outs,
        show_outs=inning_half in ("top", "bottom"),
    )


if __name__ == "__main__":
    app.run(debug=True, port=os.getenv("PORT", default=5000))

# if __name__ == "__main__":
# app.run(debug=True, port=os.getenv("PORT", default=5000))
