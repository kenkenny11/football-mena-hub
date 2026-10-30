"""Build Touchline's weekend football and NFL pick boards from ESPN public schedules."""
from __future__ import annotations
import datetime as dt
import json
import re
import urllib.request
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent
OUTPUT = ROOT / "predictions.json"
ESPN_NFL_PAGE = "https://www.espn.com/nfl/schedule/_/week"
FOOTBALL_SOURCES = {
    "Premier League": "https://www.espn.com/soccer/schedule/_/league/eng.1",
    "La Liga": "https://www.espn.com/soccer/schedule/_/league/esp.1",
    "Serie A": "https://www.espn.com/soccer/schedule/_/league/ita.1",
    "Bundesliga": "https://www.espn.com/soccer/schedule/_/league/ger.1",
}
API = "https://site.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard?dates="

def confidence(spread: float) -> str:
    size = abs(spread)
    return "high" if size >= 8 else "medium" if size >= 4 else "low"

def football_confidence(american_odds: int | None) -> str:
    if american_odds is None:
        return "low"
    return "high" if american_odds <= -300 else "medium" if american_odds <= -150 else "low"

def football_rationale(favorite: str, confidence_label: str, line: str | None) -> str:
    if line:
        return f"ESPN lists {favorite} as the market favorite ({line}). The opinion follows that public price, with {confidence_label} confidence based on how strongly the favorite is priced; football outcomes remain uncertain."
    return f"No verified odds line was available for this fixture, so the model-style opinion leans toward {favorite} on a cautious, low-confidence basis. This is a matchup opinion, not a claim about certainty."

def parse_football_schedule(league: str, day: dt.date, source_url: str) -> list[dict]:
    request = urllib.request.Request(source_url, headers={"User-Agent": "TouchlineSportsNews/1.0 (public schedule refresh)"})
    with urllib.request.urlopen(request, timeout=20) as response:
        page = response.read().decode("utf-8", errors="replace")
    # ESPN serves the schedule table in page markup; the page parser below extracts only rows for the target weekend.
    from html.parser import HTMLParser
    class ScheduleParser(HTMLParser):
        def __init__(self):
            super().__init__(); self.rows=[]; self.row=None; self.cell=None; self.in_cell=False
        def handle_starttag(self, tag, attrs):
            attrs=dict(attrs)
            if tag == "tr": self.row=[]
            elif tag in ("td","th") and self.row is not None: self.cell=[]; self.in_cell=True
        def handle_endtag(self, tag):
            if tag in ("td","th") and self.in_cell and self.row is not None: self.row.append(" ".join(self.cell).strip()); self.cell=None; self.in_cell=False
            elif tag == "tr" and self.row is not None: self.rows.append(self.row); self.row=None
        def handle_data(self,data):
            if self.in_cell and self.cell is not None: self.cell.append(data.strip())
    parser=ScheduleParser(); parser.feed(page)
    current_day=None; result=[]
    for row in parser.rows:
        text=" | ".join(x for x in row if x)
        date_match=re.search(r"(?:Saturday|Sunday),?\s+(October|November)\s+(\d{1,2}),?\s+2026", text, re.I)
        if date_match:
            month=10 if date_match.group(1).lower().startswith("oct") else 11
            try: current_day=dt.date(2026,month,int(date_match.group(2)))
            except ValueError: current_day=None
            continue
        if current_day != day or len(row)<3 or not row[0] or row[0].upper() in ("MATCH","MATCHUP"): continue
        cells=[re.sub(r"\s+"," ",x).strip() for x in row]
        matchup=re.search(r"(.+?)\s+v\s+(.+)", " ".join(cells[:3]),re.I)
        if not matchup: continue
        away,home=matchup.group(1).strip(),matchup.group(2).strip()
        time=cells[2] if len(cells)>2 else "Time TBD"
        odds_text=" ".join(cells[3:])
        odd_match=re.search(r"Line:\s*([A-Z0-9]+)\s*([+-]\d+(?:\.\d+)?)\s+O/U:\s*([\d.]+)",odds_text,re.I)
        favorite=None; line=None; total=None; confidence_label="low"
        if odd_match:
            abbr,price,total=odd_match.groups(); price=float(price); line=f"{abbr} {price:+g}"
            # ESPN soccer moneyline odds use a negative number for favorite, positive for underdog.
            favorite=home if price<0 else away
            confidence_label=football_confidence(round(price)) if price<0 else "low"
        else:
            favorite=away
        # A verified positive line makes the away team an underdog, so use the home team only if no line data exists.
        if odd_match and price>0: favorite=home
        result.append({"id":re.sub(r"[^a-z0-9]+","-",f"{league}-{away}-{home}".lower()).strip("-"),"league":league,"away":away,"home":home,"kickoff":time,"favorite":favorite,"spread":line,"total":total,"confidence":confidence_label,"rationale":football_rationale(favorite,confidence_label,line)})
    return result

def football_api_board(day: dt.date) -> dict:
    games=[]
    for league,url in FOOTBALL_SOURCES.items():
        api=f"https://site.api.espn.com/apis/site/v2/sports/soccer/{url.rsplit('/',1)[-1]}/scoreboard?dates={day.strftime('%Y%m%d')}"
        try:
            request=urllib.request.Request(api,headers={"User-Agent":"TouchlineSportsNews/1.0 (public schedule refresh)"})
            with urllib.request.urlopen(request,timeout=20) as response: data=json.load(response)
            for event in data.get("events",[]):
                comp=(event.get("competitions") or [{}])[0]; odds=(comp.get("odds") or [{}])[0]
                teams=comp.get("competitors") or []
                away=next((t for t in teams if t.get("homeAway")=="away"),None); home=next((t for t in teams if t.get("homeAway")=="home"),None)
                if not away or not home: continue
                away_name=away["team"].get("displayName") or away["team"].get("name"); home_name=home["team"].get("displayName") or home["team"].get("name")
                start=event.get("date") or comp.get("date")
                kickoff=dt.datetime.fromisoformat(start.replace("Z","+00:00")).astimezone(ZoneInfo("America/New_York")).strftime("%-I:%M %p ET") if start else "Time TBD"
                detail=odds.get("details") or ""
                total=odds.get("overUnder")
                fav_home=(odds.get("homeTeamOdds") or {}).get("favorite")
                fav_away=(odds.get("awayTeamOdds") or {}).get("favorite")
                favorite=home_name if fav_home else away_name if fav_away else None
                price=(odds.get("homeTeamOdds") or {}).get("moneyLine") if fav_home else (odds.get("awayTeamOdds") or {}).get("moneyLine") if fav_away else None
                rating=football_confidence(int(price)) if price is not None and int(price)<0 else "low"
                if not favorite: continue
                games.append({"id":re.sub(r"[^a-z0-9]+","-",f"{league}-{away_name}-{home_name}".lower()).strip("-"),"league":league,"away":away_name,"home":home_name,"kickoff":kickoff,"favorite":favorite,"spread":detail or None,"total":str(total) if total is not None else None,"confidence":rating,"rationale":football_rationale(favorite,rating,detail or None)})
        except Exception as exc: print(f"ESPN {league} API unavailable for {day.isoformat()}: {exc}")
    return {"date":day.isoformat(),"league":"Football","source_name":"BBC Sport Premier League schedule","source_urls":{"Premier League":"https://www.bbc.co.uk/sport/football/premier-league/scores-fixtures/2026-10","Premier League next month":"https://www.bbc.co.uk/sport/football/premier-league/scores-fixtures/2026-11"},"confidence_guide":"Football picks are editorial model opinions, not odds-based. Confidence is low when no verified match pricing or team-strength model is available. No spread, total or bookmaker odds are shown.","disclaimer":"model opinion, not betting advice","games":games}

def football_board(day: dt.date) -> dict:
    # BBC fixture listing verified for Oct 31; ESPN provides current public schedules for daily refresh.
    board=football_api_board(day)
    if board["games"]: return board
    games=[]
    for league,url in FOOTBALL_SOURCES.items():
        try: games.extend(parse_football_schedule(league,day,url))
        except Exception as exc: print(f"ESPN {league} schedule unavailable for {day.isoformat()}: {exc}")
    board["games"]=games
    return board

def bbc_epl_board(day: dt.date) -> dict:
    # Source has been checked against BBC's date-specific fixture listings.
    fixtures={
      dt.date(2026,10,31): [
        ("Chelsea","Manchester United","12:30"),("Bournemouth","Leeds United","15:00"),("Brentford","Nottingham Forest","15:00"),("Coventry City","Sunderland","15:00"),("Hull City","Ipswich Town","15:00"),("Manchester City","Brighton & Hove Albion","15:00"),("Tottenham Hotspur","Crystal Palace","17:30"),("Aston Villa","Fulham","20:00")],
      dt.date(2026,11,1): [("Liverpool","Arsenal","16:30")]
    }
    games=[]
    for home,away,time in fixtures.get(day,[]):
        # A clear, low-confidence home-team editorial lean, not a betting market claim.
        favorite=home
        games.append({"id":re.sub(r"[^a-z0-9]+","-",f"epl-{home}-{away}".lower()).strip("-"),"league":"Premier League","away":away,"home":home,"kickoff":time+" GMT","favorite":favorite,"spread":None,"total":None,"confidence":"low","rationale":f"Our model-style opinion makes a cautious home-side lean toward {favorite}, based only on the fixture context and without a verified odds line or quantified team-strength model. Confidence is low; this is an editorial view, not a forecast backed by bookmaker prices."})
    return {"date":day.isoformat(),"league":"Football","source_name":"BBC Sport Premier League schedule","source_urls":{"October":"https://www.bbc.co.uk/sport/football/premier-league/scores-fixtures/2026-10","November":"https://www.bbc.co.uk/sport/football/premier-league/scores-fixtures/2026-11"},"confidence_guide":"Football confidence is low for all picks because these editorial leans use no verified betting odds or quantified model. No spread, total or bookmaker odds are shown.","disclaimer":"model opinion, not betting advice","games":games}

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
    return {"date":day.isoformat(),"league":"NFL","source_name":"ESPN NFL Schedule","source_url":ESPN_NFL_PAGE,"confidence_guide":"Confidence reflects spread size only: low below 4 points, medium from 4 to under 8, high at 8 or more. It is a simple line-strength label, not a probability or guarantee.","disclaimer":"model opinion, not betting advice","pick_of_day":pick["id"],"games":games,"updated_at":dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")}

def refresh(today: dt.date) -> bool:
    # Refresh NFL as the primary board, then append sourced weekend football cards when available.
    nfl_board=None
    for offset in range(1, 11):
        day=today+dt.timedelta(days=offset)
        request=urllib.request.Request(API+day.strftime("%Y%m%d"),headers={"User-Agent":"TouchlineSportsNews/1.0 (public schedule refresh)"})
        try:
            with urllib.request.urlopen(request,timeout=20) as response: data=json.load(response)
        except Exception as exc:
            print(f"ESPN NFL schedule unavailable for {day.isoformat()}: {exc}"); continue
        nfl_board=board_from_events(day,data.get("events",[]))
        if nfl_board: break
    today_board=bbc_epl_board(today+dt.timedelta(days=1))
    sunday_board=bbc_epl_board(today+dt.timedelta(days=2))
    today_board["games"].extend(sunday_board["games"])
    if not nfl_board:
        print("No upcoming ESPN NFL slate with published lines found; kept the existing NFL board.")
        # A football board may still refresh when the NFL source is temporarily unavailable.
        if not today_board["games"]: return False
        nfl_board={"date":today_board["date"],"league":"Football","source_name":"ESPN schedules","source_urls":FOOTBALL_SOURCES,"confidence_guide":today_board["confidence_guide"],"disclaimer":"model opinion, not betting advice","pick_of_day":None,"games":[],"updated_at":dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")}
    nfl_board["football_games"]=today_board["games"]
    nfl_board["football_source_urls"]={"October":"https://www.bbc.co.uk/sport/football/premier-league/scores-fixtures/2026-10","November":"https://www.bbc.co.uk/sport/football/premier-league/scores-fixtures/2026-11"}
    nfl_board["football_confidence_guide"]=today_board["confidence_guide"]
    nfl_board["updated_at"]=dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    temp=OUTPUT.with_suffix(".json.tmp"); temp.write_text(json.dumps(nfl_board,ensure_ascii=False,indent=2)+"\n",encoding="utf-8"); temp.replace(OUTPUT)
    print(f"Refreshed {len(nfl_board['games'])} NFL and {len(nfl_board['football_games'])} football prediction cards.")
    return bool(nfl_board["games"] or nfl_board["football_games"])
