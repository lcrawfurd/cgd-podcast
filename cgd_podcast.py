#!/usr/bin/env python3
"""
CGD Blog → Podcast
Fetches new CGD blog posts via real Chrome (bypasses Cloudflare),
converts to MP3 via Edge TTS, commits audio + RSS feed to GitHub Pages.

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
import nodriver
from bs4 import BeautifulSoup
from readability import Document

# ── Config ─────────────────────────────────────────────────────────────────
BLOG_URL     = "https://www.cgdev.org/blog"
BASE_DIR     = Path(__file__).parent
AUDIO_DIR    = BASE_DIR / "audio"
PROCESSED    = BASE_DIR / "processed.json"
FEED_FILE    = BASE_DIR / "feed.xml"
GITHUB_USER  = "lcrawfurd"
REPO_NAME    = "cgd-podcast"
BASE_URL     = f"https://{GITHUB_USER}.github.io/{REPO_NAME}"
CHROME        = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
CHROME_PROFILE = str(Path.home() / ".cgd-podcast-chrome")  # persistent profile = reuses CF cookies
VOICE         = "en-GB-SoniaNeural"   # Change to en-GB-RyanNeural for male
MAX_EPISODES  = 50
MAX_CHARS     = 60_000
CF_WAIT_SECS  = 10   # seconds to wait for Cloudflare to pass


# ── Helpers ─────────────────────────────────────────────────────────────────

def load_processed():
    if PROCESSED.exists():
        return json.loads(PROCESSED.read_text())
    return {}

def save_processed(data):
    PROCESSED.write_text(json.dumps(data, indent=2, ensure_ascii=False))

def x(s):
    return (s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")

async def get_html(browser, url):
    tab = await browser.get(url)
    await asyncio.sleep(CF_WAIT_SECS)
    return await tab.evaluate("document.documentElement.outerHTML")

async def get_blog_entries(browser):
    """Scrape the CGD blog listing for new post URLs and titles."""
    html = await get_html(browser, BLOG_URL)
    soup = BeautifulSoup(html, "html.parser")
    entries = []
    seen = set()
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if re.match(r"^/blog/[a-z0-9-]{5,}$", href):
            url = f"https://www.cgdev.org{href}"
            if url not in seen:
                seen.add(url)
                # Clean title: strip "Blog Post" prefix added by CGD markup
                title = re.sub(r"^Blog Post\s*", "", a.get_text(strip=True))
                entries.append({"url": url, "title": title or href.split("/")[-1].replace("-", " ").title()})
    return entries

async def fetch_article_text(browser, url):
    """Fetch and clean article body text."""
    try:
        html = await get_html(browser, url)
        doc = Document(html)
        soup = BeautifulSoup(doc.summary(), "html.parser")
        text = soup.get_text(separator=" ", strip=True)
        text = re.sub(r"\s+", " ", text).strip()
        return text[:MAX_CHARS]
    except Exception as e:
        print(f"  ✗ fetch failed: {e}")
        return None

async def tts(text, path):
    communicate = edge_tts.Communicate(text, VOICE)
    await communicate.save(str(path))

def make_filename(title):
    date_str = datetime.now().strftime("%Y%m%d")
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
    result = subprocess.run(["git", "diff", "--cached", "--quiet"])
    if result.returncode == 0:
        print("Nothing new to commit.")
        return
    subprocess.run(["git", "commit", "-m", commit_msg], check=True)
    subprocess.run(["git", "push"], check=True)


# ── Main ────────────────────────────────────────────────────────────────────

async def main():
    AUDIO_DIR.mkdir(parents=True, exist_ok=True)
    processed = load_processed()

    print("Starting browser…")
    browser = await nodriver.start(
        browser_executable_path=CHROME,
        user_data_dir=CHROME_PROFILE,
        headless=False,
    )

    try:
        print(f"Fetching CGD blog listing…")
        entries = await get_blog_entries(browser)
        print(f"Found {len(entries)} posts on listing page.")

        new_files = []
        for entry in entries:
            url = entry["url"]
            if url in processed:
                continue

            title = entry["title"]
            print(f"\nProcessing: {title}")

            text = await fetch_article_text(browser, url)
            if not text:
                continue

            full_text = f"{title}. {text}"
            filename = make_filename(title)
            audio_path = AUDIO_DIR / filename

            try:
                await tts(full_text, audio_path)
                size = audio_path.stat().st_size
                print(f"  ✓ {filename} ({size // 1024} KB)")
            except Exception as e:
                print(f"  ✗ TTS failed: {e}")
                continue

            processed[url] = {
                "title": title,
                "url": url,
                "filename": filename,
                "size": size,
                "pub_date": formatdate(),
                "summary": text[:300],
            }
            save_processed(processed)  # save after each article so restarts resume
            new_files.append(audio_path)

    finally:
        browser.stop()

    if not new_files:
        print("\nNo new posts.")
        return

    # Enforce episode cap
    if len(processed) > MAX_EPISODES:
        sorted_eps = sorted(processed.items(), key=lambda kv: kv[1]["pub_date"])
        to_remove = sorted_eps[:len(processed) - MAX_EPISODES]
        for url_key, ep in to_remove:
            old_file = AUDIO_DIR / ep["filename"]
            if old_file.exists():
                old_file.unlink()
                subprocess.run(["git", "rm", "--cached", "-f", str(old_file)],
                               cwd=BASE_DIR, capture_output=True)
            del processed[url_key]
        print(f"Pruned {len(to_remove)} old episode(s).")

    save_processed(processed)
    FEED_FILE.write_text(generate_feed(processed), encoding="utf-8")

    recent_titles = [processed[f.name.replace('.mp3','')]['title'] if f.name.replace('.mp3','') in processed
                     else list(processed.values())[-1]['title']
                     for f in new_files[:3]]
    commit_msg = f"Add {len(new_files)} episode(s): {', '.join(t[:35] for t in recent_titles)}"
    git_push(new_files, commit_msg)

    print(f"\nDone. {len(new_files)} new episode(s) pushed.")
    print(f"Subscribe in Pocket Casts: {BASE_URL}/feed.xml")


if __name__ == "__main__":
    asyncio.run(main())
