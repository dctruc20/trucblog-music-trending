#!/usr/bin/env python3
"""TrucBlog Music Pro v4.5: daily video charts, genre videos, public playlist discovery.
YouTube Data API server-side only. Keep YOUTUBE_API_KEY in GitHub Actions Secrets.
The trending chart is a mostPopular music chart; genre/playlist matches are discovery,
NOT official per-genre charts. Up to 90 search.list requests per scheduled run.
"""
from __future__ import annotations
import datetime as dt
import json
import os
from pathlib import Path
import re
import urllib.parse
import urllib.request

BASE = 'https://www.googleapis.com/youtube/v3/'
OUTPUT = Path(__file__).resolve().parent.parent / 'trending.json'
ID = re.compile(r'^[A-Za-z0-9_-]{11}$')
PLAYLIST_ID = re.compile(r'^(?:PL|UU|FL|OLAK5uy_|RD)[\w-]{8,150}$')
REGIONS = ('VN', 'AU', 'US', 'GB')
GENRES = {
    'vpop': ('V-Pop / Nhạc trẻ', 'nhạc trẻ Việt Nam official music video', 'VN'),
    'bolero': ('Bolero / Trữ tình', 'bolero nhạc trữ tình official', 'VN'),
    'remix': ('Remix / EDM', 'electronic dance music remix official', 'US'),
    'lofi': ('Lofi / Chill', 'lofi chill music mix official', 'US'),
    'instrumental': ('Hòa tấu / Không lời', 'instrumental piano guitar music official', 'US'),
    'usuk': ('US–UK', 'US UK pop official music video', 'US'),
    'kpop': ('K-Pop', 'KPOP official music video', 'KR'),
    'jpop': ('J-Pop', 'J-POP Japanese official music video', 'JP'),
    'catholic': ('Nhạc Công giáo', 'nhạc thánh ca Công giáo Catholic music', 'VN'),
    'children': ('Nhạc thiếu nhi', 'nhạc thiếu nhi children songs music official', 'VN'),
    'gameshow': ('Gameshow YouTube', 'gameshow full episode official', 'VN'),
    'movie': ('Phim YouTube', 'full movie official channel', 'US'),
}


def bounded(name: str, default: int, lower: int, upper: int) -> int:
    try:
        return max(lower, min(upper, int(os.environ.get(name, str(default)))))
    except ValueError:
        return default


def api(name: str, params: dict, key: str) -> dict:
    req = urllib.request.Request(BASE + name + '?' + urllib.parse.urlencode({**params, 'key': key}),
                                 headers={'Accept': 'application/json', 'User-Agent': 'TrucBlog-Music/4.5'})
    try:
        with urllib.request.urlopen(req, timeout=25) as r:
            return json.load(r)
    except Exception as exc:
        # Do not print exception strings: a URL inside an HTTPError may contain the API key.
        raise RuntimeError(f'YouTube {name}: API request failed ({type(exc).__name__})') from None


def good_videos(items: list) -> list[dict]:
    result, seen = [], set()
    for entry in items:
        raw_id = entry.get('id')
        vid = raw_id.get('videoId') if isinstance(raw_id, dict) else raw_id
        if not isinstance(vid, str) or not ID.fullmatch(vid) or vid in seen:
            continue
        info = entry.get('snippet') or {}
        status = entry.get('status') or {}
        if status.get('embeddable') is False or status.get('privacyStatus', 'public') != 'public':
            continue
        title = str(info.get('title') or '').strip()
        if title.casefold() in ('private video', 'deleted video', ''):
            continue
        seen.add(vid)
        try:
            views = max(0, int((entry.get('statistics') or {}).get('viewCount', 0)))
        except (ValueError, TypeError):
            views = 0
        result.append({'id': vid, 'title': title[:190], 'channelTitle': str(info.get('channelTitle') or 'YouTube')[:120],
                       'viewCount': views, 'publishedAt': str(info.get('publishedAt') or '')[:32]})
    return result


def chart(region: str, key: str, target: int) -> list[dict]:
    items, token, visited = [], '', set()
    for _ in range(min(12, (target + 49)//50 + 2)):
        opts = {'part': 'snippet,statistics,status', 'chart': 'mostPopular', 'regionCode': region,
                'videoCategoryId': '10', 'maxResults': 50}
        if token:
            opts['pageToken'] = token
        payload = api('videos', opts, key)
        known = {x['id'] for x in items}
        items += [v for v in good_videos(payload.get('items') or []) if v['id'] not in known]
        token = payload.get('nextPageToken') or ''
        if len(items) >= target or not token or token in visited:
            break
        visited.add(token)
    return items[:target]


def genre_videos(region: str, slug: str, key: str, target: int, cutoff: str,
                 search_one) -> list[dict]:
    found, token, visited = [], '', set()
    for _ in range(min(3, (target+49)//50)):
        payload = search_one({'part': 'snippet', 'type': 'video', 'regionCode': region,
                              'videoCategoryId': '10' if slug not in ('gameshow', 'movie') else None,
                              'videoEmbeddable': 'true', 'q': GENRES[slug][1], 'order': 'viewCount',
                              'publishedAfter': cutoff, 'maxResults': 50,
                              **({'pageToken': token} if token else {})})
        ids = []
        for v in payload.get('items') or []:
            vid = (v.get('id') or {}).get('videoId')
            if isinstance(vid, str) and ID.fullmatch(vid) and vid not in ids and vid not in found:
                ids.append(vid)
        found += ids
        token = payload.get('nextPageToken') or ''
        if len(found) >= target or not token or token in visited:
            break
        visited.add(token)
    found = found[:target]
    if not found:
        return []
    details = {}
    for start in range(0, len(found), 50):
        payload = api('videos', {'part': 'snippet,statistics,status', 'id': ','.join(found[start:start+50])}, key)
        details.update({v['id']: v for v in good_videos(payload.get('items') or [])})
    return [details[i] for i in found if i in details][:target]


def genre_playlists(slug: str, key: str, limit: int, search_one) -> list[dict]:
    label, query, region = GENRES[slug]
    payload = search_one({'part': 'snippet', 'type': 'playlist', 'q': query + ' playlist',
                          'regionCode': region, 'maxResults': min(20, max(limit * 3, 8))})
    ids, items = [], {}
    for obj in payload.get('items') or []:
        raw = (obj.get('id') or {}).get('playlistId')
        if not isinstance(raw, str) or not PLAYLIST_ID.fullmatch(raw) or raw in items:
            continue
        sn = obj.get('snippet') or {}
        thumbs = sn.get('thumbnails') or {}
        img = (thumbs.get('medium') or thumbs.get('default') or {}).get('url') or ''
        items[raw] = {'id': raw, 'title': str(sn.get('title') or label)[:170],
                      'channelTitle': str(sn.get('channelTitle') or 'YouTube')[:100],
                      'thumbnail': img if str(img).startswith('https://') else ''}
        ids.append(raw)
    if not ids:
        return []
    details = api('playlists', {'part': 'contentDetails,status', 'id': ','.join(ids[:50])}, key)
    confirmed = {}
    for obj in details.get('items') or []:
        pid = obj.get('id')
        if (pid not in items or (obj.get('status') or {}).get('privacyStatus') != 'public'):
            continue
        n = (obj.get('contentDetails') or {}).get('itemCount') or 0
        if n < 1:
            continue
        confirmed[pid] = {**items[pid], 'videoCount': int(n)}
    return [confirmed[x] for x in ids if x in confirmed][:limit]


def main():
    key = os.environ.get('YOUTUBE_API_KEY', '').strip()
    if not key:
        raise SystemExit('Missing secret YOUTUBE_API_KEY')
    chart_limit = bounded('TREND_CHART_LIMIT', 250, 30, 500)
    genre_limit = bounded('TREND_GENRE_LIMIT', 70, 20, 150)
    playlist_limit = bounded('TREND_PLAYLIST_LIMIT', 6, 0, 15)
    search_budget = bounded('TREND_SEARCH_BUDGET', 88, 10, 95)
    lookback_days = bounded('TREND_SEARCH_DAYS', 365, 14, 730)
    chosen = [s.strip().lower() for s in os.environ.get('TREND_GENRES', ','.join(GENRES)).split(',')]
    chosen = list(dict.fromkeys(s for s in chosen if s in GENRES))
    if not chosen:
        raise SystemExit('No supported TREND_GENRES configured')
    prior = {}
    try:
        if OUTPUT.exists(): prior = json.loads(OUTPUT.read_text(encoding='utf-8'))
    except (ValueError, OSError):
        pass
    old_regions = prior.get('regions') or {}
    old_categories = prior.get('categories') or {}
    old_lists = prior.get('playlistsByGenre') or {}
    cutoff = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=lookback_days)).strftime('%Y-%m-%dT%H:%M:%SZ')
    charts, categories, playlists = {}, {}, {}
    searches, fresh = 0, []

    def search_one(params):
        nonlocal searches
        if searches >= search_budget:
            raise RuntimeError('Search call budget reached')
        searches += 1
        return api('search', {k:v for k,v in params.items() if v is not None}, key)

    for region in REGIONS:
        try:
            found = chart(region, key, chart_limit)
            if not found: raise ValueError('empty chart')
            charts[region] = found
            fresh.append('chart:'+region)
        except (RuntimeError, ValueError):
            charts[region] = old_regions.get(region) if isinstance(old_regions.get(region), list) else []
        categories[region] = {}
    # First pass: each genre and region has at least one search (as budget permits).
    for slug in chosen:
        for region in REGIONS:
            try:
                videos = genre_videos(region, slug, key, min(50, genre_limit), cutoff, search_one)
                if not videos: raise ValueError('no videos')
                categories[region][slug] = videos
                fresh.append('videos:'+region+'/'+slug)
            except (RuntimeError, ValueError):
                categories[region][slug] = (old_categories.get(region) or {}).get(slug) or []
    # Playlists are discovered once per genre (country-agnostic), then any region can browse them.
    for slug in chosen:
        try:
            playlists[slug] = genre_playlists(slug, key, playlist_limit, search_one) if playlist_limit else []
            if playlists[slug]: fresh.append('playlists:'+slug)
            elif isinstance(old_lists.get(slug), list): playlists[slug] = old_lists[slug]
        except (RuntimeError, ValueError):
            playlists[slug] = old_lists.get(slug) if isinstance(old_lists.get(slug), list) else []
    # Expand to 70+ videos for the selected leading genres within the remaining API budget.
    prioritized = ['kpop','jpop','usuk','vpop','bolero','lofi','remix','instrumental','catholic','children','gameshow','movie']
    if genre_limit > 50:
        for slug in prioritized:
            if slug not in chosen: continue
            for region in REGIONS:
                if searches >= search_budget: break
                if len(categories[region][slug]) < 45: continue
                try:
                    bigger = genre_videos(region, slug, key, genre_limit, cutoff, search_one)
                    if len(bigger) > len(categories[region][slug]):
                        categories[region][slug] = bigger
                except (RuntimeError, ValueError):
                    continue
    if not fresh:
        if OUTPUT.exists():
            print('No fresh API data; existing trending.json preserved without changing its timestamp')
            return
        raise SystemExit('No data available; trending.json not changed')
    result = {
      'schemaVersion': 4, 'updatedAt': dt.datetime.now(dt.timezone.utc).isoformat(timespec='seconds').replace('+00:00','Z'),
      'source': 'YouTube Data API', 'disclaimer': 'Genre videos and playlists are YouTube search discoveries, not official trend rankings',
      'searchCalls': searches, 'regions': charts,
      'categories': categories, 'categoryLabels': {s: GENRES[s][0] for s in chosen},
      'playlistsByGenre': playlists, 'refreshed': fresh,
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    tmp = OUTPUT.with_suffix('.tmp')
    tmp.write_text(json.dumps(result, ensure_ascii=False, separators=(',',':')) + '\n', encoding='utf-8')
    tmp.replace(OUTPUT)
    print(f"Saved {OUTPUT.name} ({len(chosen)} genres, {searches} search calls, {sum(map(len, charts.values()))} chart videos, {sum(map(len, playlists.values()))} playlists)")

if __name__ == '__main__': main()
