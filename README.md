# Out of Town Games

Out of Town Games is a Flask app that presents MLB schedule, game, and standings views in a compact dark scoreboard style. Data is sourced from the MLB Stats API.

## Routes

| Route | Description |
|---|---|
| `/` | Daily game index with live state, bases/outs, inning status, and compact win-probability sparkline cues |
| `/games/<id>/score` | Single-game scoreboard with pitch context, batter/pitcher details, and a bottom delta win-probability chart |
| `/standings` | AL/NL East and West standings |

## Current Behavior

- Index page:
	- Shows today by default and supports day navigation.
	- Orders games as: in-progress, not-started, then final.
	- Non-started games are non-clickable.
	- Uses responsive 1/2/3-column card layout.
- Game page:
	- Shows batter, batting order slot, AVG/OBP/OPS, pitcher, pitch count, count, bases, and outs.
	- Hides outs when inning context does not indicate top/bottom.
	- Refreshes every 5s by default, 3s with runner on third, and may back off to 10s when state is unchanged.
	- Stops auto-refresh when game is final.
	- Bottom chart displays win-probability delta over time (away-home) with inning half markers.
- Standings page:
	- Auto-refreshes with shared bottom progress bar component.

## Caching

- Schedule (`/`) API calls are uncached for freshest game state.
- Standings API responses are cached in memory (TTL 1 hour).
- Standings cache is invalidated when newly final games are detected.
- Win-probability history is cached on disk in `win_prob_cache.json` and pruned to keep at most the current plus most recent game per team.

## Project Layout

- `main.py` - Flask routes and page composition
- `utils.py` - API helpers, formatting, win-probability caching, sparkline/chart data shaping
- `templates/index.html` - Daily game index template
- `templates/game.html` - Single-game scoreboard template
- `templates/standings.html` - Standings template
- `static/index.css` - Index styles
- `static/game.css` - Game page styles
- `static/standings.css` - Standings styles
- `static/refresh_bar.css` - Shared refresh progress bar styles

## Run Locally

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python main.py
```

App URL: `http://localhost:5000`

## Deployment

Configured for Railway. Typical process command:

```bash
gunicorn main:app
```

## Stack

- Python 3.11+
- Flask + Jinja2
- MLB Stats API
- Vanilla HTML/CSS/JS
