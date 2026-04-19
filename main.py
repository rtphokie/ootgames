from datetime import date

import requests
from flask import Flask, jsonify, render_template_string, request


app = Flask(__name__)
MLB_SCHEDULE_URL = "https://statsapi.mlb.com/api/v1/schedule"
MLB_GAME_FEED_URL = "https://statsapi.mlb.com/api/v1.1/game/{game_pk}/feed/live"

def _team_logo_url(team_id: int | None) -> str:
    if not team_id:
        return ""
    return f"https://www.mlbstatic.com/team-logos/team-cap-on-dark/{team_id}.svg"


GAMES_LIST_TEMPLATE = """
<!doctype html>
<html lang="en">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>MLB Games</title>
    <script>
        function updateRefreshLine(refreshMs) {
            const bar = document.getElementById("schedule-refresh-bar");
            if (!bar) return;
            const start = Date.now();
            const timer = setInterval(function () {
                const elapsed = Date.now() - start;
                const remaining = Math.max(0, refreshMs - elapsed);
                bar.style.width = ((remaining / refreshMs) * 100).toFixed(2) + "%";
                if (remaining <= 0) clearInterval(timer);
            }, 100);
        }
        window.addEventListener("DOMContentLoaded", function () {
            const ms = 15000;
            updateRefreshLine(ms);
            setTimeout(function () { window.location.reload(); }, ms);

            document.querySelectorAll(".game[data-pk]").forEach(function (el) {
                const pk = el.dataset.pk;
                const vs = el.dataset.vs;
                const hs = el.dataset.hs;
                const key = "mlb_score_" + pk;
                const prev = localStorage.getItem(key);
                if (prev !== null && prev !== vs + "|" + hs) {
                    const [pv, ph] = prev.split("|").map(Number);
                    const cv = Number(vs), ch = Number(hs);
                    if (cv > pv || ch > ph) {
                        el.classList.add("run-scored");
                    }
                }
                localStorage.setItem(key, vs + "|" + hs);
            });
        });
    </script>
    <style>
        :root {
            --bg: #000000;
            --panel: #101010;
            --line: #3b3b3b;
            --text: #f5f5f5;
            --muted: #b8b8b8;
            --accent: #ffd400;
        }
        body {
            margin: 0;
            background: var(--bg);
            color: var(--text);
            font-family: "Menlo", "Consolas", monospace;
            min-height: 100vh;
            padding: 16px;
            box-sizing: border-box;
        }
        .wrap {
            width: min(1200px, 98vw);
            margin: 0 auto;
        }
        h1 {
            margin: 0 0 6px 0;
            font-size: 22px;
            letter-spacing: 0.04em;
        }
        .sub {
            color: var(--muted);
            margin-bottom: 12px;
            font-size: 13px;
            text-align: right;
        }
        .games-grid {
            display: grid;
            grid-template-columns: repeat(2, 1fr);
            gap: 8px;
        }
        .game {
            display: grid;
            grid-template-columns: 1fr 44px 44px;
            align-items: center;
            border: none;
            background: var(--panel);
            padding: 8px 10px;
            text-decoration: none;
            color: var(--text);
        }
        .game:hover {
            background: #1a1800;
        }
        .game-teams {
            display: flex;
            flex-direction: column;
            gap: 3px;
        }
        .game-team-row {
            display: grid;
            grid-template-columns: 16px 3ch auto 1fr;
            align-items: center;
            column-gap: 4px;
            font-size: 13px;
            font-weight: 700;
        }
        .game-team-name {
            text-align: right;
        }
        .game-team-score {
            font-size: 15px;
            font-weight: 800;
            margin-left: 15px;
        }
        .game-team-row.loser {
            font-weight: 400;
            color: var(--muted);
        }
        .game-team-row.loser .game-team-score {
            font-weight: 400;
        }
        .logo {
            width: 16px;
            height: 16px;
            object-fit: contain;
            opacity: 0.95;
            flex-shrink: 0;
        }
        .game-inning {
            display: flex;
            flex-direction: column;
            align-items: center;
            justify-content: center;
            gap: 1px;
        }
        .game-triangle {
            width: 0;
            height: 0;
            border-left: 5px solid transparent;
            border-right: 5px solid transparent;
        }
        .game-triangle.up   { border-bottom: 8px solid var(--accent); }
        .game-triangle.down { border-top: 8px solid var(--accent); }
        .game-inning-num {
            font-size: 18px;
            font-weight: 800;
            line-height: 1;
        }
        .game-inning-label {
            font-size: 10px;
            color: var(--muted);
        }
        .game-right {
            display: flex;
            flex-direction: column;
            align-items: center;
            gap: 5px;
        }
        .game-bases {
            display: grid;
            grid-template-columns: 12px 12px 12px;
            grid-template-rows: 12px 12px;
            column-gap: 3px;
            row-gap: 3px;
            align-items: center;
            justify-items: center;
        }
        .game-base {
            width: 8px;
            height: 8px;
            background: #3a3a3a;
            transform: rotate(45deg);
            border: 1px solid #5a5a5a;
        }
        .game-base.second { grid-column: 2; grid-row: 1; }
        .game-base.third  { grid-column: 1; grid-row: 2; }
        .game-base.first  { grid-column: 3; grid-row: 2; }
        .game-base.on { background: var(--accent); border-color: #c3a500; }
        .game-outs { display: flex; gap: 4px; }
        .game-out {
            width: 6px;
            height: 6px;
            border-radius: 999px;
            background: #3a3a3a;
            border: 1px solid #5a5a5a;
        }
        .game-out.on { background: var(--accent); border-color: #c3a500; }
        .countdown {
            position: fixed;
            top: 10px;
            right: 12px;
            width: 96px;
            height: 4px;
            background: #0b0b0b;
            border-radius: 999px;
            overflow: hidden;
        }
        .countdown-bar {
            width: 100%;
            height: 100%;
            background: #171717;
            border-radius: 999px;
            transition: width 0.1s linear;
        }
        @keyframes run-flash {
            0%   { background: #3a2e00; }
            40%  { background: #1f1800; }
            70%  { background: #3a2e00; }
            100% { background: var(--panel); }
        }
        .run-scored {
            animation: run-flash 1.4s ease-out forwards;
        }
        .empty {
            border: 1px dashed var(--line);
            padding: 20px;
            color: var(--muted);
            text-align: center;
            grid-column: 1 / -1;
        }
        @media (min-width: 900px) {
            .games-grid {
                grid-template-columns: repeat(3, 1fr);
            }
        }
        @media (max-width: 500px) {
            .games-grid {
                grid-template-columns: 1fr;
            }
        }
    </style>
</head>
<body>
    <div class="countdown" aria-hidden="true">
        <div id="schedule-refresh-bar" class="countdown-bar"></div>
    </div>
    <div class="wrap">
        <div class="sub">{{ selected_date }} &mdash; {{ games|length }} games</div>
        <div class="games-grid">
        {% if games %}
            {% for game in games %}
                <a class="game" href="/games/{{ game.game_pk }}/score" data-pk="{{ game.game_pk }}" data-vs="{{ game.visitor_score }}" data-hs="{{ game.home_score }}">
                    <div class="game-teams">
                        <div class="game-team-row{% if game.is_final and game.home_wins %} loser{% endif %}">
                            <img class="logo" src="{{ game.visitor_logo_url }}" alt="{{ game.visitor_abbr }}" onerror="this.style.display='none'">
                            <span class="game-team-name">{{ game.visitor_abbr }}</span>
                            <span class="game-team-score">{{ game.visitor_score }}</span>
                        </div>
                        <div class="game-team-row{% if game.is_final and not game.home_wins %} loser{% endif %}">
                            <img class="logo" src="{{ game.home_logo_url }}" alt="{{ game.home_abbr }}" onerror="this.style.display='none'">
                            <span class="game-team-name">{{ game.home_abbr }}</span>
                            <span class="game-team-score">{{ game.home_score }}</span>
                        </div>
                    </div>
                    <div class="game-inning">
                        {% if game.is_final %}
                        {% else %}
                            {% if game.inning_arrow == 'up' %}
                                <div class="game-triangle up"></div>
                            {% else %}
                                <div style="height:8px"></div>
                            {% endif %}
                            <div class="game-inning-num">{{ game.inning_number }}</div>
                            {% if game.inning_arrow == 'down' %}
                                <div class="game-triangle down"></div>
                            {% elif game.inning_arrow == 'none' %}
                                <div class="game-inning-label">{{ game.inning_display }}</div>
                            {% else %}
                                <div style="height:10px"></div>
                            {% endif %}
                        {% endif %}
                    </div>
                    <div class="game-right">
                        {% if not game.is_final %}
                        <div class="game-bases" aria-label="Bases">
                            <div class="game-base second {% if game.second_base %}on{% endif %}"></div>
                            <div class="game-base third {% if game.third_base %}on{% endif %}"></div>
                            <div class="game-base first {% if game.first_base %}on{% endif %}"></div>
                        </div>
                        <div class="game-outs" aria-label="Outs">
                            <div class="game-out {% if game.outs >= 1 %}on{% endif %}"></div>
                            <div class="game-out {% if game.outs >= 2 %}on{% endif %}"></div>
                            <div class="game-out {% if game.outs >= 3 %}on{% endif %}"></div>
                        </div>
                        {% endif %}
                    </div>
                </a>
            {% endfor %}
        {% else %}
            <div class="empty">No games found for this date.</div>
        {% endif %}
        </div>
    </div>
</body>
</html>
"""

SCOREBOARD_TEMPLATE = """
<!doctype html>
<html lang="en">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>MLB Scoreboard</title>
    <script>
        function updateRefreshLine(refreshMs) {
            const bar = document.getElementById("refresh-line-bar");
            if (!bar) {
                return;
            }
            const start = Date.now();
            const timer = setInterval(function () {
                const elapsed = Date.now() - start;
                const remainingMs = Math.max(0, refreshMs - elapsed);
                const percent = (remainingMs / refreshMs) * 100;
                bar.style.width = percent.toFixed(2) + "%";
                if (remainingMs <= 0) {
                    clearInterval(timer);
                }
            }, 100);
        }

        window.addEventListener("DOMContentLoaded", function () {
            let refreshMs = 5000;
            const gamePk = {{ game_pk | tojson }};
            const stateToken = {{ state_token | tojson }};
            const storageKey = "mlb_state_" + String(gamePk);

            try {
                const previousState = localStorage.getItem(storageKey);
                if (previousState === stateToken) {
                    refreshMs = 10000;
                }
                localStorage.setItem(storageKey, stateToken);
            } catch (err) {
                // If storage is unavailable, keep the default 5 second refresh.
            }

            updateRefreshLine(refreshMs);
            setTimeout(function () {
                window.location.reload();
            }, refreshMs);
        });
    </script>
    <style>
        :root {
            --bg: #000000;
            --panel: #101010;
            --line: #3b3b3b;
            --text: #f5f5f5;
            --muted: #b8b8b8;
            --off: #6a6a6a;
            --on: #ffd400;
        }
        body {
            margin: 0;
            background: var(--bg);
            color: var(--text);
            font-family: "Menlo", "Consolas", monospace;
            min-height: 100vh;
            display: grid;
            place-items: center;
            padding: 16px;
            box-sizing: border-box;
        }
        .board {
            width: min(980px, 96vw);
            border-collapse: collapse;
            background: var(--panel);
            border: none;
            table-layout: fixed;
        }
        .board-wrap {
            position: relative;
            display: inline-block;
        }
        .board td {
            border: none;
            padding: 10px;
            vertical-align: middle;
            font-size: 18px;
            letter-spacing: 0.04em;
        }
        .muted {
            color: var(--muted);
            font-size: 14px;
            margin-right: 8px;
        }
        .value {
            font-weight: 700;
        }
        .team {
            font-size: 24px;
            font-weight: 700;
            display: inline-flex;
            align-items: center;
            gap: 8px;
        }
        .team-logo {
            width: 24px;
            height: 24px;
            object-fit: contain;
            opacity: 0.95;
        }
        .runs {
            font-size: 52px;
            text-align: center;
            font-weight: 800;
            width: 80px;
        }
        .center-cell {
            width: 340px;
        }
        .center-wrap {
            display: grid;
            gap: 10px;
            justify-items: center;
        }
        .inning-row {
            display: flex;
            align-items: center;
            gap: 16px;
        }
        .diamond-stack {
            display: grid;
            gap: 10px;
            justify-items: center;
            align-items: center;
        }
        .inning {
            display: flex;
            flex-direction: column;
            align-items: center;
            min-width: 70px;
            line-height: 1;
        }
        .triangle {
            width: 0;
            height: 0;
            margin-bottom: 4px;
            border-left: 8px solid transparent;
            border-right: 8px solid transparent;
        }
        .triangle.up {
            border-bottom: 12px solid var(--on);
        }
        .triangle.down {
            border-top: 12px solid var(--on);
        }
        .inning-num {
            font-size: 32px;
            font-weight: 800;
        }
        .bases {
            display: grid;
            grid-template-columns: 22px 22px 22px;
            grid-template-rows: 22px 22px;
            column-gap: 6px;
            row-gap: 6px;
            align-items: center;
            justify-items: center;
        }
        .base {
            width: 18px;
            height: 18px;
            background: var(--off);
            transform: rotate(45deg);
            border: 1px solid #8a8a8a;
        }
        .base.second {
            grid-column: 2;
            grid-row: 1;
        }
        .base.third {
            grid-column: 1;
            grid-row: 2;
        }
        .base.first {
            grid-column: 3;
            grid-row: 2;
        }
        .base.on {
            background: var(--on);
            border-color: #c3a500;
        }
        .outs {
            display: flex;
            gap: 12px;
            justify-content: center;
        }
        .out {
            width: 16px;
            height: 16px;
            border-radius: 999px;
            background: var(--off);
            border: 1px solid #8a8a8a;
        }
        .out.on {
            background: var(--on);
            border-color: #c3a500;
        }
        .right {
            text-align: right;
        }
        .countdown {
            position: fixed;
            top: 10px;
            right: 12px;
            width: 96px;
            height: 4px;
            background: #0b0b0b;
            border-radius: 999px;
            overflow: hidden;
        }
        .countdown-bar {
            width: 100%;
            height: 100%;
            background: #171717;
            border-radius: 999px;
            transition: width 0.1s linear;
        }
        .return-link {
            position: absolute;
            right: 10px;
            bottom: 8px;
            color: #6a6a6a;
            text-decoration: none;
            font-size: 18px;
            line-height: 1;
            opacity: 0.75;
        }
        .return-link:hover {
            color: #9a9a9a;
            opacity: 1;
        }
        @media (max-width: 700px) {
            .board td {
                padding: 8px;
                font-size: 14px;
            }
            .team {
                font-size: 18px;
            }
            .runs {
                font-size: 36px;
                width: 56px;
            }
            .center-cell {
                width: 230px;
            }
            .inning-num {
                font-size: 22px;
            }
        }
    </style>
</head>
<body>
    <div class="countdown" aria-hidden="true">
        <div id="refresh-line-bar" class="countdown-bar"></div>
    </div>
    <div class="board-wrap">
        <table class="board" aria-label="MLB scoreboard">
            <tr>
                <td colspan="2"><span class="value">{{ batter_last_name }}</span></td>
                <td colspan="2" class="right"><span class="value">{{ last_play_text }}</span></td>
            </tr>
            <tr>
                <td><span class="value">{{ pitcher_last_name }}</span></td>
                <td><span class="muted">P:</span><span class="value">{{ pitch_count }}</span></td>
                <td colspan="2" class="right"><span class="value">{{ last_pitch_meta }}</span></td>
            </tr>
            <tr>
                <td class="team"><img class="team-logo" src="{{ away_logo_url }}" alt="{{ away_abbr }} logo" onerror="this.style.display='none'">{{ away_abbr }} {{ away_runs }}</td>
                <td class="runs"></td>
                <td class="center-cell" rowspan="2">
                    <div class="center-wrap">
                        <div class="inning-row">
                            <div class="inning">
                                {% if inning_arrow == 'up' %}
                                    <div class="triangle up"></div>
                                {% else %}
                                    <div style="height: 12px;"></div>
                                {% endif %}
                                <div class="inning-num">{{ inning_number }}</div>
                                {% if inning_arrow == 'down' %}
                                    <div class="triangle down" style="margin-top: 4px; margin-bottom: 0;"></div>
                                {% endif %}
                            </div>
                            <div class="diamond-stack">
                                <div class="bases" aria-label="Bases">
                                    <div class="base second {% if second_base %}on{% endif %}"></div>
                                    <div class="base third {% if third_base %}on{% endif %}"></div>
                                    <div class="base first {% if first_base %}on{% endif %}"></div>
                                </div>
                                <div class="outs" aria-label="Outs">
                                    <div class="out {% if outs >= 1 %}on{% endif %}"></div>
                                    <div class="out {% if outs >= 2 %}on{% endif %}"></div>
                                    <div class="out {% if outs >= 3 %}on{% endif %}"></div>
                                </div>
                            </div>
                        </div>
                    </div>
                </td>
                <td class="right"><span class="value">{{ balls }}-{{ strikes }}</span></td>
            </tr>
            <tr>
                <td class="team"><img class="team-logo" src="{{ home_logo_url }}" alt="{{ home_abbr }} logo" onerror="this.style.display='none'">{{ home_abbr }} {{ home_runs }}</td>
                <td class="runs"></td>
                <td class="right"></td>
            </tr>
        </table>
        <a class="return-link" href="/" aria-label="Back to schedule">&#8617;</a>
    </div>
</body>
</html>
"""


def _last_name(name: str | None) -> str:
    if not name:
        return "-"
    parts = name.strip().split()
    return parts[-1] if parts else "-"


def _safe_int(value, default=0):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


@app.get("/")
def index():
    selected_date = request.args.get("date", date.today().isoformat())

    try:
        response = requests.get(
            MLB_SCHEDULE_URL,
            params={"sportId": 1, "date": selected_date, "hydrate": "team,linescore"},
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

    dates = response.json().get("dates", [])
    games = []
    for day in dates:
        for game in day.get("games", []):
            teams = game.get("teams", {})
            home = teams.get("home", {})
            away = teams.get("away", {})
            linescore = game.get("linescore") or {}
            inning_state = linescore.get("inningState")
            current_inning = linescore.get("currentInning")
            if inning_state and current_inning:
                state_lower = inning_state.lower()
                if state_lower.startswith("mid"):
                    inning_display = "mid"
                elif state_lower.startswith("end"):
                    inning_display = "end"
                else:
                    inning_display = f"{inning_state} {current_inning}"
            else:
                inning_display = (game.get("status") or {}).get("detailedState") or "Scheduled"

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
                    "status": (game.get("status") or {}).get("detailedState"),
                    "home_team": (home.get("team") or {}).get("name"),
                    "home_abbr": (home.get("team") or {}).get("abbreviation") or (home.get("team") or {}).get("name"),
                    "home_logo_url": _team_logo_url((home.get("team") or {}).get("id")),
                    "home_score": home_score if home_score is not None else "-",
                    "visitor_team": (away.get("team") or {}).get("name"),
                    "visitor_abbr": (away.get("team") or {}).get("abbreviation") or (away.get("team") or {}).get("name"),
                    "visitor_logo_url": _team_logo_url((away.get("team") or {}).get("id")),
                    "visitor_score": away_score if away_score is not None else "-",
                    "inning_display": inning_display,
                    "inning_number": current_inning or "-",
                    "inning_arrow": inning_arrow,
                    "is_final": (game.get("status") or {}).get("detailedState", "").lower().startswith("final") or (game.get("status") or {}).get("detailedState", "").lower().startswith("game over") or (game.get("status") or {}).get("detailedState", "").lower().startswith("completed"),
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
                "count": len(games),
                "games": games,
                "routes": [
                    "/games/<game_id>/score",
                    "/games/<game_id>",
                    "/score/<game_id>",
                ],
            }
        )

    return render_template_string(
        GAMES_LIST_TEMPLATE,
        selected_date=selected_date,
        games=games,
    )


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
    inning_number = linescore.get("currentInning") or "-"
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
    last_pitch = ((last_event.get("details") or {}).get("description")) or "-"
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
        last_pitch_meta = "-"
    last_play_text = ((current_play.get("result") or {}).get("description")) or last_pitch

    pitch_count = "-"
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

    return render_template_string(
        SCOREBOARD_TEMPLATE,
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
        away_runs=away_score if away_score is not None else "-",
        balls=balls,
        strikes=strikes,
        home_abbr=home_abbr,
        home_logo_url=_team_logo_url(home_team.get("id")),
        home_runs=home_score if home_score is not None else "-",
        inning_number=inning_number,
        inning_arrow=inning_arrow,
        first_base=bool(offense.get("first")),
        second_base=bool(offense.get("second")),
        third_base=bool(offense.get("third")),
        outs=outs,
    )


if __name__ == "__main__":
    app.run(debug=True)
