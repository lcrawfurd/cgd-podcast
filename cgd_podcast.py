#!/usr/bin/env python3
"""
CGD Blog → Podcast
Fetches new CGD blog posts, converts to MP3 via Edge TTS,
commits audio + RSS feed to GitHub Pages.
Subscribe in Pocket Casts: https://lcrawfurd.github.io/cgd-podcast/feed.xml
"""

import asyncio
import json
import os
import re
import subprocess
import time
from datetime import datetime
from email.utils import formatdate
from pathlib import Path

import edge_tts
import feedparser
import requests
from bs4 import BeautifulSoup
from readability import Document

# ── Config ─────────────────────────────────────────────────────────────────
FEED_URL    = "https://www.cgdev.org/blog/feed"
BASE_DIR    = Path(__file__).parent
AUDIO_DIR   = BASE_DIR / "audio"
PROCESSED   = BASE_DIR / "processed.json"
FEED_FILE   = BASE_DIR / "feed.xml"
GITHUB_USER = "lcrawfurd"
REPO_NAME   = "cgd-podcast"
BASE_URL    = f"https://{GITHUB_USER}.github.io/{REPO_NAME}"
VOICE       = "en-GB-SoniaNeural"   # British female — change to en-GB-RyanNeural for male
MAX_EPISODES = 50                   # keep latest N episodes to avoid repo bloat
MAX_CHARS    = 60_000               # trim very long articles


# ── Helpers ────────────────────────────────────────────────────────────────

def load_processed():
    if PROCESSED.exists():
        return json.loads(PROCESSED.read_text())
    return {}

def save_processed(data):
    PROCESSED.write_text(json.dumps(data, indent=2, ensure_ascii=False))

def x(s):
    """Escape XML special chars."""
    return (s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")

def fetch_article_text(url):
    """Fetch full article text from a CGD blog URL."""
    try:
        headers = {"User-Agent": "Mozilla/5.0"}
        r = requests.get(url, headers=headers, timeout=20)
        r.raise_for_status()
        doc = Document(r.text)
        soup = BeautifulSoup(doc.summary(), "html.parser")
        text = soup.get_text(separator=" ", strip=True)
        text = re.sub(r"\s+", " ", text).strip()
        return text[:MAX_CHARS]
    except Exception as e:
        print(f"  ✗ fetch failed: {e}")
        return None

async def tts(text, path):
    """Convert text to MP3 using Edge TTS."""
    communicate = edge_tts.Communicate(text, VOICE)
    await communicate.save(str(path))

def make_safe_filename(title, pub_date_struct):
    date_str = time.strftime("%Y%m%d", pub_date_struct) if pub_date_struct else datetime.now().strftime("%Y%m%d")
    slug = re.sub(r"[^\w\s-]", "", title)[:60].strip()
    slug = re.sub(r"\s+", "-", slug).lower()
    return f"{date_str}-{slug}.mp3"

def generate_feed(episodes):
    items = ""
    for ep in sorted(episodes.values(), key=lambda e: e["pub_date"], reverse=True):
        items += f"""
    <item>
      <title>{x(ep['title'])}</title>
      <description>{x(ep.get('summary', ''))}</description>
      <link>{x(ep['url'])}</link>
      <pubDate>{ep['pub_date']}</pubDate>
      <guid isPermaLink="false">{x(ep['url'])}</guid>
      <enclosure url="{BASE_URL}/audio/{ep['filename']}" type="audio/mpeg" length="{ep['size']}"/>
    </item>"""

    return f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:itunes="http://www.itunes.com/dtds/podcast-1.0.dtd">
  <channel>
    <title>CGD Blog (Audio)</title>
    <description>Center for Global Development blog posts, converted to audio.</description>
    <link>https://www.cgdev.org/blog</link>
    <language>en-gb</language>
    <itunes:author>Center for Global Development</itunes:author>
    <itunes:category text="Society &amp; Culture"/>
    {items}
  </channel>
</rss>"""

def git_push(new_files, commit_msg):
    os.chdir(BASE_DIR)
    for f in new_files:
        subprocess.run(["git", "add", str(f)], check=True)
    subprocess.run(["git", "add", "processed.json", "feed.xml"], check=True)
    subprocess.run(["git", "commit", "-m", commit_msg], check=True)
    subprocess.run(["git", "push"], check=True)


# ── Main ───────────────────────────────────────────────────────────────────

def main():
    AUDIO_DIR.mkdir(parents=True, exist_ok=True)
    processed = load_processed()

    print(f"Checking CGD feed…")
    feed = feedparser.parse(FEED_URL)
    if not feed.entries:
        print("No entries found — check network or feed URL.")
        return

    new_files = []
    for entry in feed.entries:
        url = entry.get("link", "")
        if not url or url in processed:
            continue

        title = entry.get("title", "Untitled")
        print(f"\nProcessing: {title}")

        text = fetch_article_text(url)
        if not text:
            continue

        full_text = f"{title}. {text}"

        pub_struct = entry.get("published_parsed")
        filename = make_safe_filename(title, pub_struct)
        audio_path = AUDIO_DIR / filename

        try:
            asyncio.run(tts(full_text, audio_path))
            size = audio_path.stat().st_size
            print(f"  ✓ {filename} ({size // 1024} KB)")
        except Exception as e:
            print(f"  ✗ TTS failed: {e}")
            continue

        pub_date = formatdate(time.mktime(pub_struct)) if pub_struct else formatdate()
        summary = BeautifulSoup(entry.get("summary", ""), "html.parser").get_text()[:300]

        processed[url] = {
            "title": title,
            "url": url,
            "filename": filename,
            "size": size,
            "pub_date": pub_date,
            "summary": summary,
        }
        new_files.append(audio_path)

    if not new_files:
        print("\nNo new posts.")
        return

    # Enforce episode cap — remove oldest MP3s from disk and processed dict
    if len(processed) > MAX_EPISODES:
        sorted_eps = sorted(processed.items(), key=lambda kv: kv[1]["pub_date"])
        to_remove = sorted_eps[:len(processed) - MAX_EPISODES]
        for url_key, ep in to_remove:
            old_file = AUDIO_DIR / ep["filename"]
            if old_file.exists():
                old_file.unlink()
                subprocess.run(["git", "rm", "--cached", "-f", str(old_file)], cwd=BASE_DIR, capture_output=True)
            del processed[url_key]
        print(f"Pruned {len(to_remove)} old episode(s).")

    save_processed(processed)
    FEED_FILE.write_text(generate_feed(processed), encoding="utf-8")

    titles = [processed[f]["title"] if isinstance(f, str) else "" for f in [n.name for n in new_files]]
    commit_msg = f"Add {len(new_files)} new episode(s): {', '.join(t[:40] for t in list(processed.values())[-len(new_files):])}"
    git_push(new_files, commit_msg)
    print(f"\nDone. {len(new_files)} new episode(s) pushed.")
    print(f"Feed: {BASE_URL}/feed.xml")

if __name__ == "__main__":
    main()
