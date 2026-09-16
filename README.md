# textdesk

локальный веб-просмотрщик и редактор текстовых файлов. открываешь в браузере, правишь, `Ctrl+S` — правки уходят прямо в файл на диске. снаружи корня сервера — только чтение.

![редактор](docs/editor.png)
![режим книги](docs/book.png)

## что умеет
- подсветка кода на highlight.js: ~140 языков, дев-файлы (Dockerfile, Makefile, .env, .gitignore и др.)
- режим книги: страницы с мгновенным переворотом, счётчик `2 / 134`, стрелки ‹ ›, клавиши ←/→, PgUp/PgDn; колесо в книге молчит, длинные строки переносятся, продолжения с отступом 2ch, страница — ровно N строк экрана (все одной высоты, граница кратна строке, поэтому строки не режутся)
- навигатор по папкам: крошки, фильтр с клавиатуры, поле пути (абсолютный путь к файлу или папке)
- вне корня сервера — только чтение (`/__file`, `/__dir`), `/proc /sys /dev` закрыты
- колонка номеров строк, темы светлая/тёмная, размер шрифта `A±` (11–24px), память последнего файла
- запись защищена: только текстовые расширения, только внутрь корня, сверка Origin, подтверждение на затирание пустым текстом

## быстрый старт

```
cd textdesk
python3 serve.py            # корень по умолчанию — на две папки выше
python3 serve.py 8792 /path/to/workspace
```

открой http://127.0.0.1:8792/ — сервер сам предложит браузер. файл выбирай кнопкой «открыть файл…» или полем пути в обзоре «файлы» (`Ctrl+P`).

статичный снимок без сервера: открой `index.html` файлом (двойной клик) или [github pages](https://aidvizhhub.github.io/textdesk/) — там только чтение и вшитый демо-текст.

## сборка страницы под свой текст

```
python3 gen.py ../notes.txt        # вшивает notes.txt в index.html как стартовый холст
```

## автозапуск (systemd user)

```
cp contrib/textdesk.service ~/.config/systemd/user/
sed -i "s|/path/to/textdesk|$(pwd)|g" ~/.config/systemd/user/textdesk.service
systemctl --user daemon-reload
systemctl --user enable --now textdesk
```

логи: `journalctl --user -u textdesk -f`, выключить: `systemctl --user disable --now textdesk`.
чтобы сервер поднимался до логина (при загрузке системы): `sudo loginctl enable-linger $USER`.
флаг `--no-browser` в юните гасит автозапуск браузера — при старте вкладки не всплывают.

## тесты

```
pip install playwright
python3 test_viewer.py             # поднимает сервер на временном корне и гоняет браузер
```

нужен системный chrome (playwright запускается с `channel='chrome'`, браузеры не качает).

## лицензия

MIT. сторонние компоненты — [THIRD_PARTY.md](THIRD_PARTY.md).

---

# textdesk (EN)

A tiny local web text/code viewer and editor. Run `python3 serve.py`, open `http://127.0.0.1:8792/`, edit files in the browser; `Ctrl+S` writes them to disk. Only text files inside the server root are writable — everything outside the root is read-only. Code highlighting via vendored highlight.js, a book mode with instant page flips, light/dark themes. MIT license.
