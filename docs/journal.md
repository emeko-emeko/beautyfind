# Журнал: beautyfind (ветка claude/eloquent-pascal-k1a8u1)

## Коммиты этой сессии (по порядку)
- 78e8053 — Код де ви, Viled, Space NK, Cult Beauty как «pending» магазины; пересчёт EUR→₸ (EUR_TO_KZT = 509.99, курс НБ РК на 7.10.2026, обновлять вручную); тесты на сохранённом HTML
- 960d634 — подключены Код де ви и Viled (search_url `/women/search?searchQuery={query}`)
- ec413e5 — флаг «Unable to ship to Kazakhstan» (`restricted_sel`), пометка в сообщении бота
- ebf72fb — подключён Cult Beauty (`cultbeauty.com/search/?q={query}`)
- 9fb3c28 — подключён Space NK (`spacenk.com/uk/search?q={query}&search-button=&lang=en_GB`)
- eb71712 — удалено сообщение «⚠️ магазин: недоступен» (сообщение «Магазины не ответили» оставлено); отслеживание цен: `/watch` со списком и отменой, фоновый watcher каждые 10 мин, уведомления о изменении цены
- 06136fa — обработчик страницы товара Cult Beauty (цена EUR → ₸, исходная сумма в `price_native`)
- 9c5256a — обработчик страницы товара Space NK (цена уже в ₸, `.product-detail__prices .value`)

## Текущее состояние
Подключено 8 магазинов в STORES: Mon Amie, Золотое Яблоко, Французский дом, Yves Rocher, Код де ви, Viled, Cult Beauty, Space NK. PENDING_STORES пуст.

Кнопка «Отслеживать цену» есть у всех 8 магазинов: обработчики страницы товара добавлены для Код де ви (`detail_kodedevie`) и Viled (`detail_viled`, объём из активной кнопки «30 мл» / «50 мл»).
Код де ви: цена 13 860 ₸ со скидкой, без скидки 19 800 ₸. Файл `code de vie.txt` повреждён (нет `<`, `>`, `"`), тест на нём построен по воспроизведённой разметке.

Плашка «Unable to ship to Kazakhstan» (`h5.unavailable-notice`) распознаётся только у Space NK. У Cult Beauty образца нет.

## Ключевые файлы
- cosmetics_bot/src/scraping/stores.py — записи Store, STORES / PENDING_STORES
- cosmetics_bot/src/scraping/details.py — DETAIL_HANDLERS (monamie, goldapple, frenchhouse, yvesrocher, cultbeauty, spacenk)
- cosmetics_bot/src/scraping/search.py — EXTRACT_JS, _build_candidate (пересчёт валюты, restricted)
- cosmetics_bot/src/core/models.py — Store (price_currency, fx_to_kzt, restricted_sel), Candidate
- cosmetics_bot/src/core/utils.py — EUR_TO_KZT
- cosmetics_bot/src/core/db.py — watches (volume, add_watch с заменой дубля, remove_watch)
- cosmetics_bot/src/telegram/watcher.py — фоновая проверка цен и уведомления
- cosmetics_bot/src/telegram/bot.py — /watch, wdel:, кнопка watch только для поддерживаемых магазинов
- cosmetics_bot/src/ui/formatter.py — price_text (₸ + ≈ € в скобках), пометка «Доставка в Казахстан невозможна»
- main.py — запуск watch_loop через asyncio.create_task
- Тесты: cosmetics_bot/tests/test_new_stores.py, test_watch.py, test_bot_search.py (обновлён под отсутствие сообщения о недоступности)

## Открытые вопросы и задачи
1. Код де ви: пересохранить страницу товара как HTML (`code de vie.txt` без тегов), затем заменить тест на реальной разметке. Viled: смена варианта кнопкой «50 мл» не проверена на живом сайте (в файле только активный вариант).
2. Курс EUR_TO_KZT = 509.99 устарел (октябрь 2026). Нужен актуальный курс, поправить вручную.
3. Не проверено на живых сайтах: селекторы карточек выдачи поиска для Space NK, Код де ви, Viled, Cult Beauty (сохранённые примеры были с категорий и брендов). Проверить через бота запросом типа «lips» / «pencil».
4. Watcher не проверен на живом боте (тесты только логики на подставных данных). Проверить: подписаться на товар, подождать 10–30 мин.
5. Плашка доставки для Cult Beauty: нужен HTML карточки/страницы с этой плашкой.
6. Выбор оттенка на Space NK: обработчик берёт цену текущего выбранного оттенка, при смене оттенка не проверено.
7. Предложено, не сделано (нужно подтверждение): добавить `__pycache__/` в .gitignore.
8. Существующая проблема: main.py на Linux — msvcrt = None, блокировка файла упадёт. Не трогал.
9. Подключение бота к Telegram в тестах не проверялось.

## Окружение для тестов (важно)
- Системный Python без playwright/aiogram. Установлено в scratchpad:
  - pylib (playwright 1.63.0 — совпадает с браузером /opt/pw-browsers, версия из /opt/node-tools)
  - pylib2 (aiogram, python-dotenv)
- Запуск: `PYTHONPATH=<scratchpad>/pylib2:<scratchpad>/pylib:. PYTHONDONTWRITEBYTECODE=1 python3 -m unittest cosmetics_bot.tests.<модуль>`
- ПОСЛЕ тестов: `git checkout -- cosmetics_bot/data/bot.db` (импорт bot.py вызывает init_db и меняет трекаемый файл) и удалить `*.cpython-313.pyc`, иначе они попадут в «untracked».
- `python3 -c "import ..."` без PYTHONDONTWRITEBYTECODE тоже создаёт pyc — это уже случалось.

## Правила, которые соблюдались
- Коммиты и пуши только в claude/eloquent-pascal-k1a8u1.
- Строку Co-Authored-By с названием модели в коммитах не писать (системная инструкция). Строка Claude-Session есть.
- Адреса поиска брались только из присланных пользователем ссылок, ничего не угадывалось.
- Сайты из окружения недоступны (прокси 403), поэтому разметка берётся только из присланного HTML.
