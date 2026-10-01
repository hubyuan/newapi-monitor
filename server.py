#!/usr/bin/env python3
"""
NewAPI Group Monitor — 分组监控代理服务

读取 NewAPI 管理 API，聚合分组级别的成功率、首字时间（FRT）和请求趋势，
通过只读 Web 界面展示。管理员 Token 隐藏在服务端，前端无需鉴权。

用法:
  export NEWAPI_BASE_URL=http://127.0.0.1:3000
  export NEWAPI_TOKEN=sk-xxxxx
  python3 server.py [--port 8898]

环境变量:
  NEWAPI_BASE_URL  NewAPI 服务地址（必填）
  NEWAPI_TOKEN     管理员 API Token（必填）
  LOG_LIMIT        每分组拉取日志条数，默认 400
  CACHE_TTL        统计缓存秒数，默认 120
  EXCLUDE_GROUPS   排除的分组，逗号分隔
"""
import argparse
import http.server
import json
import os
import sys
import threading
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
HTML_FILE = os.path.join(SCRIPT_DIR, 'index.html')

BASE_URL = os.environ.get('NEWAPI_BASE_URL', '').rstrip('/')
TOKEN = os.environ.get('NEWAPI_TOKEN', '')
LOG_LIMIT = int(os.environ.get('LOG_LIMIT', '400'))
CACHE_TTL = int(os.environ.get('CACHE_TTL', '120'))
EXCLUDE_GROUPS = set(g.strip() for g in os.environ.get('EXCLUDE_GROUPS', '').split(',') if g.strip())

SAFE_CHANNEL_FIELDS = {
    'id', 'name', 'group', 'status', 'priority', 'weight',
    'test_time', 'response_time', 'models', 'auto_ban', 'type',
}

_cache_lock = threading.Lock()
_cache = {'stats': None, 'stats_at': 0, 'channels': None, 'channels_at': 0}


def _api(path):
    req = urllib.request.Request(
        f'{BASE_URL}{path}',
        headers={'Authorization': f'Bearer {TOKEN}',
                 'Content-Type': 'application/json'})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read())


def _get_channels():
    with _cache_lock:
        if _cache['channels'] and time.time() - _cache['channels_at'] < CACHE_TTL:
            return _cache['channels']
    try:
        data = _api('/api/channel/?p=0&page_size=500')
        channels = data.get('data', {}).get('items', [])
    except Exception:
        channels = []
    with _cache_lock:
        _cache['channels'] = channels
        _cache['channels_at'] = time.time()
    return channels


def _build_stats():
    with _cache_lock:
        if _cache['stats'] and time.time() - _cache['stats_at'] < CACHE_TTL:
            return _cache['stats']

    now = int(time.time())
    channels = _get_channels()

    all_groups = set()
    for ch in channels:
        for g in (ch.get('group') or '').split(','):
            g = g.strip()
            if g and g not in EXCLUDE_GROUPS:
                all_groups.add(g)

    def _fetch_group(group):
        gq = urllib.parse.quote(group)
        try:
            data = _api(f'/api/log/?p=0&page_size={LOG_LIMIT}&group={gq}')
            items = data.get('data', {}).get('items', [])
        except Exception:
            items = []

        success = 0
        fail = 0
        sum_time = 0
        time_count = 0
        earliest = None
        entries = []

        for item in items:
            t = item.get('type', 0)
            ts = item.get('created_at', 0)
            frt = 0
            if t == 2:
                success += 1
                try:
                    other = json.loads(item.get('other') or '{}')
                    frt_ms = other.get('frt') or 0
                    frt = round(frt_ms / 1000, 2) if frt_ms > 0 else 0
                except Exception:
                    pass
                if frt > 0:
                    sum_time += frt
                    time_count += 1
                entries.append([ts, 1, frt])
            elif t == 5:
                fail += 1
                entries.append([ts, 0, 0])
            if ts and (earliest is None or ts < earliest):
                earliest = ts

        entries.sort(key=lambda x: x[0])

        total = success + fail
        span = (now - earliest) if earliest else None

        if total > 0:
            return group, {
                'success': success,
                'fail': fail,
                'rate': round(success / total * 100, 1),
                'avg_time': round(sum_time / time_count, 2) if time_count else None,
                'span': span,
                'total_reqs': total,
                'entries': entries,
            }
        return group, None

    result = {}
    with ThreadPoolExecutor(max_workers=4) as pool:
        for group, stats in pool.map(_fetch_group, sorted(all_groups)):
            if stats:
                result[group] = stats

    with _cache_lock:
        _cache['stats'] = result
        _cache['stats_at'] = time.time()
    return result


class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        if '404' not in (fmt % args):
            ts = time.strftime('%H:%M:%S')
            sys.stderr.write(f'[{ts}] {fmt % args}\n')

    def _json(self, data, code=200, cache=0):
        body = json.dumps(data, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        if cache > 0:
            self.send_header('Cache-Control', f'public, max-age=0, s-maxage={cache}')
        else:
            self.send_header('Cache-Control', 'no-cache')
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self.send_response(204)
        self.end_headers()

    def do_HEAD(self):
        self.do_GET()

    def do_GET(self):
        path = self.path.split('?', 1)[0]
        try:
            if path in ('/', '/index.html'):
                with open(HTML_FILE, 'rb') as f:
                    content = f.read()
                self.send_response(200)
                self.send_header('Content-Type', 'text/html; charset=utf-8')
                self.send_header('Cache-Control', 'no-cache')
                self.end_headers()
                self.wfile.write(content)
            elif path == '/data/channels':
                items = _get_channels()
                safe = []
                for ch in items:
                    groups = [g.strip() for g in (ch.get('group') or '').split(',') if g.strip()]
                    visible = [g for g in groups if g not in EXCLUDE_GROUPS]
                    if not visible:
                        continue
                    row = {k: v for k, v in ch.items() if k in SAFE_CHANNEL_FIELDS}
                    row['group'] = ','.join(visible)
                    safe.append(row)
                self._json({'channels': safe}, cache=30)
            elif path == '/data/stats':
                self._json({'stats': _build_stats()}, cache=30)
            else:
                self.send_error(404)
        except Exception as e:
            self._json({'error': str(e)}, 502)


def main():
    parser = argparse.ArgumentParser(description='NewAPI Group Monitor')
    parser.add_argument('--port', '-p', type=int, default=int(os.environ.get('PORT', '8898')))
    args = parser.parse_args()

    if not BASE_URL:
        print('错误: 请设置环境变量 NEWAPI_BASE_URL', file=sys.stderr)
        sys.exit(1)
    if not TOKEN:
        print('错误: 请设置环境变量 NEWAPI_TOKEN', file=sys.stderr)
        sys.exit(1)

    srv = http.server.ThreadingHTTPServer(('0.0.0.0', args.port), Handler)
    print(f'NewAPI Group Monitor 已启动: http://0.0.0.0:{args.port}')
    print(f'  API: {BASE_URL}')
    print(f'  日志条数: {LOG_LIMIT}  缓存: {CACHE_TTL}s')
    if EXCLUDE_GROUPS:
        print(f'  排除分组: {", ".join(sorted(EXCLUDE_GROUPS))}')
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print('\n已停止')
        srv.server_close()


if __name__ == '__main__':
    main()
