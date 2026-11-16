# -*- coding: utf-8 -*-
"""
研报阅读工作台 · 本地服务
=========================
- 端口 8765，仅绑定本机 127.0.0.1，启动后自动打开浏览器
- reports/  下放研报 PDF（按 机构/分类 归文件夹）
- summaries/ 放同名镜像的 AI 精读总结 HTML（reports/X/Y/xxx.pdf ↔ summaries/X/Y/xxx.html）
- 接口：
    GET /                工作台 UI（static/index.html）
    GET /api/library     分类树（带计数）+ 研报列表
    GET /api/search      全文搜索（PDF 文本由 PyMuPDF 提取，缓存于 .index/；同时搜索标题与总结页）
    GET /files/...       静态文件（PDF 内嵌阅读 / 总结页）
- 依赖：标准库即可运行；PyMuPDF 可选（缺失时自动降级为仅搜标题/文件名）
"""
import datetime as _dt
import hashlib
import json
import os
import re
import sys
import threading
import webbrowser
from collections import defaultdict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs, unquote

# ---------------- 配置 ----------------
BASE = os.path.dirname(os.path.abspath(__file__))
REPORTS_DIR = os.path.join(BASE, 'reports')
SUMMARIES_DIR = os.path.join(BASE, 'summaries')
INDEX_DIR = os.path.join(BASE, '.index')
STATIC_DIR = os.path.join(BASE, 'static')
HOST = '127.0.0.1'
PORT = 8765

# 机构展示顺序（用户自建的新机构文件夹会追加在后）
ORGS = ['Platts', 'FGE', 'Energy Aspects', 'Kpler', 'JPM', 'Morgan Stanley', 'GS']
# 机构固定分类树（即使为空也显示）；不在预设里的机构，其任意子文件夹自动识别为子分类
ORG_PRESETS = {
    'Platts': [
        ('Daily', ['原油', '汽油柴油', '石脑油', '燃料油其它']),
        ('Weekly', None),
        ('Monthly', None),
    ],
    'Energy Aspects': [
        ('Insights', ['Crude Oil', 'Dirty Freight']),
        ('Weekly Updates', ['Perspectives', 'US Oil Weekly', 'Weekly Arbs Update', 'Dirty Freight']),
        ('Monthly Outlooks', ['Canada', 'China', 'Geopolitics', 'Fundamentals',
                              'North America', 'Sour Crude', 'Sweet Crude']),
    ],
    'Kpler': [
        ('Insight', None),
        ('Others', ['原油', '成品油', '燃料油', '其它']),
    ],
}

try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

# ---------------- 日期解析 ----------------
_MONTHS = {'jan': 1, 'feb': 2, 'mar': 3, 'apr': 4, 'may': 5, 'jun': 6,
           'jul': 7, 'aug': 8, 'sep': 9, 'oct': 10, 'nov': 11, 'dec': 12}


def _safe_date(y, m, d):
    try:
        return _dt.date(int(y), int(m), int(d)).isoformat()
    except (ValueError, TypeError):
        return None


def parse_date(name, mtime):
    """从文件名解析日期，失败回退文件修改时间。返回 (iso_date, 命中span 或 None)"""
    # 2026-11-14 / 2026_11_14 / 2026.11.14
    m = re.search(r'\d{4}[-_.]\d{1,2}[-_.]\d{1,2}', name)
    if m:
        p = re.split(r'[-_.]', m.group(0))
        d = _safe_date(p[0], p[1], p[2])
        if d:
            return d, m.span()
    # 20261114（前后不能紧邻数字，避免误吃长数字串）
    m = re.search(r'(?<!\d)(20\d{2})(0[1-9]|1[0-2])(0[1-9]|[12]\d|3[01])(?!\d)', name)
    if m:
        d = _safe_date(m.group(1), m.group(2), m.group(3))
        if d:
            return d, m.span()
    # 14 Nov 2026 / Nov 14, 2026 / Nov-14-26 / 2026 Nov 14（月份缩写必须能对上才认）
    m = re.search(r'(?i)(?:(20\d{2})[-_. ]?)?([a-z]{3})[-_. ]?(\d{1,2})(?:[-_. ,]?(\d{2,4}))?', name)
    if m:
        mon = _MONTHS.get(m.group(2).lower())
        if mon and 1 <= int(m.group(3)) <= 31:
            y = m.group(1)
            if not y and m.group(4):
                yy = m.group(4)
                y = ('20' + yy) if len(yy) == 2 else yy
            if not y:
                y = _dt.date.fromtimestamp(mtime).year
            d = _safe_date(y, mon, m.group(3))
            if d:
                return d, m.span()
    return _dt.date.fromtimestamp(mtime).isoformat(), None


def clean_title(name, span):
    """文件名 → 展示标题：去扩展名、去日期段、下划线转空格"""
    stem = os.path.splitext(name)[0]
    if span:
        s, e = span
        stem = stem[:s] + ' ' + stem[e:]
    stem = stem.replace('_', ' ')
    stem = re.sub(r'\s+', ' ', stem).strip(' -–—.·#')
    return stem or os.path.splitext(name)[0]


# ---------------- 扫描 ----------------
def scan_reports():
    """递归扫描 reports/ + summaries/，返回研报条目列表。
    - PDF 条目：hasSummary 由同名镜像自动发现
    - 孤立总结页（无对应 PDF）：pdfMissing=True，作为「仅总结」条目展示 """
    items = []
    seen_summary_rels = set()
    if os.path.isdir(REPORTS_DIR):
        for root, dirs, files in os.walk(REPORTS_DIR):
            dirs.sort()
            for fn in sorted(files):
                if not fn.lower().endswith('.pdf'):
                    continue
                full = os.path.join(root, fn)
                try:
                    st = os.stat(full)
                except OSError:
                    continue
                rel_to_reports = os.path.relpath(full, REPORTS_DIR).replace('\\', '/')
                parts = rel_to_reports.split('/')
                org = parts[0]
                category = '/'.join(parts[1:-1])  # 直接放机构目录下则为 ''
                date_iso, span = parse_date(fn, st.st_mtime)
                summary_rel = 'summaries/' + '/'.join(parts[:-1] + [parts[-1][:-4] + '.html'])
                seen_summary_rels.add(summary_rel)
                items.append({
                    'rel': 'reports/' + rel_to_reports,
                    'name': fn,
                    'title': clean_title(fn, span),
                    'date': date_iso,
                    'org': org,
                    'category': category,
                    'size': st.st_size,
                    'mtime': int(st.st_mtime),
                    'hasSummary': os.path.exists(os.path.join(BASE, summary_rel)),
                    'pdfMissing': False,
                })
    # 孤立总结页：只有总结、没有对应 PDF —— 也展示为「仅总结」条目
    if os.path.isdir(SUMMARIES_DIR):
        for root, dirs, files in os.walk(SUMMARIES_DIR):
            dirs.sort()
            for fn in sorted(files):
                if not fn.lower().endswith('.html'):
                    continue
                full = os.path.join(root, fn)
                try:
                    st = os.stat(full)
                except OSError:
                    continue
                summary_rel = 'summaries/' + os.path.relpath(full, SUMMARIES_DIR).replace('\\', '/')
                if summary_rel in seen_summary_rels:
                    continue
                parts = summary_rel.split('/')
                org = parts[1]
                category = '/'.join(parts[2:-1])
                date_iso, span = parse_date(fn, st.st_mtime)
                items.append({
                    'rel': summary_rel,
                    'name': fn,
                    'title': clean_title(fn, span),
                    'date': date_iso,
                    'org': org,
                    'category': category,
                    'size': st.st_size,
                    'mtime': int(st.st_mtime),
                    'hasSummary': True,
                    'pdfMissing': True,
                })
    return items


# ---------------- 分类树 ----------------
def _cat_node(org, cat, cat_count, preset=None):
    """构建分类节点。
    preset: [(label, sub)]，sub 为 None 或 [子类label列表]（仅 Platts 预设树用）
    cat 为 '' 表示机构根节点。计数含全部子树（扫描时已按前缀累加）。"""
    node = {
        'label': cat.split('/')[-1], 'org': org, 'cat': cat,
        'count': cat_count.get((org, cat), 0),
        'children': [],
    }
    prefix = cat + '/' if cat else ''
    existing = set()
    if preset:
        for label_p, sub in preset:
            sub_cat = cat + '/' + label_p if cat else label_p
            child_preset = [(s, None) for s in sub] if sub else None
            child = _cat_node(org, sub_cat, cat_count, child_preset)
            child['label'] = label_p
            node['children'].append(child)
            existing.add(sub_cat)
    # 实际存在但预设之外的子分类（按字母序追加）
    extra = set()
    for (o, c) in cat_count:
        if o == org and c.startswith(prefix) and c != cat:
            rest = c[len(prefix):]
            first = (cat + '/' + rest.split('/')[0]) if cat else rest.split('/')[0]
            if first not in existing:
                extra.add(first)
    for full in sorted(extra):
        node['children'].append(_cat_node(org, full, cat_count, None))
    return node


def build_tree(items):
    org_count = defaultdict(int)
    cat_count = defaultdict(int)
    for it in items:
        org_count[it['org']] += 1
        if it['category']:
            segs = it['category'].split('/')
            for i in range(1, len(segs) + 1):
                cat_count[(it['org'], '/'.join(segs[:i]))] += 1
    orgs = list(ORGS)
    for it in items:
        if it['org'] not in orgs:
            orgs.append(it['org'])
    tree = []
    for o in orgs:
        preset = ORG_PRESETS.get(o)
        node = _cat_node(o, '', cat_count, preset)
        node['label'] = o
        node['count'] = org_count.get(o, 0)
        tree.append(node)
    return tree


# ---------------- 文本提取（PyMuPDF，带缓存） ----------------
_fitz = None
_fitz_failed = False
_index_lock = threading.Lock()


def _get_fitz():
    global _fitz, _fitz_failed
    if _fitz is None and not _fitz_failed:
        try:
            import fitz  # PyMuPDF
            _fitz = fitz
        except Exception:
            _fitz_failed = True
            print('[提示] 未安装 PyMuPDF，全文搜索降级为仅搜标题/分类/总结文本')
    return _fitz


def _cache_path(rel):
    h = hashlib.md5(rel.encode('utf-8')).hexdigest()[:16]
    return os.path.join(INDEX_DIR, h + '.txt')


def _read_cache(cp, st):
    try:
        with open(cp, encoding='utf-8') as f:
            head = f.readline().strip()
            body = f.read()
        h = json.loads(head)
        if h.get('m') == int(st.st_mtime) and h.get('s') == st.st_size:
            return body
    except Exception:
        pass
    return None


def extract_pdf_text(abs_path, rel):
    cp = _cache_path(rel)
    try:
        st = os.stat(abs_path)
    except OSError:
        return ''
    cached = _read_cache(cp, st)
    if cached is not None:
        return cached
    with _index_lock:
        cached = _read_cache(cp, st)  # 双检：等锁期间可能已被别的线程提取
        if cached is not None:
            return cached
        fitz = _get_fitz()
        if fitz is None:
            return ''
        try:
            doc = fitz.open(abs_path)
            out = '\n'.join(page.get_text() for page in doc)
            doc.close()
        except Exception:
            return ''
        try:
            os.makedirs(INDEX_DIR, exist_ok=True)
            with open(cp, 'w', encoding='utf-8') as f:
                f.write(json.dumps({'m': int(st.st_mtime), 's': st.st_size}) + '\n')
                f.write(out)
        except Exception:
            pass
        return out


def extract_html_text(abs_path, rel):
    """总结页 HTML → 纯文本（同样走 mtime 缓存）"""
    cp = _cache_path(rel)
    try:
        st = os.stat(abs_path)
    except OSError:
        return ''
    cached = _read_cache(cp, st)
    if cached is not None:
        return cached
    with _index_lock:
        cached = _read_cache(cp, st)
        if cached is not None:
            return cached
        try:
            import html as _html
            with open(abs_path, encoding='utf-8', errors='replace') as f:
                raw = f.read()
            raw = re.sub(r'<(script|style)[^>]*>.*?</\1>', ' ', raw, flags=re.S | re.I)
            out = _html.unescape(re.sub(r'<[^>]+>', ' ', raw))
            out = re.sub(r'[ \t\r]+', ' ', out)
            out = re.sub(r'\n\s*\n+', '\n', out)
        except Exception:
            return ''
        try:
            os.makedirs(INDEX_DIR, exist_ok=True)
            with open(cp, 'w', encoding='utf-8') as f:
                f.write(json.dumps({'m': int(st.st_mtime), 's': st.st_size}) + '\n')
                f.write(out)
        except Exception:
            pass
        return out


# ---------------- 搜索 ----------------
def _snippet(text, pos, width=110, context=70):
    start = max(0, pos - context)
    end = min(len(text), pos + width)
    frag = text[start:end].replace('\n', ' ')
    frag = re.sub(r'\s+', ' ', frag).strip()
    return {'snippet': ('…' if start > 0 else '') + frag + ('…' if end < len(text) else ''),
            'offset': pos - start + (3 if start > 0 else 0)}


def do_search(q, org=None, dfrom=None, dto=None):
    q = (q or '').strip()
    ql = q.lower()
    results = []
    for it in scan_reports():
        if org and it['org'] != org:
            continue
        if dfrom and it['date'] < dfrom:
            continue
        if dto and it['date'] > dto:
            continue
        entry = dict(it)
        # 1) 标题 / 机构 / 分类命中
        hay = ' '.join([it['title'], it['org'], it['category']]).lower()
        pos = hay.find(ql)
        if pos >= 0:
            entry.update({'matchIn': 'meta', 'snippet': it['title'], 'offset': -1, 'rank': 0})
            results.append(entry)
            continue
        # 2) 总结页文本命中
        done = False
        if it['hasSummary']:
            if it['rel'].startswith('reports/'):
                s_rel = it['rel'].replace('reports/', 'summaries/', 1)[:-4] + '.html'
            else:
                s_rel = it['rel']  # 仅总结条目，rel 本身就是 summaries/xxx.html
            stext = extract_html_text(os.path.join(BASE, s_rel), s_rel)
            pos = stext.lower().find(ql)
            if pos >= 0:
                sn = _snippet(stext, pos)
                entry.update({'matchIn': 'summary', 'snippet': sn['snippet'],
                              'offset': sn['offset'], 'rank': 1})
                results.append(entry)
                done = True
        # 3) PDF 全文命中（仅总结条目无 PDF，跳过）
        if not done and not it.get('pdfMissing'):
            ftext = extract_pdf_text(os.path.join(BASE, it['rel']), it['rel'])
            if ftext:
                pos = ftext.lower().find(ql)
                if pos >= 0:
                    sn = _snippet(ftext, pos)
                    entry.update({'matchIn': 'fulltext', 'snippet': sn['snippet'],
                                  'offset': sn['offset'], 'rank': 2})
                    results.append(entry)
    results.sort(key=lambda e: (e['rank'], -e['mtime']))
    return {'q': q, 'count': len(results), 'results': results}


# ---------------- HTTP ----------------
_CTYPES = {
    '.pdf': 'application/pdf', '.html': 'text/html; charset=utf-8',
    '.htm': 'text/html; charset=utf-8', '.txt': 'text/plain; charset=utf-8',
    '.png': 'image/png', '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg',
    '.gif': 'image/gif', '.svg': 'image/svg+xml', '.json': 'application/json; charset=utf-8',
    '.css': 'text/css; charset=utf-8', '.js': 'text/javascript; charset=utf-8',
}


class Handler(BaseHTTPRequestHandler):
    server_version = 'ReportDesk/1.0'

    def log_message(self, fmt, *args):
        try:
            sys.stdout.write('[req] ' + (fmt % args)[:110] + '\n')
            sys.stdout.flush()
        except Exception:
            pass

    def _send_bytes(self, code, body, ctype):
        self.send_response(code)
        self.send_header('Content-Type', ctype)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        self.wfile.write(body)

    def _json(self, obj, code=200):
        self._send_bytes(code, json.dumps(obj, ensure_ascii=False).encode('utf-8'),
                         'application/json; charset=utf-8')

    def _serve_static_file(self, rel_under_base):
        rel = rel_under_base.replace('\\', '/')
        if '..' in rel.split('/'):
            return self._json({'error': 'bad path'}, 400)
        root_map = None
        if rel.startswith('reports/'):
            root_map = REPORTS_DIR
        elif rel.startswith('summaries/'):
            root_map = SUMMARIES_DIR
        elif rel.startswith('static/'):
            root_map = STATIC_DIR
        if root_map is None:
            return self._json({'error': 'not found'}, 404)
        abs_path = os.path.normpath(os.path.join(BASE, rel))
        root = os.path.normpath(root_map)
        if not abs_path.startswith(root + os.sep):
            return self._json({'error': 'forbidden'}, 403)
        if not os.path.isfile(abs_path):
            return self._json({'error': 'not found'}, 404)
        ext = os.path.splitext(abs_path)[1].lower()
        ctype = _CTYPES.get(ext, 'application/octet-stream')
        try:
            with open(abs_path, 'rb') as f:
                body = f.read()
        except OSError:
            return self._json({'error': 'read failed'}, 500)
        self._send_bytes(200, body, ctype)

    def do_GET(self):
        parsed = urlparse(self.path)
        path = unquote(parsed.path)
        qs = parse_qs(parsed.query or '')
        try:
            if path in ('/', '/index.html'):
                return self._serve_static_file('static/index.html')
            if path == '/api/library':
                items = scan_reports()
                return self._json({'total': len(items), 'reports': items,
                                   'tree': build_tree(items)})
            if path == '/api/search':
                return self._json(do_search(
                    (qs.get('q') or [''])[0],
                    org=(qs.get('org') or [None])[0],
                    dfrom=(qs.get('from') or [None])[0],
                    dto=(qs.get('to') or [None])[0],
                ))
            if path.startswith('/files/'):
                return self._serve_static_file(path[len('/files/'):])
            if path == '/favicon.ico':
                return self._send_bytes(204, b'', 'image/x-icon')
            return self._json({'error': 'not found'}, 404)
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception as e:
            try:
                self._json({'error': str(e)}, 500)
            except Exception:
                pass


def main():
    no_browser = '--no-browser' in sys.argv
    url = 'http://127.0.0.1:%d/' % PORT
    try:
        srv = ThreadingHTTPServer((HOST, PORT), Handler)
    except OSError:
        print('端口 %d 已被占用 —— 工作台可能已在运行。' % PORT)
        if not no_browser:
            webbrowser.open(url)
        return
    srv.daemon_threads = True
    print('=' * 52)
    print('  研报阅读工作台已启动')
    print('  地址      : %s' % url)
    print('  研报目录  : %s' % REPORTS_DIR)
    print('  总结目录  : %s' % SUMMARIES_DIR)
    print('  使用方式  : 把 PDF 放入 reports/ 对应机构文件夹，')
    print('              回到浏览器点「刷新」即可；关闭本窗口即停止服务')
    print('=' * 52)
    if not no_browser:
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print('\n服务已停止。')


if __name__ == '__main__':
    main()
