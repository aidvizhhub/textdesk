#!/usr/bin/env python3
"""дымовой тест вьюхи и serve.py (playwright + системный chrome).
запуск: python3 test_viewer.py — поднимает сервер на временном корне, гоняет
проверки (холст, загрузка, зеркало строк, тема, шрифт, сохранение, диалог
затирания, кнопка открытия, память) и отдельно file:// без сервера.
код 0 — всё зелёное."""
import os
import pathlib
import shutil
import socket
import subprocess
import struct
import sys
import tempfile
import time
import zlib
import urllib.request

import json
import re

from playwright.sync_api import sync_playwright

HERE = pathlib.Path(__file__).resolve().parent
FAILED = []


def check(name, cond, info=''):
    print(('OK   ' if cond else 'FAIL ') + name + ((' — ' + info) if info else ''), flush=True)
    if not cond:
        FAILED.append(name)


def png_bytes(w, h):
    """валидный png без внешних файлов и библиотек"""
    def chunk(t, d):
        c = t + d
        return struct.pack('>I', len(d)) + c + struct.pack('>I', zlib.crc32(c) & 0xffffffff)
    raw = bytearray()
    for y in range(h):
        raw.append(0)
        for x in range(w):
            raw += bytes(((x * 37) % 256, (y * 53) % 256, 160))
    return (b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', w, h, 8, 2, 0, 0, 0))
            + chunk(b'IDAT', zlib.compress(bytes(raw), 6)) + chunk(b'IEND', b''))


def free_port():
    s = socket.socket()
    s.bind(('127.0.0.1', 0))
    port = s.getsockname()[1]
    s.close()
    return port


def book_counter(pg):
    return pg.evaluate("document.getElementById('bookpage').value + ' / ' + document.getElementById('booktotal').textContent")


def wait_port(port, timeout=10):
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            urllib.request.urlopen('http://127.0.0.1:%d/__list' % port, timeout=1)
            return True
        except Exception:
            time.sleep(0.2)
    return False


def body_bg(page):
    return page.evaluate("getComputedStyle(document.body).backgroundColor")


def var_bg(page):
    v = page.evaluate("getComputedStyle(document.documentElement).getPropertyValue('--bg').trim()")
    if len(v) == 7 and v.startswith('#'):
        return 'rgb(%d, %d, %d)' % (int(v[1:3], 16), int(v[3:5], 16), int(v[5:7], 16))
    return v


root = pathlib.Path(tempfile.mkdtemp(prefix='viewer-test-'))
(root / '11').mkdir()
(root / '11' / '11.txt').write_text('старое 11\n', encoding='utf-8')
(root / 'VPN.md').write_text('старое vpn\n', encoding='utf-8')
(root / 'tool.py').write_text('import os\nprint(os.name)\n', encoding='utf-8')
os.chmod(root / 'tool.py', 0o755)
tool_py = root / 'tool.py'
ALLOWED_HIDDEN = {'.gitignore', '.dockerignore', '.editorconfig', '.env', '.bashrc', '.zshrc', '.vimrc'}
(root / 'Dockerfile').write_text('FROM python:3.12\nRUN echo hi\n', encoding='utf-8')
file11 = root / '11' / '11.txt'
vpn = root / 'VPN.md'

PORT = free_port()
base = 'http://127.0.0.1:%d/' % PORT
env = dict(os.environ, BROWSER='true')
srv = subprocess.Popen([sys.executable, str(HERE / 'serve.py'), str(PORT), str(root)],
                       env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
try:
    if not wait_port(PORT):
        print('FAIL сервер не поднялся')
        sys.exit(1)
    with sync_playwright() as p:
        browser = p.chromium.launch(channel='chrome', headless=True)
        page = browser.new_page()
        page.add_init_script("delete window.showOpenFilePicker")

        page.goto(base)
        page.wait_for_load_state('networkidle')
        check('голый холст пуст', page.eval_on_selector('#t', 'el => el.value') == '')
        check('подсказка про кнопку', 'открой файл' in page.eval_on_selector('#target', 'el => el.textContent'))

        page.goto(base + '?file=11/11.txt')
        page.wait_for_load_state('networkidle')
        page.wait_for_function("document.getElementById('t').value.length > 0", timeout=15000)
        check('файл загружен с диска', page.eval_on_selector('#t', 'el => el.value') == 'старое 11\n')
        check('полный путь в цели', page.eval_on_selector('#target', 'el => el.textContent').endswith('11/11.txt'))
        check('ссылка читаемая', page.evaluate('location.search') == '?file=11/11.txt',
              repr(page.evaluate('location.search')))

        lines = page.eval_on_selector('#t', 'el => el.value.split("\\n")')
        mirror = page.eval_on_selector_all('#back .ln', 'els => els.map(e => e.textContent)')
        check('зеркало строк = текст', mirror == lines, '%d строк против %d' % (len(mirror), len(lines)))
        gut = page.evaluate("getComputedStyle(document.documentElement).getPropertyValue('--gut')")
        num = page.evaluate("getComputedStyle(document.querySelector('#back .ln'), '::before').content")
        check('номер строки и колонка есть', 'ch' in gut and num not in ('none', 'normal', ''),
              'gut=%s ::before=%s' % (gut.strip(), num))

        bg_light = body_bg(page)
        page.click('#theme')
        page.wait_for_timeout(300)  # тема едет через transition .18s — ждём конец, не середину
        bg_dark = body_bg(page)
        check('тёмная включается', bg_dark != bg_light and bg_dark == var_bg(page),
              'было %s, стало %s' % (bg_light, bg_dark))
        page.reload()
        page.wait_for_load_state('networkidle')
        check('тёмная пережила F5', body_bg(page) == bg_dark)
        page.click('#theme')
        page.wait_for_timeout(300)
        check('светлая возвращается', body_bg(page) == bg_light)

        page.click('#plus')
        check('A+ даёт 14px', page.evaluate("getComputedStyle(document.documentElement).fontSize") == '14px')
        x0 = page.eval_on_selector('#minus', 'el => el.getBoundingClientRect().x')
        page.click('#plus')
        x1 = page.eval_on_selector('#minus', 'el => el.getBoundingClientRect().x')
        check('A+ не сдвигает кнопки', abs(x1 - x0) < 0.5, '%.1f -> %.1f' % (x0, x1))
        dmid = page.evaluate("""() => {
          const c = s => { const b = document.querySelector(s).getBoundingClientRect(); return (b.top + b.bottom) / 2; };
          return Math.abs(c('#fsval') - c('#minus'));
        }""")
        check('номер размера по центру кнопок', dmid < 1, 'дельта %.1fpx' % dmid)
        page.click('#reset')
        check('13px возвращает дефолт', page.evaluate("getComputedStyle(document.documentElement).fontSize") == '13px'
              and page.eval_on_selector('#reset', 'el => el.disabled'))

        def chrome_sizes():
            page.click('#navbtn')
            page.wait_for_timeout(400)
            sizes = [page.eval_on_selector('#navbtn', 'el => getComputedStyle(el).fontSize'),
                     page.eval_on_selector('.navitem', 'el => getComputedStyle(el).fontSize'),
                     page.eval_on_selector('#navpanel', 'el => Math.round(el.getBoundingClientRect().width)')]
            page.keyboard.press('Escape')
            return sizes

        chrome13 = chrome_sizes()
        for _ in range(3):
            page.click('#plus')
        chrome16 = chrome_sizes()
        check('хром не зависит от размера текста', chrome13 == chrome16, '%s vs %s' % (chrome13, chrome16))
        page.click('#reset')

        page.fill('#t', 'правка из теста')
        page.keyboard.press('Control+s')
        page.wait_for_function("document.getElementById('save').textContent.includes('сохранено')")
        check('Ctrl+S записал файл', file11.read_text(encoding='utf-8') == 'правка из теста')

        dialogs = []
        page.once('dialog', lambda d: (dialogs.append(d.message), d.dismiss()))
        page.fill('#t', '   ')
        page.keyboard.press('Control+s')
        page.wait_for_timeout(600)
        check('пробелы: спросил и не записал',
              dialogs and 'затереть' in dialogs[0] and file11.read_text(encoding='utf-8') == 'правка из теста',
              dialogs[0] if dialogs else 'диалога не было')

        page.once('dialog', lambda d: d.accept())
        page.fill('#t', '')
        page.keyboard.press('Control+s')
        page.wait_for_function("document.getElementById('save').textContent.includes('сохранено')")
        check('пусто + «затереть»: файл обнулён', file11.read_text(encoding='utf-8') == '')

        page.fill('#t', 'правка из теста')
        page.keyboard.press('Control+s')
        page.wait_for_function("document.getElementById('save').textContent.includes('сохранено')")

        page.set_input_files('#file', {'name': 'VPN.md', 'mimeType': 'text/plain', 'buffer': b'vpn pravka'})
        page.wait_for_function("document.getElementById('t').value === 'vpn pravka'")
        check('кнопка: цель = VPN.md', page.eval_on_selector('#target', 'el => el.textContent').endswith('VPN.md'))
        check('ссылка после кнопки', page.evaluate('location.search') == '?file=VPN.md',
              repr(page.evaluate('location.search')))
        page.keyboard.press('Control+s')
        page.wait_for_function("document.getElementById('save').textContent.includes('сохранено')")
        check('кнопка: VPN.md записан', vpn.read_text(encoding='utf-8') == 'vpn pravka')
        check('соседний файл не тронут', file11.read_text(encoding='utf-8') == 'правка из теста')
        page.goto(base + '?file=tool.py')
        page.wait_for_load_state('networkidle')
        page.wait_for_function("document.getElementById('t').value.length > 0")
        page.fill('#t', 'import os\nprint(os.name)\n# правка\n')
        page.keyboard.press('Control+s')
        page.wait_for_function("document.getElementById('save').textContent.includes('сохранено')")
        mode = oct(tool_py.stat().st_mode & 0o7777)
        leftovers = [p.name for p in root.iterdir() if p.name.startswith('.') and p.name not in ALLOWED_HIDDEN]
        check('запись атомарная: содержимое и права файла целы', tool_py.read_text(encoding='utf-8').endswith('# правка\n'), 'права ' + mode)
        check('запись сохранила права 0755 (не сбросила в 0600)', mode == '0o755', mode)
        check('после записи в папке нет мусорных временных файлов', leftovers == [], str(leftovers))
        check('запись идёт через os.replace, а не write_bytes',
              'os.replace(' in (HERE / 'serve.py').read_text(encoding='utf-8')
              and 'target.write_bytes' not in (HERE / 'serve.py').read_text(encoding='utf-8'))
        check('после сохранения кнопка снова живая, в билде нет самодельных пухлых теней',
              not page.eval_on_selector('#save', 'el => el.disabled')
              and '0 22px 60px' not in (HERE / 'index.html').read_text(encoding='utf-8')
              and '0 18px 50px' not in (HERE / 'index.html').read_text(encoding='utf-8'), '')
        dirty_guard = page.evaluate("""() => ({dirty: dirty, fname: document.getElementById('fname').textContent})""")
        page.fill('#t', dirty_guard['fname'] and page.eval_on_selector('#t', 'el => el.value') + '\nправка без сохранения' or 'правка без сохранения')
        page.wait_for_timeout(200)
        page.keyboard.press('Control+p')
        page.wait_for_selector('#nav:not([hidden])')
        page.wait_for_timeout(400)
        page.fill('#pathin', 'VPN')
        page.wait_for_timeout(300)
        page.press('#pathin', 'Enter')      # диалог никто не принимает — Playwright отклоняет
        page.wait_for_timeout(700)
        check('несохранённые правки: уход в другой файл не проходит без согласия',
              page.eval_on_selector('#fname', 'el => el.textContent') == dirty_guard['fname'],
              page.eval_on_selector('#fname', 'el => el.textContent') + ' vs ' + dirty_guard['fname'])
        page.once('dialog', lambda d: d.accept())
        page.keyboard.press('Control+p')
        page.wait_for_selector('#nav:not([hidden])')
        page.wait_for_timeout(300)
        page.fill('#pathin', 'VPN')
        page.wait_for_timeout(300)
        page.press('#pathin', 'Enter')
        page.wait_for_function("document.getElementById('fname').textContent === 'VPN.md'")
        check('несохранённые правки: с согласием файл открывается', True)

        (root / 'ro').mkdir(exist_ok=True)
        (root / 'ro' / 'ro.txt').write_text('не трогать\n', encoding='utf-8')
        os.chmod(root / 'ro', 0o555)
        try:
            page.goto(base + '?file=ro/ro.txt')
            page.wait_for_load_state('networkidle')
            page.wait_for_function("document.getElementById('t').value.length > 0")
            page.fill('#t', 'попытка записи\n')
            page.keyboard.press('Control+s')
            page.wait_for_function("document.getElementById('save').textContent.includes('не принял')")
            check('запись в чужую папку отбита, файл цел',
                  (root / 'ro' / 'ro.txt').read_text(encoding='utf-8') == 'не трогать\n',
                  page.eval_on_selector('#save', 'el => el.textContent'))
        finally:
            os.chmod(root / 'ro', 0o755)

        page.goto(base + '?file=11/11.txt')
        page.wait_for_load_state('networkidle')
        page.wait_for_function("document.getElementById('t').value.length > 0")
        check('txt без подсветки', page.evaluate("document.querySelectorAll('#back span[class^=\"hljs\"]').length") == 0)
        page.goto(base + '?file=tool.py')
        page.wait_for_load_state('networkidle')
        page.wait_for_function("document.querySelectorAll('#back .hljs-keyword').length > 0")
        kw_light = page.evaluate("getComputedStyle(document.querySelector('#back .hljs-keyword')).color")
        page.click('#theme')
        page.wait_for_timeout(350)
        kw_dark = page.evaluate("getComputedStyle(document.querySelector('#back .hljs-keyword')).color")
        check('подсветка .py, токены зависят от темы', kw_light != kw_dark, '%s vs %s' % (kw_light, kw_dark))
        page.goto(base + '?file=Dockerfile')
        page.wait_for_load_state('networkidle')
        page.wait_for_function("document.querySelectorAll('#back .hljs-keyword').length > 0")
        check('подсветка Dockerfile', True)

        big = root / 'big.py'
        big.write_text('value = 123\n' * 4000, encoding='utf-8')
        longline = root / 'longline.txt'
        longline.write_text('x' * 4000 + '\nвторая строка\n', encoding='utf-8')
        (root / 'wide.py').write_text(('x = "' + 'y' * 500 + '"\n') * 60, encoding='utf-8')
        (root / 'bundle.min.js').write_text('var a=' + '"x",' * 1200 + '"z";\n', encoding='utf-8')
        (root / 'notes.md').write_text('# Заголовок\n\n**жирный** и *курсив* и `код` и [ссылка](https://example.com)\n\n- пункт раз\n- пункт два\n', encoding='utf-8')
        (root / '11' / 'deep').mkdir(exist_ok=True)
        (root / '11' / 'deep' / 'canon.md').write_text('# глубокий\n', encoding='utf-8')
        (root / '11' / 'pic.png').write_bytes(png_bytes(1600, 1000))
        (root / 'rootpic.md').write_text('# корневой файл\n\n![тут](pic-root.png)\n', encoding='utf-8')
        (root / 'pic-root.png').write_bytes(png_bytes(24, 16))
        (root / '11' / 'canon.md').write_text('''# Заголовок первый

Абзац с **жирным**, *курсивом*, `инлайн-кодом` и [ссылкой](https://example.com/page).

[вглубь](deep/canon.md) — соседний файл.

![схема](pic.png)

![пропажа](missing.png)

## Список

- пункт раз
  - вложенный пункт
- пункт два

1. первый
2. второй

> цитата в блоке

| язык | год |
| --- | --- |
| python | 1991 |

```python
def hello(name: str) -> str:
    return f"привет, {name}"
```

---

<script>window.__xss = 1</script>

[опасная](javascript:window.__xss=2)
''', encoding='utf-8')
        (root / 'tool.diff').write_text('--- a\n+++ b\n-старая строка\n+новая строка\n общая\n', encoding='utf-8')
        (root / 'empty.md').write_text('', encoding='utf-8')
        (root / 'search.txt').write_text('яблоко в строке\nгруша и яблоко\nяблоко яблоко\nслива\nMARKER строка тут\n'
                                         + ''.join('строка %d\n' % i for i in range(6, 80))
                                         + 'слива на последней странице\n', encoding='utf-8')
        (root / 'search2.txt').write_text('MARKER в другом файле\nвторая строка про сливу\n', encoding='utf-8')
        for i in range(1, 31):
            (root / ('pad%02d.txt' % i)).write_text('наполнитель списка %d\n' % i, encoding='utf-8')
        page.goto(base + '?file=longline.txt')
        page.wait_for_load_state('networkidle')
        page.wait_for_function("document.getElementById('t').value.length > 0")
        rows_wrap = page.evaluate("Math.round(back.children[0].offsetHeight / parseFloat(getComputedStyle(document.getElementById('t')).lineHeight))")
        page.click('#wrapbtn')
        page.wait_for_timeout(300)
        rows_nowrap = page.evaluate("Math.round(back.children[0].offsetHeight / parseFloat(getComputedStyle(document.getElementById('t')).lineHeight))")
        check('перенос выключается: длинная строка = одна', rows_wrap > 3 and rows_nowrap == 1,
              'было %d строк, стало %d' % (rows_wrap, rows_nowrap))
        check('перенос: wrap=off и класс nowrap', page.evaluate("document.getElementById('t').getAttribute('wrap') === 'off' && document.body.classList.contains('nowrap')"))
        clip = page.evaluate("""(() => {
          const t = document.getElementById('t'), b = document.getElementById('back');
          t.scrollTop = t.scrollHeight;
          t.scrollLeft = t.scrollWidth;
          const last = b.children[b.children.length - 1];
          const backH = last.offsetTop + last.offsetHeight;
          const res = {taH: t.scrollHeight, backH: backH, cliH: t.clientHeight, taW: t.scrollWidth, cliW: t.clientWidth,
                       st: Math.round(t.scrollTop), sl: Math.round(t.scrollLeft),
                       виден_конец: last.offsetTop + last.offsetHeight <= t.scrollTop + t.clientHeight + 1};
          t.scrollTop = 0;
          t.scrollLeft = 0;
          return res;
        })()""")
        check('перенос выкл: textarea тоже не переносит — высоты сходятся, есть скролл вбок',
              abs(clip['taH'] - max(clip['backH'], clip['cliH'])) <= 4 and clip['taW'] > clip['cliW'] + 100, str(clip))
        check('перенос выкл: докрутив вниз-вправо, видно конец текста', clip['виден_конец'], str(clip))
        page.click('#wrapbtn')
        page.wait_for_timeout(300)
        check('перенос включается обратно', page.evaluate("document.getElementById('t').getAttribute('wrap') === 'soft' && !document.body.classList.contains('nowrap')"))

        page.click('#wrapbtn')
        page.wait_for_timeout(250)
        clipped = page.evaluate("(() => { const l = document.getElementById('back').children[0]; const r = document.createRange(); r.selectNodeContents(l); return Math.max(...Array.from(r.getClientRects()).map(q => q.width)) > document.querySelector('.editor').clientWidth; })()")
        check('перенос выкл: длинная строка вылезает за колонку', bool(clipped))
        mask = page.evaluate("""(() => {
          const back = document.getElementById('back');
          const a = getComputedStyle(back, '::after');
          const b = getComputedStyle(back.children[0], '::before');
          return {content: a.content, width: a.width, bg: a.backgroundColor, transform: a.transform, numZ: b.zIndex};
        })()""")
        check('перенос выкл: гаттер закрыт маской, номера поверх неё',
              mask['content'] not in ('none', 'normal', '') and 'rgba(0, 0, 0, 0)' not in mask['bg']
              and mask['transform'].startswith('matrix') and mask['numZ'] == '1', str(mask))
        page.click('#bookbtn')
        page.wait_for_function("document.body.classList.contains('book')")
        page.wait_for_timeout(400)
        check('книга: перенос включается сам и кнопка переноса скрыта', page.evaluate(
            "document.getElementById('t').getAttribute('wrap') === 'soft'"
            " && !document.body.classList.contains('nowrap')"
            " && getComputedStyle(document.getElementById('wrapbtn')).display === 'none'"))
        cardfit = page.evaluate("""(() => {
          const ed = document.querySelector('.editor'), m = document.querySelector('main');
          return [Math.round(ed.getBoundingClientRect().height), m.clientHeight];
        })()""")
        check('книга: карточка не выше окна (строка длиннее страницы не раздувает карточку)',
              cardfit[0] <= cardfit[1] + 1, str(cardfit))
        pages_n = page.evaluate("bookPages()")
        check('книга: страницы идут фиксированным шагом (монстр-строка не раздувает карточку)', pages_n > 1, str(pages_n))
        fits = page.evaluate("(() => { const l = document.getElementById('back').children[0]; return l.scrollWidth <= l.clientWidth + 1; })()")
        check('книга: длинная строка не обрезается по правому краю', bool(fits))
        hang = page.evaluate("""(() => {
          const l = document.getElementById('back').children[0];
          const r = document.createRange();
          r.selectNodeContents(l);
          const rects = Array.from(r.getClientRects());
          return {rows: rects.length, dx: rects.length > 1 ? Math.round(rects[1].left - rects[0].left) : 0};
        })()""")
        check('книга: продолжение строки с отступом', hang['rows'] > 1 and hang['dx'] > 8, str(hang))
        win = page.evaluate("""(() => {
          const w = document.getElementById('backw').getBoundingClientRect();
          const t = document.getElementById('t').getBoundingClientRect();
          return [Math.round(w.top - t.top), Math.round(w.height - t.height)];
        })()""")
        check('книга: окно холста совпадает с полем textarea (нет подгляда соседней строки в поле карточки)',
              abs(win[0]) <= 1 and abs(win[1]) <= 1, str(win))
        hs = page.evaluate("[document.getElementById('back').lastElementChild.offsetTop + document.getElementById('back').lastElementChild.offsetHeight, document.getElementById('t').scrollHeight]")
        check('книга: текст холста не выше textarea (иначе последняя страница режется)', hs[0] <= hs[1], 'холст %d, textarea %d' % tuple(hs))
        page.evaluate("bookGoto(bookPages())")
        page.wait_for_timeout(250)
        tail = page.evaluate("""(() => {
          const t = document.getElementById('t');
          const lns = document.querySelectorAll('#back .ln');
          const l = lns[lns.length - 1];
          const bottom = l.offsetTop + l.offsetHeight;
          return {в_странице: bottom <= t.scrollTop + t.clientHeight + 1, ниже_верха: bottom > t.scrollTop};
        })()""")
        check('книга: последняя страница показывает конец текста', tail['в_странице'] and tail['ниже_верха'], str(tail))
        page.click('#bookbtn')
        page.wait_for_function("!document.body.classList.contains('book')")
        page.wait_for_timeout(300)
        check('книга: вне книги отступ продолжений снят', page.evaluate("getComputedStyle(document.getElementById('back').children[0]).textIndent") in ('0px', '0'))
        check('книга: выход возвращает перенос как было (выкл)', page.evaluate(
            "document.getElementById('t').getAttribute('wrap') === 'off' && document.body.classList.contains('nowrap')"))
        page.click('#wrapbtn')
        page.wait_for_timeout(200)

        page.goto(base + '?file=wide.py')
        page.wait_for_function("document.getElementById('t').value.length > 0")
        page.wait_for_timeout(300)
        if not page.evaluate("document.body.classList.contains('nowrap')"):
            page.click('#wrapbtn')
            page.wait_for_timeout(300)
        w = page.evaluate("""(() => {
          const t = document.getElementById('t'), b = document.getElementById('back');
          const last = b.children[b.children.length - 1];
          const backH = last.offsetTop + last.offsetHeight;
          t.scrollTop = t.scrollHeight;
          const res = {taH: t.scrollHeight, backH: backH, cliH: t.clientHeight, taW: t.scrollWidth, cliW: t.clientWidth,
                       виден_конец: last.offsetTop + last.offsetHeight <= t.scrollTop + t.clientHeight + 1};
          t.scrollTop = 0;
          t.scrollLeft = 0;
          return res;
        })()""")
        check('перенос выкл на длинном файле: textarea не переносит — высоты сходятся, скролл вбок есть',
              abs(w['taH'] - w['backH']) <= 4 and w['taW'] > w['cliW'] + 100, str(w))
        check('перенос выкл на длинном файле: конец текста достижим и виден', w['виден_конец'], str(w))
        fx = page.evaluate("""(() => {
          const t = document.getElementById('t'), b = document.getElementById('back'), ed = document.querySelector('.editor');
          t.scrollLeft = 600;
          const res = {edL: Math.round(ed.getBoundingClientRect().left), edR: Math.round(ed.getBoundingClientRect().right),
                       backR: Math.round(b.getBoundingClientRect().right), backW: b.offsetWidth, taW: t.scrollWidth};
          t.scrollLeft = 0;
          return res;
        })()""")
        check('перенос выкл: холст шире прокрутки — при скролле вбок нет пустой полосы справа',
              fx['backR'] >= fx['edR'] and fx['backW'] >= fx['taW'], str(fx))

        page.evaluate("localStorage.removeItem('txtviewer')")
        page.goto(base + '?file=big.py')
        page.wait_for_function("document.getElementById('t').value.length > 0")
        page.wait_for_timeout(300)
        check('авто-перенос: обычный код открывается без переноса',
              page.evaluate("document.body.classList.contains('nowrap')"))
        page.goto(base + '?file=bundle.min.js')
        page.wait_for_function("document.getElementById('t').value.length > 0")
        page.wait_for_timeout(300)
        check('авто-перенос: минифицированная строка открывается с переносом',
              page.evaluate("!document.body.classList.contains('nowrap')"))
        page.click('#wrapbtn')
        page.wait_for_timeout(300)
        page.goto(base + '?file=bundle.min.js')
        page.wait_for_function("document.getElementById('t').value.length > 0")
        page.wait_for_timeout(300)
        check('авто-перенос: выбор пользователя сильнее эвристики',
              page.evaluate("document.body.classList.contains('nowrap')"))

        page.evaluate("localStorage.removeItem('txtviewer')")
        page.goto(base + '?file=notes.md')
        page.wait_for_function("document.querySelectorAll('#back span').length > 0")
        page.wait_for_timeout(300)
        md = page.evaluate("""(() => {
          const b = document.getElementById('back');
          const css = s => { const e = b.querySelector(s); return e ? getComputedStyle(e) : null; };
          const strong = css('.hljs-strong'), emph = css('.hljs-emphasis'), code = css('.hljs-code'),
                link = css('.hljs-link'), bullet = css('.hljs-bullet');
          return {nowrap: document.body.classList.contains('nowrap'),
                  section: !!b.querySelector('.hljs-section'),
                  strong: strong && strong.fontWeight, emphasis: emph && emph.fontStyle,
                  code: code && code.color, link: link && link.textDecorationLine, bullet: bullet && bullet.color};
        })()""")
        check('md: открывается с переносом (это проза) и заголовок подсвечен',
              (not md['nowrap']) and md['section'], str(md))
        check('md: жирный, курсив, код, ссылка и пункты покрашены',
              md['strong'] in ('700', 'bold') and md['emphasis'] == 'italic' and md['link'] == 'underline'
              and md['code'] and md['bullet'], str(md))
        page.goto(base + '?file=tool.diff')
        page.wait_for_function("document.querySelectorAll('#back span').length > 0")
        df = page.evaluate("""(() => {
          const b = document.getElementById('back');
          const g = s => { const e = b.querySelector(s); return e ? getComputedStyle(e).color : null; };
          return {add: g('.hljs-addition'), del: g('.hljs-deletion')};
        })()""")
        check('diff: добавление и удаление разного цвета', bool(df['add']) and bool(df['del']) and df['add'] != df['del'], str(df))

        page.goto(base + '?file=11/canon.md')
        page.wait_for_function("!document.getElementById('viewbtn').hidden")
        page.wait_for_timeout(300)
        check('кнопка просмотра есть у md и подписана «просмотр»',
              page.evaluate("document.getElementById('viewbtn').textContent") == 'просмотр')
        page.click('#viewbtn')
        page.wait_for_function("document.body.classList.contains('preview')")
        page.wait_for_timeout(300)
        pv = page.evaluate("""(() => {
          const v = document.getElementById('view');
          const link = v.querySelector('a[href^="https"]');
          return {textareaHidden: getComputedStyle(document.getElementById('t')).display === 'none',
                  h1: v.querySelector('h1') ? v.querySelector('h1').textContent : null,
                  h2: !!v.querySelector('h2'), ul: v.querySelectorAll('ul li').length,
                  nested: !!v.querySelector('ul li ul li'), ol: v.querySelectorAll('ol li').length,
                  table: v.querySelectorAll('table tr').length, quote: !!v.querySelector('blockquote'),
                  hr: !!v.querySelector('hr'), fence: v.querySelectorAll('pre code .hljs-keyword').length,
                  linkTarget: link ? link.getAttribute('target') : null,
                  imgs: Array.from(v.querySelectorAll('img')).map(i => ({src: i.getAttribute('src'), w: i.naturalWidth})),
                  miss: (() => { const m = v.querySelector('.imgmiss'); return m ? m.textContent : null; })(),
                  xss: typeof window.__xss, script: !!v.querySelector('script'),
                  jsHref: !!v.querySelector('a[href^="javascript:"]')};
        })()""")
        check('просмотр md: заголовки, списки, таблица, цитата, линия и блок кода с подсветкой',
              bool(pv['h1']) and pv['h2'] and pv['ul'] >= 3 and pv['nested'] and pv['ol'] == 2
              and pv['table'] >= 2 and pv['quote'] and pv['hr'] and pv['fence'] > 0 and pv['textareaHidden'], str(pv))
        check('просмотр md: внешняя ссылка открывается в новой вкладке', pv['linkTarget'] == '_blank', str(pv['linkTarget']))
        check('просмотр md: картинка ищется рядом с файлом и грузится',
              any(i['src'] == '/11/pic.png' and i['w'] > 0 for i in pv['imgs']), str(pv['imgs']))
        check('просмотр md: пропавшая картинка становится читаемой плашкой, а не битым alt',
              'missing.png' in (pv['miss'] or '') and 'пропажа' in (pv['miss'] or ''), str(pv['miss']))
        check('просмотр md: сырой html и javascript: не выполняются',
              pv['xss'] == 'undefined' and not pv['script'] and not pv['jsHref'], str(pv))
        lk = page.evaluate("""() => { const a = document.querySelector('#view a[data-rel]');
            return a ? {rel: a.getAttribute('data-rel'), href: a.getAttribute('href'), tgt: a.getAttribute('target')} : null; }""")
        check('ссылка на соседний файл получает внутренний адрес и не уходит в новую вкладку сама',
              lk and lk['rel'] == '11/deep/canon.md' and '?file=' in lk['href'] and lk['tgt'] is None, str(lk))
        page.click('#view a[data-rel]')
        page.wait_for_function("document.getElementById('t').value.startsWith('# глубокий')")
        opened = page.evaluate("""() => ({preview: document.body.classList.contains('preview'),
                                         h: document.querySelector('#view h1') ? document.querySelector('#view h1').textContent : '',
                                         url: location.search})""")
        check('клик по ссылке открывает файл в этой же вкладке, просмотр перерисовывается',
              opened['preview'] and opened['h'] == 'глубокий' and opened['url'] == '?file=11/deep/canon.md', str(opened))
        page.goto(base + '?file=11/canon.md')
        page.wait_for_function("document.getElementById('t').value.startsWith('# Заголовок первый')")
        page.click('#viewbtn')
        page.wait_for_function("document.body.classList.contains('preview')")
        with page.expect_popup() as pop:
            page.click('#view a[data-rel]', modifiers=['Control'])
        pup = pop.value
        pup.wait_for_load_state()
        check('Ctrl+клик открывает ссылку в новой вкладке вьювера', '?file=11/deep/canon.md' in pup.url, pup.url)
        pup.close()
        (root / 'long.md').write_text('# длинный\n\n' + 'строка текста для прокрутки\n' * 200, encoding='utf-8')
        page.goto(base + '?file=long.md')
        page.wait_for_function("document.getElementById('t').value.length > 1000")
        page.click('#viewbtn')
        page.wait_for_function("document.body.classList.contains('preview')")
        page.hover('#view')
        page.mouse.wheel(0, 500)
        page.wait_for_timeout(250)
        sc = page.evaluate("document.getElementById('view').scrollTop")
        check('колесо мыши скроллит просмотр markdown', sc > 0, 'scrollTop=' + str(sc))
        # вкладки открытых файлов: клик — в текущей, средний клик и крестик — закрыть
        page.evaluate("() => { st.tabs = []; st.tab = ''; save(); }")
        page.goto(base + '?file=11/canon.md')
        page.wait_for_function("document.getElementById('t').value.startsWith('# Заголовок первый')")
        page.wait_for_function("document.querySelectorAll('#tabs .tab').length === 1")
        page.click('#viewbtn')
        page.wait_for_function("document.body.classList.contains('preview')")
        page.click('#view a[data-rel]')
        page.wait_for_function("document.querySelectorAll('#tabs .tab').length === 2")
        tb = page.evaluate("""() => ({n: document.querySelectorAll('#tabs .tab').length,
                                      rels: [...document.querySelectorAll('#tabs .tab')].map(e => e.dataset.rel),
                                      on: (document.querySelector('#tabs .tab.on') || {dataset: {}}).dataset.rel})""")
        check('каждая открытая ссылка даёт вкладку, активная подсвечена',
              tb['n'] == 2 and tb['rels'] == ['11/canon.md', '11/deep/canon.md'] and tb['on'] == '11/deep/canon.md', str(tb))
        page.click("#tabs .tab[data-rel='11/canon.md']")
        page.wait_for_function("location.search === '?file=11/canon.md' && document.getElementById('t').value.startsWith('# Заголовок первый')")
        check('клик по вкладке открывает файл в этой же вкладке браузера',
              page.evaluate("document.querySelector('#tabs .tab.on').dataset.rel") == '11/canon.md', page.url)
        page.click("#tabs .tab[data-rel='11/deep/canon.md']", button='middle')
        page.wait_for_function("document.querySelectorAll('#tabs .tab').length === 1")
        check('средний клик закрывает вкладку',
              page.evaluate("document.querySelector('#tabs .tab.on').dataset.rel") == '11/canon.md', '')
        page.goto(base + '?file=11/canon.md')
        page.wait_for_function("document.getElementById('t').value.startsWith('# Заголовок первый')")
        page.click('#viewbtn')
        page.wait_for_function("document.body.classList.contains('preview')")
        page.click('#view a[data-rel]')
        page.wait_for_function("document.querySelectorAll('#tabs .tab').length === 2")
        page.click('#tabs .tab.on .x')
        page.wait_for_function("location.search === '?file=11/canon.md' && document.querySelectorAll('#tabs .tab').length === 1")
        check('крестик закрывает активную вкладку и открывает соседнюю', True, page.url)
        pv2 = page.evaluate("""() => { const v = document.getElementById('view'); const p = v.querySelector('p');
            return {pad: parseFloat(getComputedStyle(v).paddingLeft), w: p ? Math.round(p.getBoundingClientRect().width) : 0,
                    x: p ? Math.round(p.getBoundingClientRect().left) : 0}; }""")
        check('просмотр md: поля и читаемая колонка, текст не липнет к краю',
              pv2['pad'] >= 16 and 0 < pv2['w'] <= 1010 and pv2['x'] >= 16, str(pv2))
        page.reload()
        page.wait_for_function("document.querySelectorAll('#tabs .tab').length === 1 && document.querySelector('#tabs .tab.on')")
        check('вкладки переживают перезагрузку', True, '')
        page.click('#viewbtn')
        page.wait_for_function("document.body.classList.contains('preview')")
        page.click('#viewbtn')
        page.wait_for_timeout(200)
        back_clean = page.evaluate("""() => ({preview: document.body.classList.contains('preview'),
                                             hint: document.body.classList.contains('hint'),
                                             viewDisplay: getComputedStyle(document.getElementById('view')).display,
                                             viewEmpty: document.getElementById('view').textContent.trim() === '',
                                             ta: getComputedStyle(document.getElementById('t')).display})""")
        check('возврат из просмотра в текст: вид скрыт и очищен, редактор на месте',
              (not back_clean['preview']) and (not back_clean['hint']) and back_clean['viewDisplay'] == 'none'
              and back_clean['viewEmpty'] and back_clean['ta'] == 'block', str(back_clean))
        page.goto(base + '?file=tool.py')
        page.wait_for_function("document.getElementById('t').value.length > 0")
        page.click('#navbtn')
        page.wait_for_function("!document.getElementById('nav').hidden && document.querySelectorAll('#navlist .navitem').length > 3")
        page.fill('#pathin', 'canon')
        page.wait_for_function("document.querySelectorAll('#navlist .navitem').length === 2")
        popups = []
        page.context.on('page', lambda pg2: popups.append(pg2))
        page.evaluate_handle("() => [...document.querySelectorAll('#navlist .navitem')].find(r => r.textContent.includes('canon.md') && !r.textContent.includes('deep'))").as_element().click(modifiers=['Control'])
        page.wait_for_timeout(1000)
        print('T5 popups:', len(popups), [pp.url for pp in popups], flush=True)
        check('Ctrl+клик по файлу в обзоре открывает его в новой вкладке браузера',
              len(popups) == 1 and '?file=11/canon.md' in popups[0].url, str([pp.url for pp in popups]))
        if popups: popups[0].close()
        popups.clear()
        page.evaluate_handle("() => [...document.querySelectorAll('#navlist .navitem')].find(r => r.textContent.includes('deep/canon.md'))").as_element().click(button='middle')
        page.wait_for_timeout(1000)
        check('средний клик по файлу в обзоре тоже даёт новую вкладку',
              len(popups) == 1 and '?file=11/deep/canon.md' in popups[0].url, str([pp.url for pp in popups]))
        if popups: popups[0].close()
        popups.clear()
        page.press('#pathin', 'Control+Enter')
        page.wait_for_timeout(1000)
        check('Ctrl+Enter в поле пути открывает файл в новой вкладке',
              len(popups) == 1 and '?file=11/canon.md' in popups[0].url, str([pp.url for pp in popups]))
        if popups: popups[0].close()
        page.keyboard.press('Escape')
        page.wait_for_timeout(150)
        page.goto(base + '?file=rootpic.md')
        page.wait_for_function("!document.getElementById('viewbtn').hidden")
        page.wait_for_timeout(300)
        page.click('#viewbtn')
        page.wait_for_function("document.body.classList.contains('preview')")
        page.wait_for_timeout(700)
        rootimg = page.evaluate("""() => { const i = document.querySelector('#view img');
          return {src: i ? i.getAttribute('src') : null, w: i ? i.naturalWidth : 0,
                  miss: !!document.querySelector('#view .imgmiss')}; }""")
        check('просмотр md: у файла в корне корня картинка тоже ищется рядом (не от корня сервера)',
              rootimg['src'] == '/pic-root.png' and rootimg['w'] > 0 and not rootimg['miss'], str(rootimg))
        page.click('#viewbtn')
        page.wait_for_timeout(200)
        back = page.evaluate("""() => ({preview: document.body.classList.contains('preview'),
                                       same: document.getElementById('t').value.includes('корневой файл')})""")
        check('просмотр md: возврат к исходнику сохраняет текст', (not back['preview']) and back['same'], str(back))
        page.click('#viewbtn')
        page.wait_for_function("document.body.classList.contains('preview')")
        page.click('#wrapbtn')
        page.wait_for_timeout(400)
        page.click('#viewbtn')
        page.wait_for_function("!document.body.classList.contains('preview')")
        page.wait_for_timeout(700)
        pw = page.evaluate("""() => { const b = document.getElementById('back'), t = document.getElementById('t');
          const lh = parseFloat(getComputedStyle(t).lineHeight) || 20;
          return {backW: b.offsetWidth, lines: b.children.length,
                  firstRows: b.children.length ? Math.round(b.children[0].offsetHeight / lh * 10) / 10 : 0,
                  spans: b.querySelectorAll('span').length}; }""")
        check('перенос, нажатый внутри просмотра, не ломает холст после возврата в текст',
              pw['backW'] > 100 and pw['lines'] > 0 and pw['firstRows'] <= 3 and pw['spans'] > 0, str(pw))
        page.click('#wrapbtn')
        page.wait_for_timeout(300)
        page.set_input_files('#file', {'name': 'canon.md', 'mimeType': 'text/markdown', 'buffer': '# из пикера\n'.encode('utf-8')})
        page.wait_for_function("document.getElementById('t').value === '# из пикера\\n'")
        page.wait_for_timeout(300)
        pick = page.evaluate("""() => ({navHidden: document.getElementById('nav').hidden,
                                        target: document.getElementById('target').textContent,
                                        title: document.getElementById('target').title})""")
        check('пикер с неоднозначным именем: контент открыт, цель записи не подключена и это сказано',
              pick['navHidden'] and 'файлов с таким именем' in pick['target'] and '11/canon.md' in pick['title'], str(pick))
        page.evaluate("""() => {
          window.__wrote = null;
          window.__asked = null;
          let first = true;
          window.showOpenFilePicker = async () => [{
            name: 'локальный.md',
            getFile: async () => new File(['# локальный файл\\n'], 'локальный.md', {type: 'text/markdown'}),
            createWritable: async () => {
              if(first){ first = false; throw new DOMException('нужно разрешение', 'NotAllowedError'); }
              return {write: async t => { window.__wrote = t; }, close: async () => {}};
            },
            requestPermission: async o => { window.__asked = o && o.mode; return 'granted'; },
          }];
        }""")
        page.click('#open')
        page.wait_for_function("document.getElementById('t').value === '# локальный файл\\n'")
        page.wait_for_timeout(300)
        loc = page.evaluate("() => document.getElementById('target').textContent")
        mem = page.evaluate("localStorage.getItem('txtviewer') || '{}'")
        check('локальный файл из системного пикера открывается и помечен как локальный',
              'локальный файл' in loc and 'локальный.md' in loc, loc)
        check('локальный документ не оставляет в памяти серверный путь', '"file":""' in mem, mem)
        page.fill('#t', '# правка локального\n')
        page.keyboard.press('Control+s')
        page.wait_for_function("document.getElementById('save').textContent.includes('сохранено')")
        wrote = page.evaluate("window.__wrote")
        check('Ctrl+S пишет прямо в локальный файл через File System Access API, без сервера',
              wrote == '# правка локального\n', str(wrote))
        asked = page.evaluate("window.__asked")
        check('доступ на запись просится только на сохранении и в режиме readwrite', asked == 'readwrite', str(asked))
        page.evaluate("delete window.showOpenFilePicker")
        hnd = page.evaluate("""() => new Promise(async res => {
          try {
            const db = await new Promise(r => { const q = indexedDB.open('textdesk', 1);
              q.onupgradeneeded = () => q.result.createObjectStore('kv'); q.onsuccess = () => r(q.result); q.onerror = () => r(null); });
            if(!db) return res('нет базы');
            const rq = db.transaction('kv', 'readonly').objectStore('kv').get('lastHandle');
            rq.onsuccess = () => res(rq.result ? 'сохранён' : 'пусто');
            rq.onerror = () => res('ошибка чтения');
          } catch(e){ res('исключение: ' + e.message); }
        })""")
        check('дескриптор локального файла уходит в IndexedDB (мок без clone — значит пусто, но не падает)',
              hnd in ('пусто', 'нет базы', 'исключение: DataCloneError' ), hnd)

        page.evaluate("""() => {
          window.showOpenFilePicker = async () => [{
            name: 'локальный.png',
            getFile: async () => new File([Uint8Array.from(atob('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=='), c => c.charCodeAt(0))], 'локальный.png', {type: 'image/png'}),
          }];
        }""")
        page.click('#open')
        page.wait_for_function("document.body.classList.contains('media')")
        page.wait_for_timeout(200)
        lm = page.evaluate("""() => ({src: document.getElementById('mimg').getAttribute('src') || '',
                                       target: document.getElementById('target').textContent})""")
        check('локальная картинка из системного пикера показывается blob-ссылкой',
              lm['src'].startswith('blob:') and 'локальный.png' in lm['target'], str(lm))
        rr = page.evaluate("""() => ({pic: resolveRel('pic.png'), ext: resolveRel('https://example.com/a.md'),
                                       anchor: resolveRel('#x'), miss: resolveRel('no/such/file.md')})""")
        check('у локального файла картинки и ссылки ищутся по уникальному хвосту в корне',
              rr['pic'] == '/11/pic.png' and rr['ext'] == 'https://example.com/a.md'
              and rr['anchor'] == '#x' and rr['miss'] == 'no/such/file.md', str(rr))
        page.evaluate("delete window.showOpenFilePicker")

        page.goto(base + '?file=11/pic.png')
        page.wait_for_function("document.body.classList.contains('media') && document.getElementById('mimg').naturalWidth > 0")
        med = page.evaluate("""() => ({src: document.getElementById('mimg').getAttribute('src'),
                                        img: !document.getElementById('mimg').hidden,
                                        vid: !document.getElementById('mvid').hidden,
                                        pos: document.getElementById('pos').textContent,
                                        target: document.getElementById('target').textContent,
                                        zoom: document.getElementById('mzoom').textContent})""")
        check('png открывается картинкой, а не текстом',
              med['src'] == '/11/pic.png' and med['img'] and not med['vid'] and med['pos'] == 'картинка', str(med))
        t0 = page.evaluate("document.getElementById('mimg').style.transform")
        page.hover('#mimg')
        page.mouse.wheel(0, -240)
        page.wait_for_timeout(150)
        t1 = page.evaluate("document.getElementById('mimg').style.transform")
        check('колесо приближает картинку', t0 != t1, t0 + ' -> ' + t1)
        page.dblclick('#mimg')
        page.wait_for_timeout(150)
        t2 = page.evaluate("document.getElementById('mimg').style.transform")
        check('двойной клик вписывает картинку обратно', 'scale(1)' in t2, t2)
        page.dblclick('#mimg')
        page.wait_for_timeout(150)
        t3 = page.evaluate("document.getElementById('mimg').style.transform")
        check('двойной клик из вписанного даёт 1:1', 'scale(1)' not in t3, t3)
        before = (root / '11' / 'pic.png').read_bytes()
        page.keyboard.press('Control+s')
        page.wait_for_timeout(300)
        lab = page.evaluate("document.getElementById('savelbl').textContent")
        check('в медиа Ctrl+S не пишет: только просмотр',
              lab == 'только просмотр' and (root / '11' / 'pic.png').read_bytes() == before, lab)

        clip = b'\x00\x00\x00\x18ftypmp42' + bytes(range(256)) * 4
        (root / '11' / 'clip.mp4').write_bytes(clip)
        page.goto(base + '?file=11/clip.mp4')
        page.wait_for_function("document.body.classList.contains('media')")
        vid = page.evaluate("""() => ({v: !document.getElementById('mvid').hidden,
                                        src: document.getElementById('mvid').getAttribute('src'),
                                        img: document.getElementById('mimg').hidden,
                                        raw: document.getElementById('rawbtn').hidden})""")
        check('mp4 открывается плеером, а не текстом, и кнопки «текст» у видео нет',
              vid['v'] and vid['src'] == '/11/clip.mp4' and vid['img'] and vid['raw'], str(vid))
        rr = urllib.request.urlopen(urllib.request.Request(base + '11/clip.mp4', headers={'Range': 'bytes=4-7'}))
        check('сервер отдаёт видео кусками (206), чтобы плеер перематывал',
              rr.status == 206 and rr.headers.get('Content-Range') == 'bytes 4-7/%d' % len(clip),
              str(rr.status) + ' ' + str(rr.headers.get('Content-Range')))
        lst = json.loads(urllib.request.urlopen(base + '__list').read().decode('utf-8'))
        check('картинки и видео видны в списке файлов',
              '11/pic.png' in lst['files'] and '11/clip.mp4' in lst['files'],
              str([f for f in lst['files'] if 'pic' in f or 'mp4' in f]))
        page.goto(base + '?file=11/pic.png')
        page.wait_for_function("document.body.classList.contains('media') && document.getElementById('mimg').naturalWidth > 0")
        ab = page.evaluate("() => ({hidden: document.getElementById('rawbtn').hidden, text: document.getElementById('rawbtn').textContent})")
        check('у картинки снизу есть кнопка «текст»', not ab['hidden'] and ab['text'] == 'текст', str(ab))
        page.click('#rawbtn')
        page.wait_for_function("!document.body.classList.contains('media') && document.getElementById('t').value.length > 100")
        raw = page.evaluate("""() => ({media: document.body.classList.contains('media'),
                                       pos: document.getElementById('pos').textContent,
                                       btn: document.getElementById('rawbtn').textContent,
                                       ro: document.getElementById('t').readOnly,
                                       len: document.getElementById('t').value.length,
                                       head: document.getElementById('t').value.slice(0, 40)})""")
        check('текст: файл картинки читается как в блокноте',
              'PNG' in raw['head'] and 'IHDR' in raw['head'] and raw['pos'] == 'картинка текстом'
              and raw['btn'] == 'картинка' and raw['ro'] and raw['len'] > 1000, str(raw))
        before = (root / '11' / 'pic.png').read_bytes()
        page.keyboard.press('Control+s')
        page.wait_for_timeout(250)
        lab = page.evaluate("document.getElementById('savelbl').textContent")
        check('текст картинки в png не пишется: только просмотр, байты целы',
              lab == 'только просмотр' and (root / '11' / 'pic.png').read_bytes() == before, lab)
        page.click('#rawbtn')
        page.wait_for_timeout(200)
        back = page.evaluate("() => ({media: document.body.classList.contains('media'), btn: document.getElementById('rawbtn').textContent, ro: document.getElementById('t').readOnly})")
        check('кнопка возвращает изображение с зумом', back['media'] and back['btn'] == 'текст' and not back['ro'], str(back))

        page.goto(base + '?file=VPN.md')
        page.wait_for_function("!document.body.classList.contains('media') && document.getElementById('t').value.length > 0")
        check('после медиа текстовый файл снова открывается текстом', True, '')

        vv = urllib.request.urlopen(base + '__version').read().decode('utf-8').strip()
        check('сервер отдаёт версию страницы для проверки устаревания', len(vv) > 5 and '-' in vv, vv)
        page.route('**/__version', lambda route: route.fulfill(status=200, body='999-999'))
        page.evaluate("checkVersion()")
        page.wait_for_timeout(600)
        st = page.evaluate("""() => ({shown: !document.getElementById('stale').hidden,
                                      text: document.getElementById('stale').textContent})""")
        check('новая версия на сервере: страница сама предупреждает и предлагает обновить',
              st['shown'] and 'обновить' in st['text'], str(st))
        page.unroute('**/__version')
        page.click('#viewbtn')
        page.wait_for_function("document.body.classList.contains('preview')")
        page.click('#bookbtn')
        page.wait_for_timeout(300)
        st2 = page.evaluate("""() => ({book: document.body.classList.contains('book'), preview: document.body.classList.contains('preview'),
                                       btn: document.getElementById('viewbtn').hidden})""")
        check('книга выключает просмотр и прячет кнопку просмотра', st2['book'] and not st2['preview'] and st2['btn'], str(st2))
        page.click('#bookbtn')
        page.wait_for_timeout(200)
        page.goto(base + '?file=notes.md')
        page.wait_for_timeout(300)
        check('кнопка просмотра есть только у md',
              page.evaluate("!document.getElementById('viewbtn').hidden"), 'notes.md')

        page.goto(base + '?file=no-such-file-xyz.md')
        page.wait_for_timeout(1200)
        miss = page.evaluate("""() => ({target: document.getElementById('target').textContent,
                                       fname: document.getElementById('fname').textContent,
                                       hint: document.body.classList.contains('hint'),
                                       card: document.querySelector('.hintcard') ? document.querySelector('.hintcard').textContent : null,
                                       len: document.getElementById('t').value.length})""")
        check('ненайденный файл говорит об этом, а не молчит пустым полем',
              'не нашёл' in miss['target'] and miss['fname'] == 'no-such-file-xyz.md', str(miss))
        check('ненайденный файл: в рабочей зоне карточка с ошибкой и что делать',
              miss['hint'] and 'не нашёл' in (miss['card'] or '') and 'Ctrl+P' in (miss['card'] or ''), str(miss['card']))
        page.goto(base + '?file=sub/notes.md')
        page.wait_for_timeout(1300)
        tw = page.evaluate("""() => ({target: document.getElementById('target').textContent,
                                      card: document.querySelector('.hintcard') ? document.querySelector('.hintcard').textContent : null})""")
        check('битый путь: сказано, что такой файл есть в другом месте',
              'есть: notes.md' in tw['target'] and 'есть: notes.md' in (tw['card'] or ''), str(tw))
        page.goto(base + '?file=deep/canon.md')
        page.wait_for_function("document.getElementById('t').value.length > 0")
        page.wait_for_timeout(600)
        sfx = page.evaluate("""() => ({fname: document.getElementById('fname').textContent,
                                       url: location.search,
                                       card: document.querySelector('.hintcard') ? document.querySelector('.hintcard').textContent : null})""")
        check('путь без начала (только хвост) открывается по уникальному концу, адрес исправляется сам',
              sfx['fname'] == 'canon.md' and sfx['url'] == '?file=11/deep/canon.md' and sfx['card'] is None, str(sfx))
        page.goto(base + '?file=11/11.txt')
        page.wait_for_function("document.getElementById('fname').textContent === '11.txt'")
        page.keyboard.press('Control+p')
        page.wait_for_selector('#nav:not([hidden])')
        page.wait_for_timeout(400)
        page.click('#navcrumbs button')
        page.wait_for_timeout(500)
        page.keyboard.type('deep')
        page.wait_for_function("document.querySelectorAll('#navlist .navitem').length >= 1")
        page.wait_for_timeout(300)
        deep_rows = page.eval_on_selector_all('#navlist .navitem', 'els => els.map(e => e.textContent)')
        check('обзор по имени ищет и по вложенным папкам, а не только в текущей',
              any('11/deep' in r for r in deep_rows), str(deep_rows))
        page.keyboard.press('Enter')
        page.wait_for_function("document.getElementById('fname').textContent === 'canon.md'")
        page.wait_for_timeout(400)
        check('поиск по имени открывает найденное в глубине и обновляет адрес',
              page.evaluate("location.search") == '?file=11/deep/canon.md',
              page.evaluate("location.search"))
        page.evaluate("localStorage.removeItem('txtviewer')")
        page.goto(base)
        page.wait_for_function("document.querySelector('.hintcard') !== null")
        empty_hint = page.evaluate("""() => ({hint: document.body.classList.contains('hint'),
                                              card: document.querySelector('.hintcard') ? document.querySelector('.hintcard').textContent : null})""")
        check('без файла: рабочая зона объясняет, с чего начать',
              empty_hint['hint'] and 'файл не открыт' in (empty_hint['card'] or '') and 'Ctrl+P' in (empty_hint['card'] or ''),
              str(empty_hint['card']))
        page.goto(base + '?file=empty.md')
        page.wait_for_timeout(1000)
        emp = page.evaluate("""() => ({target: document.getElementById('target').textContent,
                                      len: document.getElementById('t').value.length,
                                      cnt: document.getElementById('cnt').textContent})""")
        check('пустой файл открывается как пустой и без ошибки', emp['len'] == 0 and 'не нашёл' not in emp['target'], str(emp))

        long_name = 'very-long-overflow-filename-for-test-' + 'x' * 30 + '.txt'
        (root / long_name).write_text('длинное имя\n', encoding='utf-8')
        page.goto(base + '?file=' + long_name)
        page.wait_for_function("document.getElementById('fname').textContent.length > 40")
        page.wait_for_timeout(300)
        ov = page.evaluate("""() => { const f = document.getElementById('fname');
          return {ell: getComputedStyle(f).textOverflow, title: f.title, cut: f.scrollWidth > f.clientWidth + 1,
                  icons: document.querySelector('#navbtn use').getAttribute('href') + '|' + document.querySelector('#open use').getAttribute('href')}; }""")
        check('имя файла не раздувает бар: ellipsis и полное имя в title',
              ov['ell'] == 'ellipsis' and ov['title'] == long_name and ov['cut'], str(ov))
        check('иконки не близнецы: у «файлы» своё дерево, у «открыть» своя папка',
              ov['icons'].split('|')[0] != ov['icons'].split('|')[1] and 'folder-tree' in ov['icons'], str(ov['icons']))

        page.goto(base + '?file=search.txt')
        page.wait_for_function("document.getElementById('t').value.length > 0")
        page.wait_for_timeout(300)
        page.keyboard.press('Control+f')
        page.wait_for_function("!document.getElementById('findwrap').hidden")
        page.fill('#findin', 'яблоко')
        page.wait_for_timeout(300)
        check('поиск: нашёл все совпадения, стоит на первом', page.eval_on_selector('#findcnt', 'el => el.textContent') == '1 / 4',
              page.eval_on_selector('#findcnt', 'el => el.textContent'))
        page.press('#findin', 'Enter')
        page.wait_for_timeout(150)
        check('поиск: Enter вперёд', page.eval_on_selector('#findcnt', 'el => el.textContent') == '2 / 4',
              page.eval_on_selector('#findcnt', 'el => el.textContent'))
        page.press('#findin', 'Shift+Enter')
        page.wait_for_timeout(150)
        check('поиск: Shift+Enter назад', page.eval_on_selector('#findcnt', 'el => el.textContent') == '1 / 4',
              page.eval_on_selector('#findcnt', 'el => el.textContent'))
        page.keyboard.press('F3')
        page.wait_for_timeout(150)
        check('поиск: F3 листает совпадения', page.eval_on_selector('#findcnt', 'el => el.textContent') == '2 / 4',
              page.eval_on_selector('#findcnt', 'el => el.textContent'))
        hl = page.evaluate("""() => ({cur: CSS.highlights.get('find-cur') ? CSS.highlights.get('find-cur').size : -1,
                                      all: CSS.highlights.get('find') ? CSS.highlights.get('find').size : -1,
                                      line: document.getElementById('back').children[1].offsetTop,
                                      top: document.getElementById('t').scrollTop})""")
        check('поиск: совпадения подсвечены, текущее отдельно', hl['cur'] == 1 and hl['all'] >= 1, str(hl))
        check('поиск: прыжок доводит совпадение в окно', hl['line'] - hl['top'] >= 0, str(hl))
        page.fill('#findin', 'ЯБЛОКО')
        page.wait_for_timeout(250)
        check('поиск: без учёта регистра находит верхним регистром тоже',
              page.eval_on_selector('#findcnt', 'el => el.textContent').endswith('/ 4'),
              page.eval_on_selector('#findcnt', 'el => el.textContent'))
        page.click('#findcase')
        page.wait_for_timeout(250)
        check('поиск: Aa включает учёт регистра', page.eval_on_selector('#findcnt', 'el => el.textContent') == 'нет',
              page.eval_on_selector('#findcnt', 'el => el.textContent'))
        page.click('#findcase')
        page.wait_for_timeout(200)
        page.press('#findin', 'Escape')
        page.wait_for_timeout(250)
        esc = page.evaluate("""() => ({hidden: document.getElementById('findwrap').hidden,
                                       all: CSS.highlights.get('find') ? CSS.highlights.get('find').size : -1})""")
        check('поиск: Esc закрывает панель и снимает подсветку', esc['hidden'] and esc['all'] == 0, str(esc))
        page.keyboard.press('Control+f')
        page.fill('#findin', 'слива на последней')
        page.wait_for_timeout(250)
        page.click('#bookbtn')
        page.wait_for_function("document.body.classList.contains('book')")
        page.wait_for_timeout(300)
        before = book_counter(page)
        page.press('#findin', 'Enter')
        page.wait_for_timeout(300)
        after = book_counter(page)
        check('поиск в книге: прыжок перелистывает на страницу с совпадением', before != after, before + ' -> ' + after)
        page.click('#bookbtn')
        page.wait_for_timeout(200)

        g = json.loads(urllib.request.urlopen(base + '__grep?q=MARKER').read().decode('utf-8'))
        check('поиск по корню: json отдаёт файлы, строки и счётчики',
              g['files_total'] == 2 and g['hits_total'] == 2, str({k: g[k] for k in ('files_total', 'hits_total', 'truncated')}))
        g2 = json.loads(urllib.request.urlopen(base + '__grep?q=marker&case=1').read().decode('utf-8'))
        check('поиск по корню: учитывает регистр', g2['hits_total'] == 0, str(g2['hits_total']))

        page.keyboard.press('Control+p')
        page.wait_for_selector('#nav:not([hidden])')
        page.fill('#navgrep', 'marker')
        page.press('#navgrep', 'Enter')
        page.wait_for_function("document.querySelectorAll('#navlist .navitem .hittext').length >= 2")
        hits = page.eval_on_selector_all('#navlist .navitem', 'els => els.map(e => e.textContent)')
        check('поиск по корню: список показывает совпадения из разных файлов',
              any('search.txt:' in h for h in hits) and any('search2.txt:' in h for h in hits), str(hits))
        check('поиск по корню: надпись фильтра дерева не липнет к поиску',
              'фильтр' not in page.eval_on_selector('#navcrumbs', 'el => el.textContent')
              and 'поиск «marker»' in page.eval_on_selector('#navcrumbs', 'el => el.textContent')
              and '2 в 2' in page.eval_on_selector('#navcrumbs', 'el => el.textContent'),
              page.eval_on_selector('#navcrumbs', 'el => el.textContent'))
        page.click('#navlist .navitem:has(.hittext)')
        page.wait_for_function("document.getElementById('fname').textContent === 'search.txt'")
        page.wait_for_timeout(400)
        gh = page.evaluate("""() => ({find: !document.getElementById('findwrap').hidden,
                                      cnt: document.getElementById('findcnt').textContent,
                                      val: document.getElementById('findin').value,
                                      cur: CSS.highlights.get('find-cur') ? CSS.highlights.get('find-cur').size : -1,
                                      line: document.getElementById('back').children[4].offsetTop,
                                      top: document.getElementById('t').scrollTop})""")
        check('поиск по корню: клик открывает файл, ищет в нём и встаёт на строку',
              gh['find'] and gh['val'] == 'marker' and gh['cnt'] == '1 / 1' and gh['cur'] == 1 and gh['line'] - gh['top'] >= 0, str(gh))
        page.keyboard.press('Escape')
        page.wait_for_timeout(200)
        page.keyboard.press('Control+Shift+F')
        page.wait_for_selector('#nav:not([hidden])')
        page.wait_for_timeout(300)
        gf = page.evaluate("""() => ({focus: document.activeElement && document.activeElement.id,
                                      crumbs: document.querySelector('#navcrumbs').textContent})""")
        check('Ctrl+Shift+F открывает обзор и ставит курсор в поиск по корню',
              gf['focus'] == 'navgrep' and 'фильтр' not in gf['crumbs'], str(gf))
        page.keyboard.type('marker')
        page.wait_for_timeout(250)
        check('набор в поле поиска не уходит в фильтр дерева',
              page.eval_on_selector('#navgrep', 'el => el.value') == 'marker'
              and 'фильтр' not in page.eval_on_selector('#navcrumbs', 'el => el.textContent'),
              page.eval_on_selector('#navcrumbs', 'el => el.textContent'))
        page.keyboard.press('Escape')
        page.goto(base + '?file=big.py')
        page.wait_for_load_state('networkidle')
        page.wait_for_function("document.querySelector('#back .ln .hljs-number') !== null")
        far_before = page.evaluate("document.querySelectorAll('#back .ln')[3000].querySelectorAll('span').length")
        page.evaluate("document.getElementById('t').scrollTop = document.querySelectorAll('#back .ln')[3000].offsetTop")
        page.wait_for_timeout(400)
        far_after = page.evaluate("document.querySelectorAll('#back .ln')[3000].querySelectorAll('span').length")
        check('вьюпорт-подсветка: далёкая строка красится после скролла', far_before == 0 and far_after > 0,
              'до=%d после=%d' % (far_before, far_after))

        page.evaluate("document.getElementById('t').scrollTop = 0")
        page.click('#bookbtn')
        page.wait_for_function("document.body.classList.contains('book')")
        check('книга: кнопка показывает режим',
              page.eval_on_selector('#bookbtn', 'el => el.classList.contains("on") && el.getAttribute("aria-pressed") === "true"'))
        page.wait_for_timeout(400)
        num1 = book_counter(page)
        check('книга: счётчик 1 / N', num1.startswith('1 / ') and int(num1.split(' / ')[1]) > 1, num1)
        h1 = page.evaluate("Math.round(document.querySelector('.editor').getBoundingClientRect().height)")
        page.click('#bookr')
        page.wait_for_timeout(120)
        h2 = page.evaluate("Math.round(document.querySelector('.editor').getBoundingClientRect().height)")
        page.click('#bookl')
        page.wait_for_timeout(120)
        check('книга: карточка одной высоты на всех страницах', h1 == h2, '%d vs %d' % (h1, h2))
        grid = page.evaluate("""(() => {
          const lns = Array.from(document.querySelectorAll('#back .ln'));
          const pitch = Math.min.apply(null, lns.map(l => l.offsetHeight).filter(h => h > 0));
          const offTop = lns.filter(l => Math.abs((l.offsetTop / pitch) % 1) * pitch >= 0.5).length;
          const offH = lns.filter(l => Math.abs((l.offsetHeight / pitch) % 1) * pitch >= 0.5).length;
          const card = getComputedStyle(document.querySelector('.editor')).boxShadow !== 'none';
          return {pitch: pitch, tops: offTop, heights: offH, card: card};
        })()""")
        check('книга: все строки по сетке одной высоты (границы страниц не режут строки)',
              grid['tops'] == 0 and grid['heights'] == 0 and grid['card'], str(grid))
        page.set_viewport_size({'width': 1100, 'height': 640})
        page.wait_for_timeout(400)
        rs = page.evaluate("""(() => {
          const lns = Array.from(document.querySelectorAll('#back .ln'));
          const pitch = parseFloat(getComputedStyle(document.documentElement).getPropertyValue('--book-lhp'));
          return {pitch: pitch, bad: lns.filter(l => Math.abs((l.offsetTop / pitch) % 1) > 0.02).length,
                  card: Math.round(document.querySelector('.editor').getBoundingClientRect().height),
                  main: document.querySelector('main').clientHeight};
        })()""")
        check('книга: после ресайза окна сетка держится, карточка в окне',
              rs['pitch'] > 0 and rs['bad'] == 0 and rs['card'] <= rs['main'] + 1, str(rs))
        page.set_viewport_size({'width': 1280, 'height': 720})
        page.wait_for_timeout(400)
        sep = page.evaluate("""(() => {
          const cs = getComputedStyle(document.querySelector('.editor'), '::before');
          return cs.width + '|' + cs.backgroundColor;
        })()""")
        check('гаттер отделён линией', sep.startswith('1px') and 'rgba(0, 0, 0, 0)' not in sep, sep)

        page.mouse.move(450, 220)
        page.mouse.wheel(0, 400)
        page.wait_for_timeout(200)
        numw = book_counter(page)
        check('книга: колесо не листает и не скроллит', numw.startswith('1 / '), numw)
        page.click('#bookr')
        page.wait_for_timeout(80)
        num2 = book_counter(page)
        instant = page.evaluate("""(() => {
          const t = document.getElementById('t');
          return Math.abs(t.scrollTop - bookTarget()) < 1;
        })()""")
        check('книга: вправо листает мгновенно', num2.startswith('2 / ') and instant, num2)
        page.evaluate("document.getElementById('t').scrollTop += 40")
        page.wait_for_timeout(150)
        snapped = page.evaluate("""(() => {
          const t = document.getElementById('t');
          return Math.abs(t.scrollTop - bookTarget()) < 1;
        })()""")
        check('книга: свободный скролл не пробивает страницу', bool(snapped))
        page.click('#bookl')
        page.wait_for_timeout(400)
        num3 = book_counter(page)
        check('книга: влево возвращает', num3.startswith('1 / '), num3)

        page.fill('#bookpage', '3')
        page.press('#bookpage', 'Enter')
        page.wait_for_timeout(250)
        num5 = book_counter(page)
        check('книга: ввод номера страницы', num5.startswith('3 / '), num5)
        pos3 = page.eval_on_selector('#pos', 'el => el.textContent')
        check('книга: в статусе строка с текущей страницы, а не каретка', pos3.startswith('строка ') and int(pos3.split()[1]) > 1, pos3)
        page.fill('#bookpage', '1')
        page.press('#bookpage', 'Enter')
        page.wait_for_timeout(250)
        num6 = book_counter(page)
        check('книга: возврат на первую', num6.startswith('1 / '), num6)
        page.keyboard.press('ArrowRight')
        page.wait_for_timeout(400)
        num4 = book_counter(page)
        check('книга: стрелка вправо листает', num4.startswith('2 / '), num4)
        page.click('#bookbtn')
        check('книга: режим выключается',
              page.evaluate("!document.body.classList.contains('book')")
              and page.eval_on_selector('#bookbtn', 'el => !el.classList.contains("on")'))
        page.click('#theme')
        page.wait_for_timeout(350)

        page.keyboard.press('Control+p')
        page.wait_for_selector('#nav:not([hidden])')
        check('навигатор открывается', page.is_visible('#navpanel'))
        page.wait_for_function("document.querySelectorAll('#navlist .navitem').length >= 1")
        rows = page.eval_on_selector_all('#navlist .navitem', 'els => els.map(e => e.textContent)')
        check('навигатор видит .py', any('tool.py' in r for r in rows), str(rows))
        check('навигатор видит Dockerfile', any('Dockerfile' in r for r in rows), str(rows))
        page.click('.navitem:has-text("11")')
        page.wait_for_function("document.querySelector('#navcrumbs').textContent.includes('11')")
        page.click('.navitem:has-text("11.txt")')
        page.wait_for_function("document.getElementById('fname').textContent === '11.txt'")
        check('навигатор: файл открыт из папки',
              page.eval_on_selector('#target', 'el => el.textContent').endswith('11/11.txt')
              and page.evaluate('location.search') == '?file=11/11.txt', repr(page.evaluate('location.search')))
        check('навигатор закрылся после открытия', page.eval_on_selector('#nav', 'el => el.hidden'))
        page.keyboard.press('Control+p')
        page.wait_for_selector('#nav:not([hidden])')
        page.wait_for_function("document.querySelectorAll('#navcrumbs button').length === 2")
        page.keyboard.press('Backspace')
        page.wait_for_function("document.querySelectorAll('#navcrumbs button').length === 1")
        page.keyboard.type('VPN')
        page.wait_for_function("document.querySelectorAll('#navlist .navitem').length === 1"
                               " && document.querySelector('#navlist .navitem').textContent.includes('VPN.md')")
        page.keyboard.press('Enter')
        page.wait_for_function("document.getElementById('fname').textContent === 'VPN.md'")
        check('навигатор: Backspace, фильтр и Enter открыли VPN.md',
              page.evaluate('location.search') == '?file=VPN.md', repr(page.evaluate('location.search')))
        page.keyboard.press('Control+p')
        page.wait_for_selector('#nav:not([hidden])')
        page.wait_for_timeout(400)
        page.keyboard.type('notes')
        page.wait_for_function("document.querySelectorAll('#navlist .navitem').length === 1"
                               " && document.querySelector('#navlist .navitem').textContent.includes('notes.md')")
        check('обзор: набор имени фильтрует дерево и виден в поле',
              page.eval_on_selector('#pathin', 'el => el.value') == 'notes'
              and 'фильтр' in page.eval_on_selector('#navcrumbs', 'el => el.textContent'),
              page.eval_on_selector('#navcrumbs', 'el => el.textContent'))
        page.keyboard.press('Enter')
        page.wait_for_function("document.getElementById('fname').textContent === 'notes.md'")
        page.wait_for_timeout(300)
        check('обзор: Enter открыл файл из фильтра', page.evaluate('location.search') == '?file=notes.md',
              repr(page.evaluate('location.search')))
        (root / 'empty dir').mkdir(exist_ok=True)
        page.keyboard.press('Control+p')
        page.wait_for_selector('#nav:not([hidden])')
        page.wait_for_timeout(400)
        page.fill('#pathin', str(root) + '/empty dir')
        page.press('#pathin', 'Enter')
        page.wait_for_function("document.querySelector('#navcrumbs').textContent.includes('empty dir')")
        page.wait_for_timeout(400)
        es = page.evaluate("""() => { const d = document.querySelector('#navlist .navempty');
          return {main: d ? d.firstChild.textContent : null, hint: d ? d.querySelector('.navempty2').textContent : null}; }""")
        check('пустая папка: внятный empty state с подсказкой',
              es['main'] == 'папка пуста' and 'Backspace' in (es['hint'] or ''), str(es))
        page.fill('#pathin', 'zzz-no-such')
        page.wait_for_timeout(300)
        nf = page.evaluate("""() => { const d = document.querySelector('#navlist .navempty');
          return {main: d ? d.firstChild.textContent : null, hint: d ? d.querySelector('.navempty2').textContent : null}; }""")
        check('фильтр без совпадений: подсказка про путь и Esc',
              'zzz-no-such' in (nf['main'] or '') and 'Enter' in (nf['hint'] or ''), str(nf))
        page.press('#pathin', 'Enter')
        try:
            page.wait_for_function("document.getElementById('pathin').placeholder.includes('не нашёл')"
                                   " || document.getElementById('target').textContent.includes('не нашёл')", timeout=6000)
            seen = True
        except Exception:
            seen = False
        check('Enter по имени без совпадений пробует открыть его как путь',
              seen, page.eval_on_selector('#pathin', 'el => el.placeholder') + ' | ' + page.eval_on_selector('#target', 'el => el.textContent'))
        page.keyboard.press('Control+Shift+F')
        page.fill('#navgrep', 'неттакогослованигде')
        page.press('#navgrep', 'Enter')
        page.wait_for_function("document.querySelector('#navlist .navempty') !== null")
        page.wait_for_timeout(300)
        gs = page.evaluate("""() => { const d = document.querySelector('#navlist .navempty');
          return {main: d.firstChild.textContent, hint: d.querySelector('.navempty2').textContent}; }""")
        check('поиск по корню без совпадений: сколько просканировал и что дальше',
              'ничего нет' in gs['main'] and 'просмотрел' in gs['hint'] and 'Esc' in gs['hint'], str(gs))
        page.keyboard.press('Escape')
        page.wait_for_function("document.getElementById('nav').hidden")
        page.keyboard.press('Control+p')
        page.wait_for_selector('#nav:not([hidden])')
        page.wait_for_timeout(300)
        page.click('#navcrumbs button')
        page.wait_for_timeout(400)
        page.keyboard.press('Escape')
        page.wait_for_function("document.getElementById('nav').hidden")
        page.keyboard.press('Control+p')
        page.wait_for_selector('#nav:not([hidden])')
        page.wait_for_timeout(400)
        box = page.locator('#navlist').bounding_box()
        pg_wheel = page.evaluate("""() => {
          window.__wheel = [];
          window.addEventListener('wheel', e => {
            const rec = {t: (e.target.id || e.target.className || e.target.tagName), p: null};
            window.__wheel.push(rec);
            setTimeout(() => { rec.p = e.defaultPrevented; }, 0);
          }, true);
          return {ta: Math.round(document.getElementById('t').scrollTop), sel: navSel,
                  count: navFiltered().length};
        }""")
        page.evaluate("navSel = 0; renderNav();")
        box = page.locator('#navlist').bounding_box()
        page.mouse.move(box['x'] + box['width'] / 2, box['y'] + box['height'] / 2)
        page.mouse.wheel(0, 120)
        page.wait_for_timeout(200)
        w1 = page.evaluate("""() => ({sel: navSel, ta: Math.round(document.getElementById('t').scrollTop),
                                      last: window.__wheel[window.__wheel.length - 1]})""")
        page.mouse.move(box['x'] + 20, box['y'] - 90)
        page.mouse.wheel(0, 120)
        page.wait_for_timeout(200)
        w2 = page.evaluate("""() => ({sel: navSel, ta: Math.round(document.getElementById('t').scrollTop),
                                      last: window.__wheel[window.__wheel.length - 1]})""")
        page.mouse.move(20, 700)
        page.mouse.wheel(0, -120)
        page.wait_for_timeout(200)
        w3 = page.evaluate("""() => ({sel: navSel, ta: Math.round(document.getElementById('t').scrollTop),
                                      last: window.__wheel[window.__wheel.length - 1]})""")
        check('обзор: колесо двигает выбор по списку, как стрелки, и не трогает страницу под модалкой',
              w1['sel'] == 1 and w2['sel'] == 2 and w3['sel'] == 1
              and w1['ta'] == 0 and w2['ta'] == 0 and w3['ta'] == 0
              and w2['last']['p'] is True and w3['last']['p'] is True,
              'старт %s, над списком %s, над полями %s, над фоном %s' % (pg_wheel, w1, w2, w3))
        page.keyboard.press('PageDown')
        page.wait_for_timeout(200)
        check('обзор: PageDown листает выбор по списку', page.evaluate("navSel") > 0, str(page.evaluate('navSel')))
        page.evaluate("document.activeElement.blur()")
        page.keyboard.press('End')
        page.wait_for_timeout(200)
        check('обзор: End уводит выбор в конец списка',
              page.evaluate("navSel") == page.evaluate("navFiltered().length - 1"), str(page.evaluate('navSel')))
        page.keyboard.press('Home')
        page.wait_for_timeout(200)
        check('обзор: Home возвращает выбор в начало', page.evaluate("navSel") == 0, str(page.evaluate('navSel')))
        page.keyboard.press('Escape')
        page.wait_for_function("document.getElementById('nav').hidden")
        page.keyboard.press('Control+p')
        page.wait_for_selector('#nav:not([hidden])')
        page.keyboard.press('Escape')
        check('навигатор закрывается по Esc', page.eval_on_selector('#nav', 'el => el.hidden'))

        page.keyboard.press('Control+p')
        page.wait_for_selector('#nav:not([hidden])')
        root_abs = page.evaluate('rootPath')
        page.fill('#pathin', root_abs + '/11/11.txt')
        page.press('#pathin', 'Enter')
        page.wait_for_function("document.getElementById('fname').textContent === '11.txt'")
        check('путь: файл открылся', page.evaluate('location.search') == '?file=11/11.txt',
              repr(page.evaluate('location.search')))
        page.keyboard.press('Control+p')
        page.wait_for_selector('#nav:not([hidden])')
        page.fill('#pathin', root_abs + '/11')
        page.press('#pathin', 'Enter')
        page.wait_for_function("document.querySelector('#navcrumbs').textContent.includes('11')")
        page.wait_for_function("document.querySelector('#navlist').textContent.includes('11.txt')")
        rows2 = page.eval_on_selector_all('#navlist .navitem', 'els => els.map(e => e.textContent)')
        check('путь: папка открылась в обзоре', any('11.txt' in r for r in rows2), str(rows2))

        page.evaluate("""() => {
          const of = window.fetch;
          window._of = of;
          window.fetch = (u, o) => u === '/__tree?dir=' ? new Promise(res => setTimeout(() => res(of(u, o)), 500)) : of(u, o);
        }""")
        page.keyboard.press('Escape')
        page.keyboard.press('Control+p')
        page.wait_for_selector('#nav:not([hidden])')
        page.fill('#pathin', root_abs + '/11')
        page.press('#pathin', 'Enter')
        page.wait_for_timeout(1100)
        rows3 = page.eval_on_selector_all('#navlist .navitem', 'els => els.map(e => e.textContent)')
        page.evaluate("window.fetch = window._of")
        check('навигатор: ответ корня, пришедший позже, не перетирает открытую папку',
              any('11.txt' in r for r in rows3), str(rows3))
        outside = pathlib.Path(tempfile.gettempdir()) / ('viewer-outside-%d.txt' % os.getpid())
        outside.write_text('внешний файл, только чтение\n', encoding='utf-8')
        page.fill('#pathin', str(outside))
        page.press('#pathin', 'Enter')
        page.wait_for_function("document.getElementById('fname').textContent === %r" % outside.name)
        check('путь: файл вне корня открылся только на чтение',
              'только чтение' in page.eval_on_selector('#target', 'el => el.textContent'),
              page.eval_on_selector('#target', 'el => el.textContent'))
        page.keyboard.press('Control+s')
        page.wait_for_timeout(300)
        check('путь: запись во внешний файл отбита',
              outside.read_text(encoding='utf-8') == 'внешний файл, только чтение\n'
              and page.eval_on_selector('#save', 'el => el.textContent') == 'только чтение')
        page.keyboard.press('Control+p')
        page.wait_for_selector('#nav:not([hidden])')
        page.fill('#pathin', str(outside.parent))
        page.press('#pathin', 'Enter')
        page.wait_for_function("document.querySelector('#navcrumbs').textContent.startsWith('/')")
        page.wait_for_function("document.querySelectorAll('#navlist .navitem').length >= 1")
        rows3 = page.eval_on_selector_all('#navlist .navitem', 'els => els.map(e => e.textContent)')
        check('путь: папка вне корня листается в обзоре', any(outside.name in r for r in rows3),
              'крошки: ' + page.eval_on_selector('#navcrumbs', 'el => el.textContent'))
        page.fill('#pathin', '/etc/passwd')
        page.press('#pathin', 'Enter')
        page.wait_for_timeout(500)
        check('путь: не-текстовый файл отбит', 'не текст' in page.eval_on_selector('#pathin', 'el => el.placeholder'),
              page.eval_on_selector('#pathin', 'el => el.placeholder'))
        page.keyboard.press('Escape')
        outside.unlink(missing_ok=True)

        page.goto(base)
        page.wait_for_load_state('networkidle')
        page.wait_for_function("document.getElementById('t').value.length > 0")
        check('память вернула последний файл', page.eval_on_selector('.bar b', 'el => el.textContent') == '11.txt',
              page.eval_on_selector('.bar b', 'el => el.textContent'))

        page.goto('file://' + str(HERE / 'index.html'))
        page.wait_for_load_state('load')
        check('file:// без сбоев js', not page.eval_on_selector('#cnt', 'el => el.textContent').startswith('сбой'))
        check('file:// иконки отрисованы', page.evaluate("document.querySelector('#theme use').getBBox().width > 0"))
        check('file:// писать некуда', 'некуда' in page.eval_on_selector('#target', 'el => el.textContent'))
        bg_file = body_bg(page)
        page.click('#theme')
        page.wait_for_timeout(300)
        check('file:// тема переключается', body_bg(page) != bg_file)
        page.click('#bookbtn')
        page.wait_for_function("document.body.classList.contains('book')")
        page.wait_for_timeout(300)
        check('file:// книга включается на статичной странице',
              page.eval_on_selector('#bookbtn', 'el => el.classList.contains("on")')
              and not page.eval_on_selector('#booknum', 'el => el.hidden'))
        fgrid = page.evaluate("""(() => {
          const lns = Array.from(document.querySelectorAll('#back .ln'));
          const pitch = parseFloat(getComputedStyle(document.documentElement).getPropertyValue('--book-lhp'));
          return {pitch: pitch, bad: lns.filter(l => Math.abs((l.offsetTop / pitch) % 1) > 0.02).length,
                  card: Math.round(document.querySelector('.editor').getBoundingClientRect().height),
                  main: document.querySelector('main').clientHeight};
        })()""")
        check('file:// книга: строки по сетке, карточка в окне',
              fgrid['pitch'] > 0 and fgrid['bad'] == 0 and fgrid['card'] <= fgrid['main'] + 1, str(fgrid))

        browser.close()

    # статичный хостинг без нашего сервера: показываем вшитый демо-текст
    plain_port = free_port()
    plain = subprocess.Popen([sys.executable, '-m', 'http.server', str(plain_port), '--bind', '127.0.0.1', '--directory', str(HERE)],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        time.sleep(1)
        with sync_playwright() as p2:
            b2 = p2.chromium.launch(channel='chrome', headless=True)
            sp = b2.new_page()
            sp.goto('http://127.0.0.1:%d/' % plain_port)
            sp.wait_for_load_state('networkidle')
            sp.wait_for_function("document.getElementById('t').value.length > 0", timeout=10000)
            check('без сервера: показывается вшитый демо-текст',
                  sp.eval_on_selector('#t', 'el => el.value.length') > 10 and not sp.is_visible('#navbtn'),
                  'len=%d' % sp.eval_on_selector('#t', 'el => el.value.length'))
            b2.close()
    finally:
        plain.terminate()
        try:
            plain.wait(timeout=5)
        except Exception:
            plain.kill()
except Exception:
    try:
        page.screenshot(path='/tmp/opencode/viewer_test_fail.png')
    except Exception:
        pass
    raise
finally:
    srv.terminate()
    try:
        srv.wait(timeout=5)
    except Exception:
        srv.kill()
    shutil.rmtree(root, ignore_errors=True)

def _lum(h):
    c = [int(h[i:i + 2], 16) / 255 for i in (1, 3, 5)]
    c = [x / 12.92 if x <= 0.03928 else ((x + 0.055) / 1.055) ** 2.4 for x in c]
    return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]


def _cr(a, b):
    la, lb = _lum(a), _lum(b)
    return (max(la, lb) + 0.05) / (min(la, lb) + 0.05)


html_src = (HERE / 'index.html').read_text(encoding='utf-8')
for tname, pattern in (('тёмная', r':root\{(.*?)\n\}'), ('светлая', r'html\.light\{(.*?)\n\}')):
    block = re.search(pattern, html_src, re.S).group(1)
    vals = dict(re.findall(r'(--[\w-]+):(#[0-9a-fA-F]{6})', block))
    bg, panel, fg, acc = vals['--bg'], vals['--panel'], vals['--fg'], vals['--acc']
    worst = min(_cr(vals[k], bg) for k in vals if k.startswith('--tok-') or k in ('--dim', '--acc'))
    check('палитра %s: текст AAA, приглушённое и токены AA, подпись на акценте AA, без чистого белого и чёрного' % tname,
          _cr(fg, bg) >= 7 and _cr(fg, panel) >= 7 and worst >= 4.5 and _cr(bg, acc) >= 4.5
          and bg not in ('#ffffff', '#000000') and fg not in ('#ffffff', '#000000'),
          'fg %.2f, худший токен %.2f, подпись на акценте %.2f' % (_cr(fg, bg), worst, _cr(bg, acc)))

print('ИТОГ:', 'всё зелёное' if not FAILED else 'упало: ' + ', '.join(FAILED), flush=True)
sys.exit(1 if FAILED else 0)
