#!/usr/bin/env python3
"""Fetch multi-sport RSS headlines and refresh the schedule-backed NFL picks board."""
from __future__ import annotations
import argparse, datetime as dt, html, json, os, re, sys
from zoneinfo import ZoneInfo
import urllib.error, urllib.request, xml.etree.ElementTree as ET
from pathlib import Path
from predictions_refresh import refresh as refresh_prediction_board

ROOT=Path(__file__).resolve().parent
ARTICLES=ROOT/'articles.json'
PREDICTIONS=ROOT/'predictions.json'
ESPN_SCHEDULE='https://www.espn.com/nfl/schedule/_/week'
ESPN_SCOREBOARD='https://site.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard?dates='
FEEDS=[
 ('BBC Sport','Football','https://feeds.bbci.co.uk/sport/football/rss.xml'),
 ('ESPN Soccer','Football','https://www.espn.com/espn/rss/soccer/news'),
 ('ESPN NBA','Basketball','https://www.espn.com/espn/rss/nba/news'),
 ('ESPN Tennis','Tennis','https://www.espn.com/espn/rss/tennis/news'),
 ('ESPN NHL','Hockey','https://www.espn.com/espn/rss/nhl/news'),
 ('ESPN NFL','NFL','https://www.espn.com/espn/rss/nfl/news'),
]
SPORTS=['Football','Basketball','Tennis','Hockey','NFL']
IMAGES={
 'Football':'https://images.unsplash.com/photo-1517466787929-bc90951d0974?auto=format&fit=crop&w=1400&q=82',
 'Basketball':'https://images.unsplash.com/photo-1546519638-68e109498ffc?auto=format&fit=crop&w=1400&q=82',
 'Tennis':'https://images.unsplash.com/photo-1622279457486-62dcc4a431d6?auto=format&fit=crop&w=1400&q=82',
 'Hockey':'https://images.unsplash.com/photo-1579952363873-27f3bade9f55?auto=format&fit=crop&w=1400&q=82',
 'NFL':'https://images.unsplash.com/photo-1566577739112-5180d4bf9390?auto=format&fit=crop&w=1400&q=82',
}
def clean(value:str)->str:
 return re.sub(r'\s+',' ',html.unescape(re.sub(r'<[^>]+>',' ',value or ''))).strip()
def slugify(value:str)->str:
 return re.sub(r'[^a-z0-9]+','-',value.lower()).strip('-')[:80].strip('-') or 'sports-update'
def fetch_feed(name:str,sport:str,url:str,timeout:int=15)->list[dict]:
 req=urllib.request.Request(url,headers={'User-Agent':'TouchlineSportsNews/1.0 (RSS reader)'})
 with urllib.request.urlopen(req,timeout=timeout) as response: raw=response.read(3_000_000)
 root=ET.fromstring(raw); entries=[]
 for item in root.findall('.//item'):
  title=clean(item.findtext('title','')); link=clean(item.findtext('link','')); desc=clean(item.findtext('description',''))
  if title and link.startswith(('https://','http://')): entries.append({'source_name':name,'sport':sport,'title':title,'source_url':link,'summary':desc[:900]})
 if not entries:
  ns={'a':'http://www.w3.org/2005/Atom'}
  for item in root.findall('a:entry',ns):
   title=clean(item.findtext('a:title','',ns)); el=item.find('a:link',ns); link=el.get('href','') if el is not None else ''
   desc=clean(item.findtext('a:summary','',ns) or item.findtext('a:content','',ns))
   if title and link: entries.append({'source_name':name,'sport':sport,'title':title,'source_url':link,'summary':desc[:900]})
 return entries
def make_draft(item:dict,use_ai:bool)->dict:
 title,summary=item['title'],item['summary']; source=item['source_name']; sport=item['sport']
 summary=summary or f'{title}. This update is based on reporting by {source}; follow the original report for further developments.'
 body=[f'{title}. This story is based on reporting published by {source}.',summary,
       f'For the complete report and updates, read the original coverage from {source}. This summary does not add facts beyond the source material supplied by its feed.']
 if use_ai:
  generated=ai_write(title,summary,source,item['source_url'],sport)
  if generated: summary=generated.get('summary',summary); body=generated.get('body',body)
 dek=summary[:187]+'…' if len(summary)>190 else summary
 return {'slug':slugify(title),'title':title,'dek':dek,'category':sport,'sport':sport,'date':dt.date.today().isoformat(),'read_minutes':2,
  'image':IMAGES[sport],'image_alt':f'{sport} story photo','source_name':source,'source_url':item['source_url'],'summary':summary,'body':body,'draft':True,
  'updated_at':dt.datetime.now(dt.timezone.utc).isoformat(timespec='seconds')}
def make_prediction(sport:str,day:dt.date)->dict:
 slug=f'{day.isoformat()}-{sport.lower()}-predictions'
 return {'slug':slug,'title':f'{sport} predictions: {day.strftime("%B %-d, %Y")} matchday outlook','dek':f'No verified {sport} fixture or bookmaker odds are available in this edition. No pick is published until current source data can be checked.',
  'category':'Predictions','sport':sport,'type':'prediction','date':day.isoformat(),'read_minutes':2,'image':IMAGES[sport],'image_alt':f'{sport} prediction preview',
  'source_name':'Touchline Predictions Desk','source_url':'','summary':'Fixtures, odds and implied probabilities are not published without a current verifiable public source. This post is an editorial placeholder, not a betting recommendation.',
  'body':['Fixtures and bookmaker prices change frequently. No current fixture or odds source was verified for this sport in this edition, so no match pick or implied probability is presented.','When a source supplies decimal odds, implied probability is calculated as 100 divided by the decimal odds, before bookmaker margin. Predictions remain opinions and are never guarantees.'],
  'odds':None,'implied_probability':None,'confidence':'low','fixtures_verified':False,'draft':True,'updated_at':dt.datetime.now(dt.timezone.utc).isoformat(timespec='seconds')}
def prediction_confidence(spread:float)->str:
 size=abs(spread)
 return 'high' if size>=8 else 'medium' if size>=4 else 'low'
def prediction_rationale(favorite:str,spread:float,confidence:str)->str:
 size=abs(spread)
 band={'low':'a narrow line that points to a close contest','medium':'a meaningful but not overwhelming spread','high':'one of the slate’s largest spread gaps'}[confidence]
 return f'The market lists {favorite} as the favorite by {size:g} points, {band}. The model-style lean follows that listed edge; confidence is {confidence} because the label is based on spread size alone, not a guarantee of the result.'
def ai_write(title:str,summary:str,source_name:str,source_url:str,sport:str)->dict|None:
 key=os.environ.get('OPENAI_API_KEY')
 if not key:return None
 base=os.environ.get('OPENAI_BASE_URL','https://api.openai.com/v1').rstrip('/'); model=os.environ.get('OPENAI_MODEL','gpt-4o-mini')
 prompt=(f'Write an original short {sport} news draft using ONLY the source headline and excerpt below. Do not invent results, quotes, dates, injuries, context or claims. If details are sparse, state the limitation. Return JSON only, keys summary (2 sentences) and body (array of 3 concise paragraphs). Source: {source_name} ({source_url})\nHeadline: {title}\nExcerpt: {summary}')
 payload=json.dumps({'model':model,'temperature':0.3,'messages':[{'role':'system','content':'You are a careful multi-sport news editor. Stay strictly within supplied facts.'},{'role':'user','content':prompt}],'response_format':{'type':'json_object'}}).encode()
 req=urllib.request.Request(base+'/chat/completions',data=payload,headers={'Authorization':'Bearer '+key,'Content-Type':'application/json'},method='POST')
 try:
  with urllib.request.urlopen(req,timeout=45) as response:data=json.load(response)
  result=json.loads(data['choices'][0]['message']['content'])
  if isinstance(result.get('summary'),str) and isinstance(result.get('body'),list):return result
 except (urllib.error.URLError,TimeoutError,KeyError,ValueError,json.JSONDecodeError) as exc:print(f'AI generation failed for {title!r}; using cautious template: {exc}',file=sys.stderr)
 return None
def run(limit:int=8,use_ai:bool=True)->int:
 today=dt.datetime.now(ZoneInfo('America/New_York')).date()
 existing=json.loads(ARTICLES.read_text(encoding='utf-8')) if ARTICLES.exists() else []
 today_text=today.isoformat()
 seen={a.get('source_url','') for a in existing if a.get('source_url')}|{a.get('slug','') for a in existing if a.get('type')!='prediction'}
 collected=[]
 for name,sport,url in FEEDS:
  try:
   items=fetch_feed(name,sport,url); print(f'{name}: fetched {len(items)} {sport} feed entries'); collected.extend(items)
  except Exception as exc:print(f'{name}: feed unavailable: {exc}',file=sys.stderr)
 added=[]
 for item in collected:
  slug=slugify(item['title'])
  if item['source_url'] in seen or slug in seen:continue
  added.append(make_draft(item,use_ai));seen.add(item['source_url']);seen.add(slug)
  if len(added)>=limit:break
 predictions_updated=refresh_prediction_board(today)
 combined=added+existing
 if combined!=existing:
  tmp=ARTICLES.with_suffix('.json.tmp');tmp.write_text(json.dumps(combined,ensure_ascii=False,indent=2)+'\n',encoding='utf-8');tmp.replace(ARTICLES)
 if added:
  drafts=ROOT/'drafts';drafts.mkdir(exist_ok=True)
  for a in added:
   lines=[f"# {a['title']}",'',f"*{a['date']} | {a['source_name']} | DRAFT*",'',a['dek'],'',*[p for para in a['body'] for p in (para,'')],f"Source: [{a['source_name']}]({a['source_url']})",'']
   (drafts/f"{a['slug']}.md").write_text('\n'.join(lines),encoding='utf-8')
 print(f'Added {len(added)} sports article draft(s); NFL predictions board refresh: {"updated" if predictions_updated else "unchanged"}.')
 return 0 if collected or added or predictions_updated else 1
if __name__=='__main__':
 parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--limit',type=int,default=8,help='maximum new feed stories');parser.add_argument('--no-ai',action='store_true',help='use the local cautious draft template');args=parser.parse_args();raise SystemExit(run(max(1,args.limit),not args.no_ai))
