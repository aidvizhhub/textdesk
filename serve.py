#!/usr/bin/env python3
"""статический сервер по папке + запись правок из страницы (Ctrl+S) в файл.
запуск: python3 serve.py [порт] [корень]
корень по умолчанию — на два уровня выше папки приложения (удобно, когда проект лежит в подпапке рабочей директории); можно передать явно вторым аргументом.
на запись: только .txt/.md/.log внутри корня, только с этого же origin
(заголовок Origin, если он есть, обязан совпасть с адресом сервера), тело до 32 МБ.
страница сама пишет в выбранный файл, кнопка «сохранить»/Ctrl+S шлёт
POST /__save?file=... ; список файлов отдаёт /__list и обновляет его на каждом
запросе, так что новые файлы видны без перезапуска."""
import http.server
import json
import os
import pathlib
import sys
import tempfile
import urllib.parse
import webbrowser

HERE = pathlib.Path(__file__).resolve().parent
PAGE_FILE = HERE / 'index.html'
VENDORED = ('/hljs.min.js', '/mdit.min.js')
NO_BROWSER = '--no-browser' in sys.argv[1:]
ARGS = [a for a in sys.argv[1:] if a != '--no-browser']
PORT = int(ARGS[0]) if len(ARGS) > 0 else 8792
ROOT = pathlib.Path(ARGS[1]).resolve() if len(ARGS) > 1 else (HERE.parent.parent if HERE.parent.parent.exists() else HERE.parent)
ALLOWED_NAMES = {'Dockerfile', 'Makefile', 'makefile', 'GNUmakefile', '.gitignore', '.dockerignore', '.editorconfig', '.env', '.bashrc', '.zshrc', '.vimrc'}
ALLOWED_EXT = ('.txt', '.md', '.log', '.py', '.sh', '.bash', '.zsh', '.js', '.mjs', '.cjs',
               '.ts', '.tsx', '.jsx', '.json', '.yml', '.yaml', '.toml', '.ini', '.cfg', '.conf',
               '.env', '.sql', '.html', '.htm', '.css', '.scss', '.xml', '.csv', '.tsv',
               '.c', '.h', '.cc', '.cpp', '.hpp', '.go', '.rs', '.java', '.kt', '.rb', '.php',
               '.lua', '.pl', '.service', '.desktop', '.diff', '.patch')
MAX_BODY = 32 * 1024 * 1024
MAX_VIEW = 2 * 1024 * 1024
SKIP_DIRS = ('/proc', '/sys', '/dev')
OK_ORIGINS = {'http://127.0.0.1:%d' % PORT, 'http://localhost:%d' % PORT}


def scan_files():
    found = []
    for dirpath, dirnames, filenames in os.walk(ROOT):
        rel = pathlib.Path(dirpath).relative_to(ROOT)
        dirnames[:] = [d for d in dirnames if not d.startswith('.') and len(rel.parts) < 2]
        for f in filenames:
            if (not f.startswith('.') or f in ALLOWED_NAMES) and (pathlib.Path(f).suffix.lower() in ALLOWED_EXT or f in ALLOWED_NAMES):
                found.append((pathlib.Path(dirpath) / f).relative_to(ROOT).as_posix())
    return sorted(found)


class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=str(ROOT), **kw)

    def do_GET(self):
        path = self.path.split('?')[0]
        if path in ('/', '/index.html'):
            try:
                data = PAGE_FILE.read_bytes()
            except OSError:
                self.send_error(500, 'no index.html next to serve.py')
                return
            self.send_response(200)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.send_header('Content-Length', str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return
        if path == '/__file':
            q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query).get('path') or ['']
            t = pathlib.Path(urllib.parse.unquote(q[0])).resolve()
            if not t.is_absolute() or not t.is_file():
                self.send_error(404)
                return
            if t.suffix.lower() not in ALLOWED_EXT and t.name not in ALLOWED_NAMES:
                self.send_error(415)
                return
            try:
                data = t.read_bytes()
            except OSError:
                self.send_error(500)
                return
            if len(data) > MAX_VIEW:
                self.send_error(413)
                return
            try:
                data.decode('utf-8')
            except UnicodeDecodeError:
                self.send_error(415)
                return
            self.send_response(200)
            self.send_header('Content-Type', 'text/plain; charset=utf-8')
            self.send_header('Content-Length', str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return
        if path == '/__dir':
            q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query).get('path') or ['']
            target = pathlib.Path(urllib.parse.unquote(q[0])).resolve()
            if any(str(target) == d or str(target).startswith(d + '/') for d in SKIP_DIRS):
                self.send_error(403)
                return
            if not target.is_dir():
                self.send_error(404)
                return
            dirs, files = [], []
            try:
                for entry in sorted(target.iterdir(), key=lambda e: e.name.lower()):
                    if entry.name.startswith('.'):
                        continue
                    try:
                        if entry.is_dir():
                            dirs.append(str(entry))
                        elif entry.suffix.lower() in ALLOWED_EXT or entry.name in ALLOWED_NAMES:
                            files.append(str(entry))
                    except OSError:
                        continue
            except OSError:
                self.send_error(403)
                return
            body = json.dumps({
                'dir': str(target),
                'parent': None if str(target) == '/' else str(target.parent),
                'dirs': dirs[:2000],
                'files': files[:2000],
            }, ensure_ascii=False).encode('utf-8')
            self.send_response(200)
            self.send_header('Content-Type', 'application/json; charset=utf-8')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if path in VENDORED:
            try:
                data = (PAGE_FILE.parent / path.lstrip('/')).read_bytes()
            except OSError:
                self.send_error(404)
                return
            self.send_response(200)
            self.send_header('Content-Type', 'application/javascript; charset=utf-8')
            self.send_header('Content-Length', str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return
        if path == '/__grep':
            qs = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            q = (qs.get('q') or [''])[0].strip()
            cs = (qs.get('case') or ['0'])[0] == '1'
            if len(q) < 2:
                self.send_error(400, 'need at least 2 chars')
                return
            needle = q if cs else q.lower()
            files_out, hits_total, truncated = [], 0, False
            scanned = 0
            for rel in scan_files():
                p = ROOT / rel
                try:
                    if p.stat().st_size > MAX_VIEW:
                        continue
                    data = p.read_text(encoding='utf-8')
                except (OSError, UnicodeDecodeError):
                    continue
                scanned += 1
                found = []
                for i, line in enumerate(data.split('\n'), 1):
                    hay = line if cs else line.lower()
                    pos = hay.find(needle)
                    if pos < 0:
                        continue
                    found.append({'line': i, 'col': pos + 1, 'text': line.strip()[:160]})
                    if len(found) >= 8:
                        truncated = True
                        break
                if not found:
                    continue
                files_out.append({'file': rel, 'hits': found})
                hits_total += len(found)
                if hits_total >= 120 or len(files_out) >= 40:
                    truncated = True
                    break
            body = json.dumps({'q': q, 'case': cs, 'files': files_out, 'files_total': len(files_out),
                               'hits_total': hits_total, 'truncated': truncated, 'scanned': scanned}, ensure_ascii=False).encode('utf-8')
            self.send_response(200)
            self.send_header('Content-Type', 'application/json; charset=utf-8')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if path == '/__list':
            files = scan_files()
            body = json.dumps({'root': str(ROOT), 'files': files}, ensure_ascii=False).encode('utf-8')
            self.send_response(200)
            self.send_header('Content-Type', 'application/json; charset=utf-8')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if path == '/__tree':
            rel = (urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query).get('dir') or [''])[0]
            target = (ROOT / urllib.parse.unquote(rel)).resolve()
            if target != ROOT and ROOT not in target.parents:
                self.send_error(403)
                return
            if not target.is_dir():
                self.send_error(404)
                return
            dirs, files = [], []
            try:
                for entry in sorted(target.iterdir(), key=lambda e: e.name.lower()):
                    if entry.name.startswith('.'):
                        continue
                    if entry.is_dir():
                        dirs.append(entry.relative_to(ROOT).as_posix())
                    elif entry.suffix.lower() in ALLOWED_EXT and (not entry.name.startswith('.') or entry.name in ALLOWED_NAMES) or entry.name in ALLOWED_NAMES:
                        files.append(entry.relative_to(ROOT).as_posix())
            except OSError:
                self.send_error(500)
                return
            body = json.dumps({
                'dir': '' if target == ROOT else target.relative_to(ROOT).as_posix(),
                'parent': None if target == ROOT else ('' if target.parent == ROOT else target.parent.relative_to(ROOT).as_posix()),
                'dirs': dirs,
                'files': files,
            }, ensure_ascii=False).encode('utf-8')
            self.send_response(200)
            self.send_header('Content-Type', 'application/json; charset=utf-8')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        super().do_GET()

    def end_headers(self):
        self.send_header('Cache-Control', 'no-store')
        super().end_headers()

    def do_POST(self):
        url = urllib.parse.urlparse(self.path)
        if url.path != '/__save':
            self.send_error(404)
            return
        origin = self.headers.get('Origin')
        if origin and origin not in OK_ORIGINS:
            self.send_error(403)
            return
        rel = (urllib.parse.parse_qs(url.query).get('file') or [''])[0]
        target = (ROOT / urllib.parse.unquote(rel)).resolve()
        if not rel or (target != ROOT and ROOT not in target.parents):
            self.send_error(403)
            return
        if target.suffix.lower() not in ALLOWED_EXT and target.name not in ALLOWED_NAMES:
            self.send_error(403)
            return
        length = int(self.headers.get('Content-Length') or 0)
        if length > MAX_BODY:
            self.send_error(413)
            return
        data = self.rfile.read(length)
        tmp = None
        try:
            fd, tmp = tempfile.mkstemp(dir=str(target.parent), prefix='.' + target.name + '.', suffix='.tmp')
            with os.fdopen(fd, 'wb') as f:
                f.write(data)
                f.flush()
                os.fsync(f.fileno())
            st = None
            try:
                st = target.stat()
            except OSError:
                pass
            if st:
                os.chmod(tmp, st.st_mode & 0o7777)
                try:
                    os.chown(tmp, st.st_uid, st.st_gid)
                except OSError:
                    pass
            os.replace(tmp, target)
        except OSError:
            if tmp:
                try:
                    os.unlink(tmp)
                except OSError:
                    pass
            self.send_error(500)
            return
        print('saved %s (%d байт)' % (target, len(data)))
        self.send_response(204)
        self.end_headers()


print('корень: %s (%d файлов)' % (ROOT, len(scan_files())), flush=True)
url = 'http://127.0.0.1:%d/' % PORT
print('страница: %s — файл выбирай кнопкой «открыть файл…»' % url, flush=True)
server = http.server.ThreadingHTTPServer(('127.0.0.1', PORT), Handler)
if not NO_BROWSER:
    try:
        webbrowser.open(url)
    except Exception:
        pass
server.serve_forever()
