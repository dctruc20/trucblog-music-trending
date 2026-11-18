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
import unicodedata
import urllib.parse
import urllib.request

BASE = 'https://www.googleapis.com/youtube/v3/'
OUTPUT = Path(__file__).resolve().parent.parent / 'trending.json'
ID = re.compile(r'^[A-Za-z0-9_-]{11}$')
PLAYLIST_ID = re.compile(r'^(?:PL|UU|FL|OLAK5uy_|RD)[\w-]{8,150}$')
REGIONS = ('VN', 'AU', 'US', 'GB')
LANGUAGE = {'VN':'vi','AU':'en','US':'en','GB':'en'}
COUNTRY_QUERIES = {
  'gameshow': {
    'VN': 'gameshow truyền hình Việt Nam tập đầy đủ VTV HTV chính thức',
    'AU': 'Australian television game show full episode official Australia',
    'US': 'American game show full episode official United States',
    'GB': 'British game show full episode official BBC ITV United Kingdom',
  },
  'movie': {
    'VN': 'phim Việt Nam trọn bộ phim điện ảnh Việt Nam kênh chính thức',
    'AU': 'Australian film full movie official Australia',
    'US': 'American film full movie official United States',
    'GB': 'British film full movie official United Kingdom',
  },
}
CHANNEL_COUNTRY_CACHE = {}
INDIA_WORDS = re.compile(r'\b(?:bollywood|india|indian|hindi|telugu|tamil|malayalam|punjabi|bhojpuri|kannada)\b',re.I)
INDIA_SCRIPTS = re.compile(r'[\u0900-\u0D7F]')
ENGLISH_MARKERS = {
  'AU': re.compile(r'\b(?:australia|australian|sydney|melbourne|abc australia|channel 7 australia)\b',re.I),
  'US': re.compile(r'\b(?:usa|united states|american|hollywood|nbc|cbs|fox television)\b',re.I),
  'GB': re.compile(r'\b(?:uk|british|britain|bbc|itv|england|united kingdom)\b',re.I),
}

def country_query(slug,region):
    return COUNTRY_QUERIES.get(slug, {}).get(region,GENRES[slug][1])

def normalized_text(s):
    s=unicodedata.normalize('NFD',str(s).casefold())
    return ''.join(ch for ch in s if unicodedata.category(ch)!='Mn').replace('đ','d')

def likely_local(item,region):
    country=str(item.get('channelCountry') or '').upper()
    if country:return country==region
    text=str(item.get('title') or '')+' '+str(item.get('channelTitle') or '')
    if INDIA_SCRIPTS.search(text) or INDIA_WORDS.search(text):return False
    if region=='VN':
        return bool(re.search(r'\b(?:viet nam|vietnam|viet|htv|vtv|tron bo|tap|phim viet|sao viet)\b',normalized_text(text)))
    return bool(ENGLISH_MARKERS[region].search(text))

def add_channel_countries(items,key):
    ids={x.get('channelId') for x in items if x.get('channelId')}
    missing=[x for x in sorted(ids) if x not in CHANNEL_COUNTRY_CACHE]
    for start in range(0,len(missing),50):
        group=missing[start:start+50]
        try:
            payload=api('channels',{'part':'snippet','id':','.join(group)},key)
            found={x['id']:str((x.get('snippet') or {}).get('country') or '').upper() for x in payload.get('items') or []}
        except RuntimeError:
            found={}
        for channel in group: CHANNEL_COUNTRY_CACHE[channel]=found.get(channel,'')
    for item in items:item['channelCountry']=CHANNEL_COUNTRY_CACHE.get(item.get('channelId'),'')
    return items


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
                       'viewCount': views, 'publishedAt': str(info.get('publishedAt') or '')[:32],
                       'channelId': str(info.get('channelId') or '')[:64]})
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
                              'videoEmbeddable': 'true', 'videoSyndicated':'true' if slug in COUNTRY_QUERIES else None,
                              'q': country_query(slug,region), 'order': 'relevance' if slug in COUNTRY_QUERIES else 'viewCount',
                              'relevanceLanguage':LANGUAGE[region] if slug in COUNTRY_QUERIES else None,
                              'publishedAfter': cutoff if slug not in COUNTRY_QUERIES else None, 'maxResults': 50,
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
    entries=[details[i] for i in found if i in details]
    if slug in COUNTRY_QUERIES:
        add_channel_countries(entries,key)
        entries=[v for v in entries if likely_local(v,region)]
    return entries[:target]


def genre_playlists(slug: str, key: str, limit: int, search_one, region_override=None) -> list[dict]:
    label, query, region = GENRES[slug]
    if region_override and slug in COUNTRY_QUERIES:
        region=region_override;query=country_query(slug,region)
    params={'part':'snippet','type':'playlist','q':query+' playlist',
            'regionCode':region,'maxResults':min(30,max(limit*4,12))}
    if region_override:
        params['relevanceLanguage']=LANGUAGE[region]
        params['order']='relevance'
    payload=search_one(params)
    ids,items=[],{}
    for obj in payload.get('items') or []:
        raw=(obj.get('id') or {}).get('playlistId')
        if not isinstance(raw,str) or not PLAYLIST_ID.fullmatch(raw) or raw in items:continue
        sn=obj.get('snippet') or {}
        thumbs=sn.get('thumbnails') or {}
        img=(thumbs.get('medium') or thumbs.get('default') or {}).get('url') or ''
        items[raw]={'id':raw,'title':str(sn.get('title') or label)[:170],
                    'channelTitle':str(sn.get('channelTitle') or 'YouTube')[:100],
                    'channelId':str(sn.get('channelId') or ''),
                    'thumbnail':img if str(img).startswith('https://') else ''}
        ids.append(raw)
    if not ids:return []
    details=api('playlists',{'part':'contentDetails,status','id':','.join(ids[:50])},key)
    confirmed={}
    for obj in details.get('items') or []:
        pid=obj.get('id')
        if pid not in items or (obj.get('status') or {}).get('privacyStatus')!='public':continue
        n=(obj.get('contentDetails') or {}).get('itemCount') or 0
        if int(n)<1:continue
        confirmed[pid]={**items[pid],'videoCount':int(n)}
    matches=[confirmed[x] for x in ids if x in confirmed]
    if region_override and slug in COUNTRY_QUERIES:
        add_channel_countries(matches,key)
        matches=[v for v in matches if likely_local(v,region)]
    return matches[:limit]


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
    old_regional = prior.get('playlistsByRegion') or {}
    cutoff = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=lookback_days)).strftime('%Y-%m-%dT%H:%M:%SZ')
    charts, categories, playlists, region_playlists = {}, {}, {}, {}
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
                old_entries=(old_categories.get(region) or {}).get(slug) or []
                # Discard misleading legacy v4 entertainment results with unknown origin.
                categories[region][slug]=[v for v in old_entries if likely_local(v,region)] if slug in COUNTRY_QUERIES else old_entries
    # Non-entertainment playlists may remain genre-wide (e.g. a Korean music playlist).
    # Gameshows/movies must be collected per selected country.
    for slug in chosen:
        if slug in COUNTRY_QUERIES:continue
        try:
            playlists[slug] = genre_playlists(slug, key, playlist_limit, search_one) if playlist_limit else []
            if playlists[slug]: fresh.append('playlists:'+slug)
            elif isinstance(old_lists.get(slug), list): playlists[slug] = old_lists[slug]
        except (RuntimeError, ValueError):
            playlists[slug] = old_lists.get(slug) if isinstance(old_lists.get(slug), list) else []
    for region in REGIONS:
        region_playlists[region]={}
        for slug in ('gameshow','movie'):
            if slug not in chosen:continue
            try:
                result=genre_playlists(slug,key,playlist_limit,search_one,region) if playlist_limit else []
                if not result:raise ValueError('no local playlist')
                region_playlists[region][slug]=result
                fresh.append('playlists:'+region+'/'+slug)
            except (RuntimeError,ValueError):
                prev=(old_regional.get(region) or {}).get(slug) or []
                region_playlists[region][slug]=[v for v in prev if likely_local(v,region)]
    # Expand to 70+ videos for selected leading genres within remaining API budget.
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
      'playlistsByGenre': playlists, 'playlistsByRegion': region_playlists, 'refreshed': fresh,
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    tmp = OUTPUT.with_suffix('.tmp')
    tmp.write_text(json.dumps(result, ensure_ascii=False, separators=(',',':')) + '\n', encoding='utf-8')
    tmp.replace(OUTPUT)
    print(f"Saved {OUTPUT.name} ({len(chosen)} genres, {searches} search calls, {sum(map(len, charts.values()))} chart videos, {sum(map(len, playlists.values()))} playlists)")

if __name__ == '__main__': main()
