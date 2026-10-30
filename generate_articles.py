#!/usr/bin/env python3
"""Fetch football RSS headlines and append source-linked article drafts.

By default, drafts are generated with a grounded template. Set OPENAI_API_KEY to
optionally ask the OpenAI-compatible endpoint configured in OPENAI_BASE_URL for
an original, source-grounded article. No credentials are stored in this project.
"""
from __future__ import annotations
import argparse
import datetime as dt
import html
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parent
ARTICLES = ROOT / "articles.json"
FEEDS = [
    ("BBC Sport", "https://feeds.bbci.co.uk/sport/football/rss.xml"),
    ("ESPN Soccer", "https://www.espn.com/espn/rss/soccer/news"),
]
IMAGES = [
    "https://images.unsplash.com/photo-1522778119026-d647f0596c20?auto=format&fit=crop&w=1400&q=85",
    "https://images.unsplash.com/photo-1517466787929-bc90951d0974?auto=format&fit=crop&w=1400&q=85",
    "https://images.unsplash.com/photo-1508098682722-e99c643e7f0b?auto=format&fit=crop&w=1400&q=85",
]

def clean(value: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", value or ""))).strip()

def slugify(value: str) -> str:
    text = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")[:75].strip("-")
    return text or "football-update"

def fetch_feed(name: str, url: str, timeout: int = 15) -> list[dict]:
    request = urllib.request.Request(url, headers={"User-Agent": "TouchlineSportsNews/1.0 (RSS reader)"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        raw = response.read(3_000_000)
    root = ET.fromstring(raw)
    entries = []
    for item in root.findall(".//item"):
        title = clean(item.findtext("title", ""))
        link = clean(item.findtext("link", ""))
        description = clean(item.findtext("description", ""))
        guid = clean(item.findtext("guid", link))
        if title and link and link.startswith(("https://", "http://")):
            entries.append({"source_name": name, "title": title, "source_url": link,
                            "summary": description[:900], "guid": guid})
    # Atom feeds are accepted too.
    if not entries:
        ns = {"a": "http://www.w3.org/2005/Atom"}
        for item in root.findall("a:entry", ns):
            title = clean(item.findtext("a:title", "", ns))
            link_el = item.find("a:link", ns)
            link = link_el.get("href", "") if link_el is not None else ""
            desc = clean(item.findtext("a:summary", "", ns) or item.findtext("a:content", "", ns))
            if title and link:
                entries.append({"source_name": name, "title": title, "source_url": link,
                                "summary": desc[:900], "guid": link})
    return entries

def make_draft(item: dict, idx: int, use_ai: bool) -> dict:
    title, source_summary = item["title"], item["summary"]
    slug = slugify(title)
    summary = source_summary or f"{title}. This update is based on reporting by {item['source_name']}; follow the original report for further developments."
    paragraphs = [
        f"{title}. This story is based on reporting published by {item['source_name']}.",
        summary if summary else f"The source headline points to this as a developing football story. The details available in the feed are limited, so this draft avoids adding unverified context.",
        f"For the complete report and any updates, read the original coverage from {item['source_name']}. This summary does not add facts beyond the source material supplied by its feed."
    ]
    if use_ai:
        generated = ai_write(title, summary, item["source_name"], item["source_url"])
        if generated:
            summary = generated.get("summary", summary)
            paragraphs = generated.get("body", paragraphs)
    description = (summary[:190] + "…") if len(summary) > 190 else summary
    return {
        "slug": slug, "title": title, "dek": description,
        "category": "Football", "date": dt.date.today().isoformat(), "read_minutes": 2,
        "image": IMAGES[idx % len(IMAGES)], "image_alt": "Football stadium during a match",
        "source_name": item["source_name"], "source_url": item["source_url"],
        "summary": summary, "body": paragraphs, "draft": True,
        "updated_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    }

def ai_write(title: str, source_summary: str, source_name: str, source_url: str) -> dict | None:
    key = os.environ.get("OPENAI_API_KEY")
    if not key:
        return None
    base = os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/")
    model = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")
    prompt = ("Write an original short football news draft using ONLY the source headline and excerpt below. "
              "Do not invent results, quotes, dates, injuries, context or claims. If details are sparse, state the limitation. "
              "Return JSON only, with keys summary (2 sentences) and body (array of 3 concise paragraphs). "
              f"Source: {source_name} ({source_url})\nHeadline: {title}\nExcerpt: {source_summary}")
    payload = json.dumps({"model": model, "temperature": 0.3, "messages": [
        {"role": "system", "content": "You are a careful football news editor. Stay strictly within supplied facts."},
        {"role": "user", "content": prompt}], "response_format": {"type": "json_object"}}).encode()
    req = urllib.request.Request(base + "/chat/completions", data=payload,
        headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=45) as response:
            data = json.load(response)
        content = data["choices"][0]["message"]["content"]
        result = json.loads(content)
        if isinstance(result.get("summary"), str) and isinstance(result.get("body"), list):
            return result
    except (urllib.error.URLError, TimeoutError, KeyError, ValueError, json.JSONDecodeError) as exc:
        print(f"AI generation failed for {title!r}; using cautious template: {exc}", file=sys.stderr)
    return None

def run(limit: int = 8, use_ai: bool = True) -> int:
    existing = json.loads(ARTICLES.read_text(encoding="utf-8")) if ARTICLES.exists() else []
    seen = {a.get("source_url", "") for a in existing} | {a.get("slug", "") for a in existing}
    collected: list[dict] = []
    for name, url in FEEDS:
        try:
            found = fetch_feed(name, url)
            print(f"{name}: fetched {len(found)} football feed entries")
            collected.extend(found)
        except Exception as exc:
            print(f"{name}: feed unavailable: {exc}", file=sys.stderr)
    added = []
    for item in collected:
        slug = slugify(item["title"])
        if item["source_url"] in seen or slug in seen:
            continue
        added.append(make_draft(item, len(added), use_ai))
        seen.add(item["source_url"]); seen.add(slug)
        if len(added) >= limit:
            break
    if not added:
        print("No new articles were added. Existing stories remain unchanged.")
        return 0 if collected else 1
    # New articles appear first. The published seed articles remain available.
    temp = ARTICLES.with_suffix(".json.tmp")
    temp.write_text(json.dumps(added + existing, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temp.replace(ARTICLES)
    drafts_dir = ROOT / "drafts"
    drafts_dir.mkdir(exist_ok=True)
    for article in added:
        md = [f"# {article['title']}", "", f"*{article['date']} | {article['source_name']} | DRAFT*", "",
              article["dek"], "", *[p for para in article["body"] for p in (para, "")],
              f"Source: [{article['source_name']}]({article['source_url']})", ""]
        (drafts_dir / f"{article['slug']}.md").write_text("\n".join(md), encoding="utf-8")
    print(f"Added {len(added)} article draft(s) to articles.json and drafts/")
    return 0

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=8, help="maximum new feed stories to append")
    parser.add_argument("--no-ai", action="store_true", help="use only the local cautious draft template")
    args = parser.parse_args()
    raise SystemExit(run(max(1, args.limit), not args.no_ai))
