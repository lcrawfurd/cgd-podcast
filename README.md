# CGD Blog Audio Podcast

Automatically converts [Center for Global Development](https://www.cgdev.org/blog) blog posts into an MP3 podcast feed, updated daily.

**Subscribe in Pocket Casts (or any podcast app):**
```
https://lcrawfurd.github.io/cgd-podcast/feed.xml
```

## How it works

1. A daily cron job runs `cgd_podcast.py` at 7:30am
2. The script opens the CGD blog using a real Chrome browser (to bypass Cloudflare protection)
3. New posts are extracted, cleaned, and converted to MP3 using Microsoft Edge TTS (`en-GB-SoniaNeural` voice)
4. Each episode includes a short intro ("This is an automated reading of a blog post from the Center for Global Development…") and outro
5. Audio files and an RSS feed are committed and pushed to GitHub Pages
6. The podcast feed is immediately available at the URL above

## Setup

### Dependencies

```bash
pip install edge-tts nodriver beautifulsoup4 readability-lxml
```

Also requires Google Chrome installed at `/Applications/Google Chrome.app`.

### Running manually

```bash
python3 cgd_podcast.py
```

### Scheduling (macOS LaunchAgent)

A `com.lee.cgd-podcast.plist` LaunchAgent runs the script daily at 7:30am. Logs go to `run.log`.

## Configuration

Key settings at the top of `cgd_podcast.py`:

| Variable | Default | Description |
|----------|---------|-------------|
| `VOICE` | `en-GB-SoniaNeural` | TTS voice (change to `en-GB-RyanNeural` for male) |
| `MAX_EPISODES` | 50 | Maximum episodes kept in the feed; oldest are removed |
| `CF_WAIT_SECS` | 10 | Seconds to wait for Cloudflare challenge to clear |
| `MAX_CHARS` | 60,000 | Maximum characters per article sent to TTS |

## Notes

- Audio files are stored in `audio/` and tracked in `processed.json`
