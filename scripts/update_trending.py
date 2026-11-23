#!/usr/bin/env python3
"""TrucBlog Music Pro v4.10: refresh seven charts, Latin aggregation, hot topics and music shows.

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
                          headers={'Accept': 'application/json', 'User-Agent': 'TrucBlog-Music/4.10'})
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
        'tags': [str(t)[:90] for t in (snip.get('tags') or [])[:16]],
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


# Charts use regionCode=GB for the UK. Latin is not a single YouTube chart:
# it combines Mexico, Argentina and Colombia, transparently labelled as a selection.
REGION_CODES = ('VN','AU','US','GB','KR','JP')
LATIN_CODES = ('MX','AR','CO')
REGION_LABELS = {'VN':'Việt Nam','AU':'Australia','US':'US','GB':'UK',
                 'KR':'Hàn Quốc','JP':'Nhật Bản','LAT':'Latin (MX/AR/CO)'}
# These topics re-evaluate daily on real chart video metadata; empty topics are hidden.
TOPIC_RULES = {
    'k-pop': ('K-Pop', r'\b(k.?pop|korean pop|케이팝|아이돌)\b|블랙핑크|방탄소년단'),
    'j-pop': ('J-Pop / Anime', r'\b(j.?pop|anime|japanese pop)\b|アニメ|歌ってみた'),
    'latin-pop': ('Latin Pop / Reggaeton', r'\b(reggaeton|latin pop|urbano|bachata|salsa|cumbia)\b'),
    'v-pop': ('V-Pop', r'\b(v.?pop|nhac tre|nhac viet|vietnamese pop)\b'),
    'rap-hiphop': ('Rap / Hip-Hop', r'\b(rap|hip.?hop|freestyle|cypher|trap)\b'),
    'ballad': ('Pop / Ballad', r'\b(ballad|slow pop|tinh ca)\b'),
    'ost': ('Nhạc phim / OST', r'\b(ost|soundtrack|original soundtrack|nhac phim)\b'),
    'live-stage': ('Live / Sân khấu', r'\b(live|performance|live stage|concert|san khau)\b'),
    'acoustic': ('Acoustic / Guitar', r'\b(acoustic|unplugged|guitar|fingerstyle)\b'),
    'edm-dance': ('EDM / Dance', r'\b(edm|dance music|remix|electronic|dj set)\b'),
    'music-shows': ('Gameshow âm nhạc', r'\b(say hi|masked singer|rap viet|idol|talent show)\b|mat na|toan nang'),
}
TOPIC_IGNORE = {'music','trending','trendingmusic','youtube','official','video','mv',
                'shorts','fyp','viral','subscribe','lyrics','lyric','2026','2025','newmusic',
                'pop','song','songs','kpop','jpop','hit','hits','audio','hd','4k','ytshorts'}


def mix_regional(data, limit=100):
    """Deterministic round-robin, no global ranking claim."""
    pools = [data.get(k, []) for k in (*REGION_CODES, 'LAT')]
    seen=set(); result=[]
    for i in range(max([0]+[len(p) for p in pools])):
        for pool in pools:
            if i >= len(pool): continue
            v=pool[i];vid=v.get('id')
            if vid and vid not in seen:
                seen.add(vid);result.append(v)
                if len(result)>=limit:return result
    return result


def public_record(row):
    return {k:v for k,v in row.items() if k!='tags'}


def hot_topics_from_charts(regions):
    """Discover active themes and hashtags from current chart video metadata (no extra API quota)."""
    items=mix_regional(regions,400)
    buckets={key:[] for key in TOPIC_RULES}
    hashes={}
    for track in items:
        text=flat(track.get('title','')+' '+ ' '.join(track.get('tags', [])))
        for key,(_name,pattern) in TOPIC_RULES.items():
            if re.search(pattern,text,re.I):buckets[key].append(track)
        # Auto discover emerging cross-regional hashtags, not only fixed topic rules.
        hashtags=re.findall(r'#([\w]{3,24})',str(track.get('title',''))+' '+ ' '.join(track.get('tags',[])),re.U)
        for tag in set(hashtags):
            norm=flat(tag).replace(' ','')
            if norm and norm not in TOPIC_IGNORE and not norm.isdigit() and len(norm)>=4:
                hashes.setdefault(norm,{'label':'#'+tag,'items':[]})['items'].append(track)
    for slug,data in sorted(hashes.items(),key=lambda x:len(x[1]['items']),reverse=True)[:12]:
        if len(data['items'])>=3:
            buckets['hash-'+slug]=data['items']
    labels={key:name for key,(name,_pattern) in TOPIC_RULES.items()}
    labels.update({'hash-'+slug:val['label'] for slug,val in hashes.items() if 'hash-'+slug in buckets})
    compact={};title={}
    for key,rows in buckets.items():
        ids=set(); unique=[]
        for v in sorted(rows,key=lambda v:(v.get('viewCount',0),v.get('publishedAt','')),reverse=True):
            vid=v.get('id')
            if vid not in ids:
                ids.add(vid);unique.append(public_record(v))
        if len(unique)>=2:
            compact[key]=unique[:50]
            title[key]=labels[key]
    return compact,title


def main():
    key=os.getenv('YOUTUBE_API_KEY','').strip()
    if not key:
        raise SystemExit('Missing YOUTUBE_API_KEY. Add GitHub repository Settings > Secrets > Actions.')
    try:old=json.loads(OUT.read_text('utf8'))
    except (OSError,json.JSONDecodeError):old={}
    old_regions=old.get('regions') if isinstance(old.get('regions'),dict) else {}
    old_shows=old.get('collections') if isinstance(old.get('collections'),dict) else {}
    regions={}; collections={}; refreshed_regions=[]; refreshed_shows=[]
    raw_regions={}
    for country in (*REGION_CODES,*LATIN_CODES):
        try:
            current=get_region(country,key)
            if not current:raise ValueError('empty music results')
            raw_regions[country]=[{**v,'market':('LAT' if country in LATIN_CODES else country),
                                   'country':country} for v in current]
            if country not in LATIN_CODES:
                regions[country]=raw_regions[country]
                refreshed_regions.append(country)
            print(country,'music video chart:',len(current))
        except (RuntimeError,ValueError) as exc:
            print('WARNING',country,type(exc).__name__,str(exc))
            if country not in LATIN_CODES:
                regions[country]=old_regions.get(country,[]) if isinstance(old_regions.get(country),list) else []
    latin_pools={x:raw_regions.get(x,[]) for x in LATIN_CODES}
    latin=[]; seen=set()
    for i in range(max([0]+[len(p) for p in latin_pools.values()])):
        for country,pool in latin_pools.items():
            if i <len(pool) and pool[i]['id'] not in seen:
                latin.append(pool[i]);seen.add(pool[i]['id'])
                if len(latin)>=50:break
        if len(latin)>=50:break
    if latin:
        regions['LAT']=latin;refreshed_regions.append('LAT')
    else:
        regions['LAT']=old_regions.get('LAT',[]) if isinstance(old_regions.get('LAT'),list) else []
    for show in SHOWS:
        slug=show['id']
        try:
            current=get_show(show,key)
            if not current:raise ValueError('no eligible official embeddable performances')
            collections[slug]=current;refreshed_shows.append(slug)
            print(show['label'],'performances:',len(current))
        except (RuntimeError,ValueError) as exc:
            print('WARNING',slug,type(exc).__name__,str(exc))
            collections[slug]=old_shows.get(slug,[]) if isinstance(old_shows.get(slug),list) else []
    if not refreshed_regions and not refreshed_shows:
        raise SystemExit('No new API results; published JSON left unchanged.')
    topics,topic_labels=hot_topics_from_charts(regions)
    if not topics and old.get('hotTopics'):
        topics=old.get('hotTopics',{});topic_labels=old.get('hotTopicLabels',{})
    stamp=TODAY.isoformat(timespec='seconds').replace('+00:00','Z')
    updated={
        'schemaVersion':3,
        'source':'YouTube Data API regional music mostPopular; Latin = MX/AR/CO selection; mixed feed not a global ranking',
        'isFallback':False,'updatedAt':stamp,
        'regionLabels':REGION_LABELS,
        'refreshedRegions':refreshed_regions,
        'refreshedCollections':refreshed_shows,
        'collectionLabels':{s['id']:s['label'] for s in SHOWS},
        'regions':{k:[public_record(v) for v in region] for k,region in regions.items()},
        'collections':{k:[public_record(v) for v in shows] for k,shows in collections.items()},
        'hotTopics':topics,'hotTopicLabels':topic_labels,
    }
    OUT.write_text(json.dumps(updated,ensure_ascii=False,indent=2)+'\n','utf8')
    print('Wrote',OUT.name,'schemaVersion=3 | refreshed charts:',refreshed_regions,
          '| shows:',len(refreshed_shows),'| live topics:',len(topics))


if __name__=='__main__':
    main()
