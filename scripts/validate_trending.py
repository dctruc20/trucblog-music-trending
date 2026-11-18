#!/usr/bin/env python3
"""Kiểm tra JSON Trending (không cần cài thư viện)."""
import json, re, sys
from pathlib import Path
p = Path(sys.argv[1]) if len(sys.argv)>1 else Path(__file__).resolve().parents[1]/'trending.json'
try: doc=json.loads(p.read_text(encoding='utf-8'))
except Exception as exc: raise SystemExit(f'JSON không đọc được: {exc}')
if doc.get('schemaVersion') != 4: raise SystemExit('Thiếu schemaVersion=4')
for key in ['regions','categories','categoryLabels','playlistsByGenre']:
    if not isinstance(doc.get(key),dict): raise SystemExit(f'Thiếu trường dạng object: {key}')
for region in ['VN','AU','US','GB']:
    if not isinstance(doc['regions'].get(region),list): raise SystemExit(f'Thiếu regions.{region}')
    if not isinstance(doc['categories'].get(region),dict): raise SystemExit(f'Thiếu categories.{region}')
    for item in doc['regions'][region]:
        if not isinstance(item,dict) or not re.fullmatch(r'[A-Za-z0-9_-]{11}',str(item.get('id',''))):
            raise SystemExit(f'ID video không hợp lệ ở vùng {region}')
for genre,playlists in doc['playlistsByGenre'].items():
    if not isinstance(playlists,list): raise SystemExit(f'playlistsByGenre.{genre} phải là array')
    for item in playlists:
        if not isinstance(item,dict) or not item.get('id') or not item.get('title'):
            raise SystemExit(f'Playlist không hợp lệ ở {genre}')
total=sum(len(v) for v in doc['regions'].values())
print(f'JSON hợp lệ: schema v4; {total} video phổ biến; '+
      f'{sum(len(v) for v in doc["playlistsByGenre"].values())} playlist; updatedAt={doc.get("updatedAt") or "chưa cập nhật"}')
