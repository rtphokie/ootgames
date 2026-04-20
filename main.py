from datetime import datetime, timedelta
import os
from zoneinfo import ZoneInfo

import requests
from flask import Flask, jsonify, render_template, request

app = Flask(__name__)
MLB_SCHEDULE_URL = "https://statsapi.mlb.com/api/v1/schedule"
MLB_GAME_FEED_URL = "https://statsapi.mlb.com/api/v1.1/game/{game_pk}/feed/live"
MLB_WIN_PROBABILITY_URL = "https://statsapi.mlb.com/api/v1/game/{game_pk}/winProbability"
MLB_STANDINGS_URL = "https://statsapi.mlb.com/api/v1/standings"

STANDINGS_DIVISIONS = [
    (204, "NL East"),
    (203, "NL West"),
    (201, "AL East"),
    (200, "AL West"),
]


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


def _gate_time_start(game_date_raw: str | None, timezone: str = "America/New_York") -> str:
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


def _normalized_timezone(timezone_raw: str | None, default: str = "America/New_York") -> str:
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

    if not isinstance(home_probability, (int, float)) or not isinstance(away_probability, (int, float)):
        return None, None

    return float(home_probability), float(away_probability)


def _record_string(wins, losses) -> str:
    if wins is None or losses is None:
        return ""
    return f"{wins}-{losses}"


@app.get("/")
def index():
    timezone = _normalized_timezone(request.args.get("tz") or request.args.get("timezone"))
    selected_date = _normalized_iso_date(request.args.get("date"), timezone)
    previous_date = _shift_iso_date(selected_date, -1)
    next_date = _shift_iso_date(selected_date, 1)
    # &startDate=2019-03-28&endDate=2019-09-29

    try:
        response = requests.get(
            MLB_SCHEDULE_URL,
            params={"sportId": 1, 
                    "startDate": selected_date, 
                    "endDate": selected_date, 
                    "hydrate": "team,linescore"},
            timeout=10,
        )
        print(f"selected_date = {selected_date}, MLB API response status: {response.status_code}")
    except requests.RequestException as exc:
        return jsonify({"error": "Failed to reach MLB API", "details": str(exc)}), 502

    if not response.ok:
        return jsonify(
            {
                "error": "MLB API request failed",
                "status_code": response.status_code,
                "body": response.text,
            }
        ), 502

    dates = response.json().get("dates", [])
    games = []
    for day in dates:
        for game in day.get("games", []):
            status = game.get("status") or {}
            abstract_state = (status.get("abstractGameState") or "").lower()
            detailed_state = status.get("detailedState")
            is_not_started = abstract_state == "preview"
            start_time_et = _gate_time_start(game.get("gameDate"), timezone=timezone)

            teams = game.get("teams", {})
            home = teams.get("home", {})
            away = teams.get("away", {})
            linescore = game.get("linescore") or {}
            inning_state = linescore.get("inningState")
            current_inning = linescore.get("currentInning")
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
            inning_half_raw = (linescore.get("inningState") or "").lower()
            if inning_half_raw.startswith("top"):
                inning_arrow = "up"
            elif inning_half_raw.startswith("bot"):
                inning_arrow = "down"
            else:
                inning_arrow = "none"
            games.append(
                {
                    "game_pk": game.get("gamePk"),
                    "status": detailed_state,
                    "home_team": (home.get("team") or {}).get("name"),
                    "home_abbr": (home.get("team") or {}).get("abbreviation") or (home.get("team") or {}).get("name"),
                    "home_logo_url": _team_logo_url((home.get("team") or {}).get("id")),
                    "home_score": home_score if home_score is not None else "",
                    "visitor_team": (away.get("team") or {}).get("name"),
                    "visitor_abbr": (away.get("team") or {}).get("abbreviation") or (away.get("team") or {}).get("name"),
                    "visitor_logo_url": _team_logo_url((away.get("team") or {}).get("id")),
                    "visitor_score": away_score if away_score is not None else "",
                    "inning_display": inning_display,
                    "inning_number": current_inning or (start_time_et if is_not_started else ""),
                    "inning_arrow": inning_arrow,
                    "is_final": (detailed_state or "").lower().startswith("final") or (detailed_state or "").lower().startswith("game over") or (detailed_state or "").lower().startswith("completed"),
                    "is_not_started": is_not_started,
                    "start_time_et": start_time_et,
                    "home_wins": (home_score is not None and away_score is not None and home_score > away_score),
                    "outs": _safe_int(linescore.get("outs"), 0),
                    "first_base": bool(offense.get("first")),
                    "second_base": bool(offense.get("second")),
                    "third_base": bool(offense.get("third")),
                }
            )

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
    timezone = _normalized_timezone(request.args.get("tz") or request.args.get("timezone"))
    season = str(datetime.now(ZoneInfo(timezone)).year)

    try:
        response = requests.get(
            MLB_STANDINGS_URL,
            params={"leagueId": "103,104", "standingsTypes": "regularSeason", "season": season},
            timeout=10,
        )
    except requests.RequestException as exc:
        return jsonify({"error": "Failed to reach MLB API", "details": str(exc)}), 502

    if not response.ok:
        return jsonify(
            {
                "error": "MLB API request failed",
                "status_code": response.status_code,
                "body": response.text,
            }
        ), 502

    records_by_division = {
        (record.get("division") or {}).get("id"): record for record in response.json().get("records", [])
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

    return render_template("standings.html", season=season, timezone=timezone, divisions=divisions)


@app.get("/games/<int:game_id>/score")
@app.get("/games/<int:game_id>/score/")
@app.get("/games/<int:game_id>")
@app.get("/games/<int:game_id>/")
@app.get("/score/<int:game_id>")
@app.get("/score/<int:game_id>/")
def get_game_score(game_id: int):
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

    game_data = payload.get("gameData", {})
    status = (game_data.get("status") or {}).get("detailedState")
    teams = game_data.get("teams", {})
    home_team = teams.get("home", {})
    away_team = teams.get("away", {})
    linescore_teams = ((payload.get("liveData") or {}).get("linescore") or {}).get("teams", {})
    home_score = (linescore_teams.get("home") or {}).get("runs")
    away_score = (linescore_teams.get("away") or {}).get("runs")

    live_data = payload.get("liveData") or {}
    linescore = live_data.get("linescore") or {}
    offense = linescore.get("offense") or {}
    outs = _safe_int(linescore.get("outs"), 0)
    inning_number = linescore.get("currentInning") or ""
    inning_half = (linescore.get("inningHalf") or "").lower()
    inning_arrow = "up" if inning_half == "top" else "down" if inning_half == "bottom" else "none"

    current_play = (live_data.get("plays") or {}).get("currentPlay") or {}
    matchup = current_play.get("matchup") or {}
    batter = matchup.get("batter") or {}
    pitcher = matchup.get("pitcher") or {}

    batter_last_name = _last_name(batter.get("lastName") or batter.get("fullName"))
    pitcher_last_name = _last_name(pitcher.get("lastName") or pitcher.get("fullName"))

    play_events = current_play.get("playEvents") or []
    last_event = play_events[-1] if play_events else {}
    last_pitch = ((last_event.get("details") or {}).get("description")) or ""
    pitch_details = last_event.get("details") or {}
    pitch_type = ((pitch_details.get("type") or {}).get("description")) or pitch_details.get("type") or ""
    speed = ((last_event.get("pitchData") or {}).get("startSpeed"))
    last_pitch_speed = f"{speed:.1f} mph" if isinstance(speed, (int, float)) else ""
    if pitch_type and last_pitch_speed:
        last_pitch_meta = f"{pitch_type} {last_pitch_speed}"
    elif pitch_type:
        last_pitch_meta = str(pitch_type)
    elif last_pitch_speed:
        last_pitch_meta = last_pitch_speed
    else:
        last_pitch_meta = ""
    last_play_text = ((current_play.get("result") or {}).get("description")) or last_pitch

    pitch_count = ""
    pitcher_id = pitcher.get("id")
    if pitcher_id is not None:
        boxscore_teams = ((live_data.get("boxscore") or {}).get("teams") or {})
        for side in ("home", "away"):
            players = (boxscore_teams.get(side) or {}).get("players") or {}
            key = f"ID{pitcher_id}"
            if key in players:
                stats = ((players[key].get("stats") or {}).get("pitching") or {})
                if stats.get("numberOfPitches") is not None:
                    pitch_count = stats.get("numberOfPitches")
                break

    home_abbr = home_team.get("abbreviation") or "HOME"
    away_abbr = away_team.get("abbreviation") or "AWAY"
    balls = _safe_int(linescore.get("balls"), 0)
    strikes = _safe_int(linescore.get("strikes"), 0)
    is_active = ((game_data.get("status") or {}).get("abstractGameState") or "").lower() == "live"
    if is_active:
        home_win_probability, away_win_probability = _current_win_probability(payload.get("gamePk", game_id))
    else:
        home_win_probability, away_win_probability = None, None

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
        balls=balls,
        strikes=strikes,
        home_abbr=home_abbr,
        home_logo_url=_team_logo_url(home_team.get("id")),
        home_runs=home_score if home_score is not None else "",
        home_win_probability=_format_probability(home_win_probability),
        inning_number=inning_number,
        inning_arrow=inning_arrow,
        first_base=bool(offense.get("first")),
        second_base=bool(offense.get("second")),
        third_base=bool(offense.get("third")),
        is_active=is_active,
        outs=outs,
    )


if __name__ == "__main__":
    app.run(debug=True, port=os.getenv("PORT", default=5000))
