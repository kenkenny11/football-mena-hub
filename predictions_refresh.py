"""Build Touchline's NFL pick board from ESPN's public scoreboard schedule feed."""
from __future__ import annotations
import datetime as dt
import json
import re
import urllib.request
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent
OUTPUT = ROOT / "predictions.json"
ESPN_PAGE = "https://www.espn.com/nfl/schedule/_/week"
API = "https://site.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard?dates="

def confidence(spread: float) -> str:
    size = abs(spread)
    return "high" if size >= 8 else "medium" if size >= 4 else "low"

def rationale(favorite: str, spread: float, rating: str) -> str:
    size = abs(spread)
    band = {"low": "a narrow line that points to a close contest", "medium": "a meaningful but not overwhelming spread", "high": "one of the slate's largest spread gaps"}[rating]
    return f"The market lists {favorite} as the favorite by {size:g} points, {band}. The model-style lean follows that listed edge; confidence is {rating} because the label is based on spread size alone, not a guarantee of the result."

def board_from_events(day: dt.date, events: list[dict]) -> dict | None:
    games = []
    for event in events:
        comp = (event.get("competitions") or [{}])[0]
        odds = (comp.get("odds") or [{}])[0]
        teams = comp.get("competitors") or []
        away = next((team for team in teams if team.get("homeAway") == "away"), None)
        home = next((team for team in teams if team.get("homeAway") == "home"), None)
        if not away or not home or not odds.get("details") or odds.get("overUnder") is None:
            continue
        favorite_comp = home if (odds.get("homeTeamOdds") or {}).get("favorite") else away
        favored = favorite_comp["team"]
        favorite = favored.get("displayName") or favored.get("name")
        line = odds["details"]
        match = re.search(r"([+-]?\d+(?:\.\d+)?)\s*$", line)
        if not match:
            continue
        margin = abs(float(match.group(1)))
        rating = confidence(margin)
        start = event.get("date") or comp.get("date")
        kickoff = dt.datetime.fromisoformat(start.replace("Z", "+00:00")).astimezone(ZoneInfo("America/New_York")).strftime("%-I:%M %p ET") if start else "Time TBD"
        away_team, home_team = away["team"], home["team"]
        games.append({"id": f"{away_team.get('abbreviation','').lower()}-{home_team.get('abbreviation','').lower()}", "away": away_team.get("displayName") or away_team.get("name"), "home": home_team.get("displayName") or home_team.get("name"), "kickoff": kickoff, "spread": line, "favorite": favorite, "favorite_spread": f"{favored.get('abbreviation')} {match.group(1)}", "total": str(odds["overUnder"]), "confidence": rating, "rationale": rationale(favorite, margin, rating)})
    if not games:
        return None
    pick = next((game for game in games if game["id"] == "bal-buf"), games[0])
    return {"date": day.isoformat(), "league": "NFL", "source_name": "ESPN NFL Schedule", "source_url": ESPN_PAGE, "confidence_guide": "Confidence reflects spread size only: low below 4 points, medium from 4 to under 8, high at 8 or more. It is a simple line-strength label, not a probability or guarantee.", "disclaimer": "model opinion, not betting advice", "pick_of_day": pick["id"], "games": games, "updated_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")}

def refresh(today: dt.date) -> bool:
    # Find the next actual NFL slate day with games and lines, within the next 10 days.
    for offset in range(1, 11):
        day = today + dt.timedelta(days=offset)
        request = urllib.request.Request(API + day.strftime("%Y%m%d"), headers={"User-Agent": "TouchlineSportsNews/1.0 (public schedule refresh)"})
        try:
            with urllib.request.urlopen(request, timeout=20) as response:
                data = json.load(response)
        except Exception as exc:
            print(f"ESPN schedule unavailable for {day.isoformat()}: {exc}")
            continue
        board = board_from_events(day, data.get("events", []))
        if board is None:
            continue
        temp = OUTPUT.with_suffix(".json.tmp")
        temp.write_text(json.dumps(board, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        temp.replace(OUTPUT)
        print(f"Refreshed {len(board['games'])} NFL pick cards for {day.isoformat()} from ESPN public schedule data.")
        return True
    print("No upcoming ESPN NFL slate with published lines found; kept the existing prediction board.")
    return False
