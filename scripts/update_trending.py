#!/usr/bin/env python3
"""TrucBlog Music Pro v4.6: refresh VN/AU popular music and official Vietnamese music shows.

YouTube Data API key is used ONLY in GitHub Actions via YOUTUBE_API_KEY.
Public trending.json contains no API keys. Python stdlib only.
"""
import datetime as dt
import json
import os
from pathlib import Path
import re
import unicodedata
from urllib import parse, request, error

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / 'trending.json'
SHOWS = json.loads((ROOT / 'show_categories.json').read_text('utf-8'))
API = 'https://www.googleapis.com/youtube/v3/'
YOUTUBE_ID = re.compile(r'^[A-Za-z0-9_-]{11}$')
TODAY = dt.datetime.now(dt.timezone.utc)
MAX_SHOW_VIDEOS = 20


def api_call(endpoint, params, key):
    query = parse.urlencode({**params, 'key': key})
    req = request.Request(API + endpoint + '?' + query,
                          headers={'Accept': 'application/json', 'User-Agent': 'TrucBlog-Music/4.6'})
    try:
        with request.urlopen(req, timeout=30) as res:
            payload = json.load(res)
    except error.HTTPError as exc:
        # Never print the request URL (it contains the secret API key).
        raise RuntimeError(f'{endpoint}: YouTube API HTTP {exc.code}') from None
    except (error.URLError, TimeoutError, ValueError) as exc:
        raise RuntimeError(f'{endpoint}: network/API response failed ({type(exc).__name__})') from None
    if not isinstance(payload, dict):
        raise RuntimeError(f'{endpoint}: invalid response JSON')
    return payload


def flat(value):
    normalized = unicodedata.normalize('NFD', str(value).lower().replace('đ', 'd'))
    return re.sub(r'\s+', ' ', ''.join(ch for ch in normalized if unicodedata.category(ch) != 'Mn')).strip()


def video_record(item):
    ident = item.get('id', '')
    if not isinstance(ident, str) or not YOUTUBE_ID.fullmatch(ident):
        return None
    snip = item.get('snippet') or {}
    status = item.get('status') or {}
    if status.get('embeddable') is False or status.get('privacyStatus', 'public') != 'public':
        return None
    title = str(snip.get('title') or '').strip()
    if title in ('', 'Private video', 'Deleted video'):
        return None
    if snip.get('liveBroadcastContent') == 'live':
        return None
    try:
        views = max(0, int((item.get('statistics') or {}).get('viewCount', 0)))
    except (ValueError, TypeError):
        views = 0
    thumbnails = snip.get('thumbnails') or {}
    image_info = next((thumbnails[k] for k in ('maxres', 'standard', 'high', 'medium') if isinstance(thumbnails.get(k), dict)), {})
    return {
        'id': ident,
        'title': title[:230],
        'channelTitle': str(snip.get('channelTitle') or 'YouTube')[:140],
        'viewCount': views,
        'publishedAt': str(snip.get('publishedAt') or ''),
        'thumbnail': image_info.get('url') or f'https://i.ytimg.com/vi/{ident}/hqdefault.jpg',
    }


def get_region(country, key):
    payload = api_call('videos', {
        'part': 'snippet,statistics,status', 'chart': 'mostPopular', 'regionCode': country,
        'videoCategoryId': '10', 'maxResults': '50',
    }, key)
    seen = set()
    out = []
    for item in payload.get('items', []):
        if str((item.get('snippet') or {}).get('categoryId', '10')) != '10':
            continue
        record = video_record(item)
        if record and record['id'] not in seen:
            seen.add(record['id'])
            out.append(record)
    return out


def get_show(show, key):
    # YouTube search.list costs about 100 API quota units per call.
    # Filter for embeddable videos and then double-check with videos.list status.embeddable.
    search_payload = api_call('search', {
        'part': 'id,snippet', 'q': show['query'], 'type': 'video',
        'regionCode': 'VN', 'relevanceLanguage': 'vi',
        'videoEmbeddable': 'true', 'maxResults': '35', 'order': 'date',
    }, key)
    candidates = []
    for item in search_payload.get('items', []):
        vid = (item.get('id') or {}).get('videoId', '')
        snippet = item.get('snippet') or {}
        title = str(snippet.get('title', ''))
        channel = flat(snippet.get('channelTitle', ''))
        full_text = flat(title + ' ' + snippet.get('description', ''))
        # Discourage third-party reuploads while accepting the official Vie/Yeah1 channel family.
        channel_id = str(snippet.get('channelId') or '')
        allowed_channels = show.get('channelIds') or []
        is_official = channel_id in allowed_channels if allowed_channels else any(flat(token) in channel for token in show.get('official', []))
        topic = flat(show.get('minimumTerm', ''))
        if not YOUTUBE_ID.fullmatch(vid) or not is_official or topic not in full_text:
            continue
        if any(w in flat(title) for w in ('trailer', 'teaser', 'reaction', 'hau truong', 'full tap', 'tap full', 'review')):
            continue
        candidates.append(vid)
    candidates = list(dict.fromkeys(candidates))[:35]
    if not candidates:
        return []
    details = api_call('videos', {
        'part': 'snippet,statistics,status,contentDetails', 'id': ','.join(candidates), 'maxResults': '50',
    }, key)
    items = []
    for item in details.get('items', []):
        record = video_record(item)
        if not record:
            continue
        # Exclude full episodes over 30 minutes; retain short performances and music videos.
        duration = (item.get('contentDetails') or {}).get('duration', '')
        m = re.fullmatch(r'PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?', duration)
        if m and (int(m.group(1) or 0) * 3600 + int(m.group(2) or 0) * 60 + int(m.group(3) or 0)) > 1800:
            continue
        items.append(record)
    # Recency-first, then popularity: this is a RECENT CURATED SHOW list, not official YouTube Trending ranking.
    items.sort(key=lambda x: (x['publishedAt'], x['viewCount']), reverse=True)
    return items[:MAX_SHOW_VIDEOS]


def main():
    key = os.getenv('YOUTUBE_API_KEY', '').strip()
    if not key:
        raise SystemExit('Missing YOUTUBE_API_KEY. Add GitHub repository Settings > Secrets > Actions.')
    try:
        old = json.loads(OUT.read_text('utf-8'))
    except (OSError, json.JSONDecodeError):
        old = {}
    old_regions = old.get('regions') if isinstance(old.get('regions'), dict) else {}
    old_shows = old.get('collections') if isinstance(old.get('collections'), dict) else {}
    regions, collections = {}, {}
    refreshed_regions, refreshed_shows = [], []
    for region in ('VN', 'AU'):
        try:
            current = get_region(region, key)
            if not current:
                raise ValueError('empty results')
            regions[region] = current
            refreshed_regions.append(region)
            print(region, 'popular music:', len(current))
        except (RuntimeError, ValueError) as exc:
            print('WARNING', region, type(exc).__name__, str(exc))
            regions[region] = old_regions.get(region, []) if isinstance(old_regions.get(region), list) else []
    for show in SHOWS:
        slug = show['id']
        try:
            current = get_show(show, key)
            if not current:
                raise ValueError('no eligible official embeddable performances')
            collections[slug] = current
            refreshed_shows.append(slug)
            print(show['label'], 'performances:', len(current))
        except (RuntimeError, ValueError) as exc:
            print('WARNING', slug, type(exc).__name__, str(exc))
            collections[slug] = old_shows.get(slug, []) if isinstance(old_shows.get(slug), list) else []
    if not refreshed_regions and not refreshed_shows:
        raise SystemExit('No API results refreshed; leaving published trending.json untouched.')
    stamp = TODAY.isoformat(timespec='seconds').replace('+00:00', 'Z')
    updated = {
        'schemaVersion': 2,
        'source': 'YouTube Data API: music mostPopular + official-channel show performances (not official show rankings)',
        'isFallback': False,
        'updatedAt': stamp,
        'refreshedRegions': refreshed_regions,
        'refreshedCollections': refreshed_shows,
        'collectionLabels': {s['id']: s['label'] for s in SHOWS},
        'regions': regions,
        'collections': collections,
    }
    OUT.write_text(json.dumps(updated, ensure_ascii=False, indent=2) + '\n', 'utf-8')
    print('Wrote', OUT.name, 'schemaVersion=2', 'regions', len(refreshed_regions), 'shows', len(refreshed_shows))


if __name__ == '__main__':
    main()
