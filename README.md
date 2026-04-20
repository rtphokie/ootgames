# Out of Town Games

A minimal MLB scoreboard web app, inspired by the out-of-town scoreboards found in ballparks like Fenway Park, Wrigley Field, and Minute Maid Park. Data is sourced from the [MLB Stats API](https://github.com/toddrob99/MLB-StatsAPI/wiki/Endpoints).

## Pages

| Route | Description |
|---|---|
| `/` | Schedule for the current day — scores, inning, baserunners, and outs for every MLB game |
| `/standings` | Division standings for AL East, AL West, NL East, and NL West |
| `/games/<id>/score` | Live scoreboard for a single game — score, inning, pitch info, win probability |

## Features

- Scores, inning state (top/bottom), baserunners, and outs on the schedule page
- Pregame start times displayed in the user's local timezone
- Previous/next day navigation on the schedule page
- Live win probability on the scoreboard page for in-progress games
- Auto-refresh every 15 seconds (schedule) and 5–10 seconds (scoreboard)
- Browser timezone detection — defaults to `America/New_York`

## Running locally

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python main.py
```

The app starts on [http://localhost:5000](http://localhost:5000).

## Deployment

Deployed on [Railway](https://railway.app) using gunicorn:

```
gunicorn main:app
```

## Stack

- **Python 3.11+** / **Flask** — web framework
- **MLB Stats API** — schedule, live game feed, win probability, standings
- **Vanilla HTML/CSS/JS** — no frontend framework; all styles in `static/`
- **Jinja2** — server-side templating in `templates/`
