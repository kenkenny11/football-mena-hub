# Touchline

A lightweight, football-first sports news blog with a Middle East lens. It includes a responsive homepage, source-linked article pages and a daily RSS-to-draft script. It is a local static site, so it can be previewed with Python's built-in web server or deployed to any static host.

## Run the site

Python 3 is enough for the preview server:

```bash
python3 -m http.server 8000
```

Open http://localhost:8000. Use the homepage to browse stories and open an individual article. Each story links to its original publisher. The included story photography uses remote Unsplash image URLs, so images need an internet connection.

## Daily article updates

`generate_articles.py` reads BBC Sport Football and ESPN Soccer RSS feeds, avoids adding a story whose URL or generated slug already exists, then appends new entries to `articles.json` and creates a matching Markdown draft in `drafts/`. The site reads `articles.json` directly, so a page reload shows appended stories. Review the Markdown and source reporting before publishing: new feed items are marked as drafts and are not independently fact-checked by the script.

Run once manually:

```bash
python3 generate_articles.py
```

To use the optional AI rewrite, set `OPENAI_API_KEY` in the environment of the scheduled process. Optional configuration: `OPENAI_BASE_URL` (defaults to `https://api.openai.com/v1`) and `OPENAI_MODEL` (defaults to `gpt-4o-mini`). The AI prompt explicitly limits the copy to facts in the RSS title and excerpt; when no key is configured, a cautious local template is used. The script never embeds or saves the key. You can disable AI explicitly with `python3 generate_articles.py --no-ai`, or limit the number of added stories with `--limit 5`.

Example daily cron entry, running at 06:15 server-local time:

```cron
15 6 * * * cd /home/sports-blog && /usr/bin/python3 generate_articles.py >> /home/sports-blog/update.log 2>&1
```

Set cron to your preferred timezone. The script requires outbound internet access to read feeds and, if enabled, contact the configured AI endpoint. Feed outages are reported; if neither feed can be read, the script exits with an error and leaves existing articles intact.

## Contents

- `index.html`, `styles.css`, `app.js`: responsive homepage and article listing
- `article.html`, `article.js`: individual story view, selected by `?slug=...`
- `articles.json`: seed stories and new generated entries
- `generate_articles.py`: RSS collector and draft writer
- `drafts/`: generated Markdown draft files

## Seed edition and editorial note

The initial edition contains five original summaries dated October 30, 2026. Each is based on a linked report from BBC Sport, ESPN or Voice of Emirates. These seed stories were written from the cited source material, not copied from beIN Sports. The design takes broad inspiration from a football-led MENA sports site but does not reuse its brand, content or assets. Match schedules and fitness reports can change; use the source link for the latest details.

## Before public launch

The updater creates drafts, not reviewed journalism. Review and correct each new draft before treating it as published reporting. Images are representative remote photographs, not publisher-provided match photos. A traffic-oriented design cannot guarantee search ranking or revenue; add your own domain, analytics, privacy notice, social sharing metadata and image licensing review before launch.
