#!/usr/bin/env python3
"""Publish a daily static YouTube mostPopular/Music snapshot for TrucBlog.
Requires env YOUTUBE_API_KEY in CI. The key must never enter the public website.
"""
import datetime
import json
import os
import pathlib
import re
import urllib.error
import urllib.parse
import urllib.request

OUT = pathlib.Path(__file__).resolve().parent.parent / "trending.json"
API = "https://www.googleapis.com/youtube/v3/videos"
COUNTRIES = ("VN", "AU")
VIDEO_ID = re.compile(r"^[\w-]{11}$")


def get_region(country: str, key: str) -> list[dict]:
    params = {
        "part": "snippet,statistics",
        "chart": "mostPopular",
        "regionCode": country,
        "videoCategoryId": "10",  # YouTube category: Music
        "maxResults": "18",
        "key": key,
    }
    request = urllib.request.Request(
        API + "?" + urllib.parse.urlencode(params),
        headers={"Accept": "application/json", "User-Agent": "TrucBlog-Music-DailyCharts/1.0"},
    )
    try:
        with urllib.request.urlopen(request, timeout=25) as response:
            payload = json.load(response)
    except urllib.error.HTTPError as err:
        detail = err.read(500).decode("utf-8", "replace")
        raise RuntimeError(f"YouTube {country} responded HTTP {err.code}: {detail}") from err
    items = payload.get("items", [])
    if not isinstance(items, list):
        raise ValueError(f"Invalid YouTube API response for {country}")
    result = []
    seen = set()
    for item in items:
        vid = str(item.get("id", ""))
        snippet = item.get("snippet", {}) or {}
        if not VIDEO_ID.fullmatch(vid) or vid in seen:
            continue
        if str(snippet.get("categoryId", "10")) != "10":
            continue
        title = str(snippet.get("title", "")).strip()
        if not title or title in ("Private video", "Deleted video"):
            continue
        seen.add(vid)
        stats = item.get("statistics", {}) or {}
        try:
            views = max(0, int(stats.get("viewCount", 0)))
        except (ValueError, TypeError):
            views = 0
        result.append({
            "id": vid,
            "title": title[:240],
            "channelTitle": str(snippet.get("channelTitle", "YouTube"))[:160],
            "viewCount": views,
            "publishedAt": snippet.get("publishedAt", ""),
        })
    return result


def main():
    key = os.getenv("YOUTUBE_API_KEY", "").strip()
    if not key:
        raise SystemExit("YOUTUBE_API_KEY is missing. Add it in GitHub repository Secrets.")
    previous = {}
    if OUT.exists():
        try:
            previous = json.loads(OUT.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            pass
    old_regions = previous.get("regions", {})
    regions = {}
    fresh_regions = []
    for country in COUNTRIES:
        try:
            videos = get_region(country, key)
            if not videos:
                raise ValueError("Chart was empty")
            regions[country] = videos
            fresh_regions.append(country)
            print(f"{country}: fetched {len(videos)} music videos")
        except (RuntimeError, ValueError, urllib.error.URLError, TimeoutError) as err:
            print(f"WARNING: {country}: {err}")
            if isinstance(old_regions.get(country), list) and old_regions[country]:
                regions[country] = old_regions[country]
            else:
                regions[country] = []
    if not fresh_regions:
        raise SystemExit("No charts refreshed; leaving last published trending.json unchanged.")
    updated_at = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    output = {
        "schemaVersion": 1,
        "source": "YouTube Data API videos.list chart=mostPopular category=Music",
        "updatedAt": updated_at,
        "refreshedRegions": fresh_regions,
        "regions": regions,
    }
    OUT.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("Saved", OUT)


if __name__ == "__main__":
    main()
