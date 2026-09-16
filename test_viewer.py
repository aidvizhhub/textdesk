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
import sys
import tempfile
import time
import urllib.request

from playwright.sync_api import sync_playwright

HERE = pathlib.Path(__file__).resolve().parent
FAILED = []


def check(name, cond, info=''):
    print(('OK   ' if cond else 'FAIL ') + name + ((' — ' + info) if info else ''), flush=True)
    if not cond:
        FAILED.append(name)


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
        page.click('#wrapbtn')
        page.wait_for_timeout(300)
        check('перенос включается обратно', page.evaluate("document.getElementById('t').getAttribute('wrap') === 'soft' && !document.body.classList.contains('nowrap')"))

        page.click('#wrapbtn')
        page.wait_for_timeout(250)
        clipped = page.evaluate("(() => { const l = document.getElementById('back').children[0]; return l.scrollWidth > l.clientWidth + 1; })()")
        check('перенос выкл: длинная строка вылезает за колонку', bool(clipped))
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

print('ИТОГ:', 'всё зелёное' if not FAILED else 'упало: ' + ', '.join(FAILED), flush=True)
sys.exit(1 if FAILED else 0)
