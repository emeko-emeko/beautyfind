# Журнал изменений проекта beautyfind

Правила ведения журнала — см. `CLAUDE.md`. Каждая запись: дата, что сделано, почему, где, кто принял решение.

Статусы решений: **открыто** (ждёт ответа), **окончательно** (решил владелец), **оспорено** (есть возражение, решение пока не принято).

---

## 2026-11-13

### 001 — Анализ запуска на Vercel (только анализ, ничего не задеплоено)
- **Что:** проверен запуск `main.py` на Linux. Падает с `AttributeError` на `msvcrt.locking`, потому что `msvcrt` есть только в Windows.
- **Почему:** Vercel не подходит для бота с long polling и Playwright; нужен либо webhook, либо обычный воркер-хостинг.
- **Где:** `main.py`, `requirements.txt`, `Dockerfile`.
- **Решение:** Vercel отложен. Проект на Vercel не создавался.
- **Кто решил:** владелец (выбор Railway/Supabase — см. запись 003).

### 002 — Очистка случайных файлов
- **Что:** удалены `cosmetics_bot/**/*.cpython-313.pyc`, созданные моим запуском `main.py`. Git-дерево стало чистым.
- **Почему:** кэш байткода не должен попадать в коммиты.
- **Кто решил:** я (Claude), по замечанию stop-hook. Владелец не возражал.

### 003 — Переход на Supabase и выбор хостинга: Railway
- **Что:** в Supabase найден проект `emeko-emeko's Project` (`aqlbpakvqkvlbcztbbgg`, eu-west-1, ACTIVE, таблиц пока нет). Railway подключён, аккаунт `emeko-emeko`.
- **Почему Railway:** в репозитории уже есть `start.sh` и `Dockerfile`, а Railway умеет держать долгоживущий процесс с Playwright. Vercel для этого не подходит (см. запись 001).
- **Решение:** Railway — хостинг. Supabase — база.
- **Статус:** окончательно (выбор владельца: «выбери хостинг сам, по удобству»).

### 004 — Найдены существующие сервисы Railway, оба в статусе FAILED
- **Что:**
  - проект `jubilant-wholeness`, сервис `beautyfind` (репозиторий `emeko-emeko/beautyfind`, ветка `main`), последний деплой FAILED;
  - проект `observant-achievement`, сервис `telegram-bot` (тот же репозиторий, ветка `main`), последний деплой FAILED.
- **Почему важно:** оба падают, скорее всего из-за `msvcrt` (запись 001).
- **Решение:** ничего не менял. Жду указания, использовать ли их или создать новый сервис.
- **Статус:** открыто.

### 005 — Расхождение схемы SQLite (`watches`)
- **Что:** в `cosmetics_bot/data/bot.db` таблица `watches` создана по старой схеме (`target_price`, `created_at`). Код (`src/core/db.py`) ожидает `initial_price`, `last_price`, `last_check`, `product_url`, `title`. Из-за `CREATE TABLE IF NOT EXISTS` старая схема не пересоздаётся, и `add_watch` упал бы.
- **Данные в SQLite:** `price_cache` — 21 строка, `favorites` — 3 строки, `watches` — 0 строк.
- **Решение:** при переносе в Supabase создаю таблицы по актуальной схеме кода и переношу данные. Старую схему не переношу.
- **Статус:** принято мной как план, ждёт подтверждения владельца при переносе данных.

### 006 — Доступ к базе с сервера
- **Что:** публичных ключей Supabase (anon/publishable) достаточно для чтения, но не для безопасной записи с сервера бота.
- **Решение (план):** бот подключается к Postgres по строке подключения (`DATABASE_URL`), которую задаёт владелец в Railway. Таблицы закрываются RLS, anon-доступа нет.
- **Статус:** открыто. Нужна строка подключения от владельца (Supabase Dashboard → Connect). Пароль в чат не присылать.

### 007 — Схема базы в Supabase (проект `aqlbpakvqkvlbcztbbgg`)
- **Что:** миграция `init_cosmetics_bot_schema`: таблицы `price_cache`, `watches`, `favorites` по актуальной схеме кода. Включён RLS, политик для anon нет. Строки `watches` с устаревшей схемой не переносились.
- **Почему:** SQLite на Railway и Vercel не подходит (файловая система эфемерна). Таблицы пересозданы под код, потому что старая схема `watches` расходилась с кодом (запись 005).
- **Кто решил:** владелец (перенос в Supabase), схема — я.

### 008 — Перенос данных из SQLite в Supabase
- **Что:** `price_cache` — 21 строка, `favorites` — 3 строки, `watches` — 0. Проверено подсчётом после вставки: 21 / 3 / 0, совпадает с SQLite.
- **Где:** таблицы Supabase. Файл `cosmetics_bot/data/bot.db` в git больше не отслеживается (см. запись 010), сам файл на диске не удалён.
- **Кто решил:** владелец (перенос данных), выполнено мной.

### 009 — `db.py` переписан на Postgres (psycopg)
- **Что:** все функции сохранены с теми же сигнатурами, `bot.py` и `details.py` не менялись. `INSERT OR REPLACE` заменён на `ON CONFLICT ... DO UPDATE`, `rowid` на `id`, плейсхолдеры `?` на `%s`. Подключение через переменную `DATABASE_URL`. `init_db()` теперь только проверяет подключение, таблицы создаются миграцией.
- **Проверка:** локальный PostgreSQL 16 (отдельный кластер в `/var/tmp/pgtest`, к Supabase не подключался). Все функции прогнаны вручную, 2 unit-теста в `tests/test_db.py` проходят.
- **Тесты:** `tests/test_db.py` запускаются только при `TEST_DATABASE_URL`, работают в отдельной схеме `test_db_tests` и рабочие таблицы не трогают. Без переменной тесты пропускаются.
- **Кто решил:** я (реализация), план согласован с владельцем (запись 006).
- **Статус:** открыто для проверки владельцем на реальной базе.

### 010 — Git: секреты и база убраны из отслеживания
- **Что:**
  - `.env`, `cosmetics_bot/.env` — `git rm --cached` (файлы на диске остались);
  - `cosmetics_bot/data/bot.db` — `git rm --cached` (файл на диске остался);
  - добавлен `.gitignore` (`__pycache__`, `.env`, `*.db`).
- **Почему:** токен Telegram лежал в git, а в `bot.db` — chat_id пользователей. Старые коммиты с токеном остаются в истории, поэтому токен всё равно нужно перевыпустить (см. запись 011).
- **Статус:** принято мной, владелец может оспорить (например, хранить `.env` в git не запрещено, но это плохая практика).

### 011 — Токен Telegram в `render.yaml` заменён на имя переменной
- **Что:** в `cosmetics_bot/render.yaml` имя переменной было подставлено токен. Заменено на `TELEGRAM_TOKEN` и `DATABASE_URL` с `sync: false`.
- **Почему:** токен не должен быть в файле репозитория.
- **Важно:** токен `8729769091:...` уже в истории git и считается скомпрометированным. **Нужно перевыпустить его через @BotFather (`/revoke`)** и задать новый в Railway. Этот шаг делает владелец.
- **Статус:** открыто (ждёт перевыпуска токена владельцем).

### 012 — Исправления для запуска на Railway
- **`main.py`:** блокировка `msvcrt` выполняется только в Windows (запись 001 — падение на Linux).
- **`Dockerfile`:** база `python:3.10-slim` заменена на `python:3.12-slim`, добавлен `playwright install --with-deps chromium`.
- **Почему 3.12:** в репозитории есть `__pycache__/*.cpython-312.pyc`, значит, код запускали на 3.12.
- **`requirements.txt`:** добавлен `psycopg[binary]>=3.1.0`.
- **Кто решил:** я (решения по Docker и версии Python могут быть оспорены владельцем).
- **Статус:** открыто — не проверено сборкой Docker-образа.

### 013 — Хостинг: Railway
- **Что:** выбран Railway. В аккаунте `emeko-emeko` (workspace `emeko-emeko's Projects`) уже есть два проекта с сервисами из этого репозитория, оба в статусе FAILED (см. запись 004).
- **Решение (план):** сервис деплоится из ветки `ccr-e925f19b-cn0pk8` после пуша. Существующие сервисы `beautyfind` и `telegram-bot` пока не менял.
- **Статус:** открыто — владелец выбирает, использовать существующий сервис или создать новый.

### 014 — Служебное: `.gitignore`, `CLAUDE.md`, `JOURNAL.md`
- **Что:** созданы файлы правил и журнала (`CLAUDE.md`, `JOURNAL.md`) и `.gitignore`.
- **Кто решил:** владелец (запрос на журнал и правила), оформление мной.

### 015 — Пуш в ветку `ccr-e925f19b-cn0pk8`
- **Что:** коммит `0c03943` (перенос на Supabase, исправления для Railway, правила и журнал) запушен в `origin/ccr-e925f19b-cn0pk8`. Ветка `main` не трогалась, Pull Request не создавался.
- **Почему:** Railway собирает образ из GitHub-репозитория, без пуша деплоить нечего.
- **Кто решил:** владелец (запрос на доведение до ума), пуш выполнен мной по правилам рабочей ветки.
- **Статус:** принято. Деплой на Railway ещё не запущен, ждёт строки подключения и нового токена (см. запись 013 и 011).

### 016 — Railway: новый сервис `cosmetics-bot` в проекте `jubilant-wholeness`
- **Что:** создан сервис `cosmetics-bot` (id `cf8462e6-5bdf-4acb-89dd-c95db6504cc3`) в проекте `jubilant-wholeness` (id `c2dc2d3c-b7ba-4c10-896b-54c5df5f8d17`).
- **Почему:** владелец выбрал новый сервис в `jubilant-wholeness` (запись 013). Существующие `beautyfind` и `telegram-bot` не менялись.
- **Кто решил:** владелец.
- **Статус:** принято.

### 017 — Railway: сервис `cosmetics-bot` подключён к GitHub
- **Что:** источник — репозиторий `emeko-emeko/beautyfind`, ветка `ccr-e925f19b-cn0pk8`, без закрепления на коммите. Сборка по Dockerfile в корне.
- **Почему:** Railway собирает образ из GitHub-репозитория (см. запись 015).
- **Пока не заданы переменные `TELEGRAM_TOKEN` и `DATABASE_URL`.** Без них бот не сможет работать (см. запись 011).
- **Кто решил:** владелец (выбор сервиса), подключение выполнено мной.
- **Статус:** принято, ждёт переменных.

### 018 — Деплой `cosmetics-bot` упал на сборке образа (BUILD_IMAGE)
- **Что:** деплой `825eb291-bd29-4a43-8bf0-24c5ec92a43b` (коммит `4f4d81a`) упал: `playwright install --with-deps chromium` завершился с кодом 127. Node-драйвер Playwright не может загрузить `libatomic.so.1`.
- **Почему:** в `python:3.12-slim` нет `libatomic1`, а `--with-deps` её не ставит.
- **Исправление:** в `Dockerfile` перед `pip install` добавлен шаг `apt-get install libatomic1`.
- **Кто решил:** я (диагноз по логам Railway), владелец не возражал.
- **Статус:** открыто — деплой после пуша ещё не проверен.

### 019 — Переменные окружения в `cosmetics-bot` не заданы
- **Что:** `list-variables` для `cosmetics-bot` показывает только системные `RAILWAY_*`. `DATABASE_URL` и `TELEGRAM_TOKEN` отсутствуют.
- **Замечание:** в сервисе `beautyfind` (проект `jubilant-wholeness`) есть 2 незакоммиченных изменения (staged). Я их не создавал и не применял. Возможно, переменные были добавлены туда.
- **Статус:** открыто — владелец проверяет, куда попали переменные. Ни одно изменение в `beautyfind` я не принимал.

### 020 — Переменные `DATABASE_URL` и `TELEGRAM_TOKEN` применены
- **Что:** владелец добавил переменные в `beautyfind`, затем изменения были применены в Railway (вероятно, через дашборд). Сейчас переменные есть в `cosmetics-bot` и `beautyfind` (проект `jubilant-wholeness`). Значения я не читал и не копировал.
- **Побочный эффект:** применение staged-изменений запустило деплой `beautyfind` из ветки `main` (деплой `427dbae5…`, статус BUILDING). Ветка `main` не менялась. Этот сервис старый, его судьба не решена.
- **Кто решил:** владелец (добавление переменных и применение).
- **Статус:** принято. Новый деплой `cosmetics-bot` (`a1b2835a…`) собирается, результат запуска ещё не проверен.
- **Замечание:** в `cosmetics-bot` и `beautyfind` переменные одни и те же. Вероятно, `TELEGRAM_TOKEN` в обоих сервисах не нужен одновременно: два сервиса с одним токеном Telegram будут конфликтовать (`getUpdates` работает только в одном экземпляре). Если `beautyfind` не используется, его стоит остановить. Решение за владельцем, статус открыто.

### 021 — Очистка репозитория и объединение документов
- **Что:** из git убраны `code de vie.txt` и `viled.txt` (файлы на диске остались, добавлены в `.gitignore`); из git убраны `__pycache__/*.pyc` (файлы на диске остались); `docs/journal.md` и `claude-setup.md` объединены в этот файл как приложения A и B (содержимое без правок).
- **Почему:** большие HTML-дампы не нужны в репозитории; кэш байткода не должен отслеживаться; три документа с журналом и настройками должны быть одним файлом.
- **Где:** `JOURNAL.md`, `docs/journal.md` (удалён), `claude-setup.md` (удалён), `.gitignore`, индекс git.
- **Кто решил:** владелец (запрос на очистку и объединение); оформление мной.
- **Статус:** принято. Тесты `test_kodedevie_viled` не зависят от этих файлов (пропускаются, если их нет).

---

## Приложение A. Журнал сессии (бывший `docs/journal.md`)


### Коммиты этой сессии (по порядку)
- 78e8053 — Код де ви, Viled, Space NK, Cult Beauty как «pending» магазины; пересчёт EUR→₸ (EUR_TO_KZT = 509.99, курс НБ РК на 7.10.2026, обновлять вручную); тесты на сохранённом HTML
- 960d634 — подключены Код де ви и Viled (search_url `/women/search?searchQuery={query}`)
- ec413e5 — флаг «Unable to ship to Kazakhstan» (`restricted_sel`), пометка в сообщении бота
- ebf72fb — подключён Cult Beauty (`cultbeauty.com/search/?q={query}`)
- 9fb3c28 — подключён Space NK (`spacenk.com/uk/search?q={query}&search-button=&lang=en_GB`)
- eb71712 — удалено сообщение «⚠️ магазин: недоступен» (сообщение «Магазины не ответили» оставлено); отслеживание цен: `/watch` со списком и отменой, фоновый watcher каждые 10 мин, уведомления о изменении цены
- 06136fa — обработчик страницы товара Cult Beauty (цена EUR → ₸, исходная сумма в `price_native`)
- 9c5256a — обработчик страницы товара Space NK (цена уже в ₸, `.product-detail__prices .value`)

### Текущее состояние
Подключено 8 магазинов в STORES: Mon Amie, Золотое Яблоко, Французский дом, Yves Rocher, Код де ви, Viled, Cult Beauty, Space NK. PENDING_STORES пуст.

Кнопка «Отслеживать цену» есть у всех 8 магазинов: обработчики страницы товара добавлены для Код де ви (`detail_kodedevie`) и Viled (`detail_viled`, объём из активной кнопки «30 мл» / «50 мл»).
Код де ви: цена 13 860 ₸ со скидкой, без скидки 19 800 ₸. Файл `code de vie.txt` повреждён (нет `<`, `>`, `"`), тест на нём построен по воспроизведённой разметке.

Плашка «Unable to ship to Kazakhstan» (`h5.unavailable-notice`) распознаётся только у Space NK. У Cult Beauty образца нет.

### Ключевые файлы
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

### Открытые вопросы и задачи
1. Код де ви: пересохранить страницу товара как HTML (`code de vie.txt` без тегов), затем заменить тест на реальной разметке. Viled: смена варианта кнопкой «50 мл» не проверена на живом сайте (в файле только активный вариант).
2. Курс EUR_TO_KZT = 509.99 устарел (октябрь 2026). Нужен актуальный курс, поправить вручную.
3. Не проверено на живых сайтах: селекторы карточек выдачи поиска для Space NK, Код де ви, Viled, Cult Beauty (сохранённые примеры были с категорий и брендов). Проверить через бота запросом типа «lips» / «pencil».
4. Watcher не проверен на живом боте (тесты только логики на подставных данных). Проверить: подписаться на товар, подождать 10–30 мин.
5. Плашка доставки для Cult Beauty: нужен HTML карточки/страницы с этой плашкой.
6. Выбор оттенка на Space NK: обработчик берёт цену текущего выбранного оттенка, при смене оттенка не проверено.
7. Предложено, не сделано (нужно подтверждение): добавить `__pycache__/` в .gitignore.
8. Существующая проблема: main.py на Linux — msvcrt = None, блокировка файла упадёт. Не трогал.
9. Подключение бота к Telegram в тестах не проверялось.

### Окружение для тестов (важно)
- Системный Python без playwright/aiogram. Установлено в scratchpad:
  - pylib (playwright 1.63.0 — совпадает с браузером /opt/pw-browsers, версия из /opt/node-tools)
  - pylib2 (aiogram, python-dotenv)
- Запуск: `PYTHONPATH=<scratchpad>/pylib2:<scratchpad>/pylib:. PYTHONDONTWRITEBYTECODE=1 python3 -m unittest cosmetics_bot.tests.<модуль>`
- ПОСЛЕ тестов: `git checkout -- cosmetics_bot/data/bot.db` (импорт bot.py вызывает init_db и меняет трекаемый файл) и удалить `*.cpython-313.pyc`, иначе они попадут в «untracked».
- `python3 -c "import ..."` без PYTHONDONTWRITEBYTECODE тоже создаёт pyc — это уже случалось.

### Правила, которые соблюдались
- Коммиты и пуши только в claude/eloquent-pascal-k1a8u1.
- Строку Co-Authored-By с названием модели в коммитах не писать (системная инструкция). Строка Claude-Session есть.
- Адреса поиска брались только из присланных пользователем ссылок, ничего не угадывалось.
- Сайты из окружения недоступны (прокси 403), поэтому разметка берётся только из присланного HTML.

---

## Приложение B. Настройки Claude (бывший `claude-setup.md`)

### Настройки Claude: всё в одном файле

Дата сбора: 14.11.2026. Источники: `~/.claude/settings.json`, папки `~/.claude/skills`, `~/.claude/skill-repos`, `FridgeKeeper\.claude\`, список скиллов и MCP из системного контекста сессии. Секреты и токены сюда не вписаны.

#### 1. Общие настройки (`C:\Users\User\.claude\settings.json`)

| Параметр | Значение |
|---|---|
| Модель по умолчанию | `haiku` |
| Усилие для Haiku 5.5 | `low` (`modelSettings.claude-haiku-5-5.effortLevel`) |
| Тема | `dark` |
| Workflows | включены (`enableWorkflows: true`) |
| Хук `Stop` | gstack: `bash /c/Users/User/.claude/skills/gstack/hosts/claude/hooks/timeline-stop-hook`, таймаут 5 с |

#### 2. Плагины (включены в `enabledPlugins`)

| Плагин | Маркетплейс | Что даёт |
|---|---|---|
| claude-code-setup | claude-plugins-official | подбор настроек и автоматизации |
| frontend-design | claude-plugins-official | дизайн фронтенда |
| security-guidance | claude-plugins-official | подсказки по безопасности |
| skill-creator | claude-plugins-official | создание скиллов |
| playwright | claude-plugins-official | браузерные тесты |
| superpowers | claude-plugins-official | процессные скиллы (brainstorming, debugging, TDD, планы) |
| ecc | `ecc` (github: affaan-m/everything-claude-code) | большой набор скиллов и агентов ECC |
| mempalace | `mempalace` (github: MemPalace/mempalace) | память и поиск по заметкам |
| agent-skills | `addy-agent-skills` (github: addyosmani/agent-skills) | инженерные скиллы |
| ui-ux-pro-max | `ui-ux-pro-max-skill` (github: nextlevelbuilder/ui-ux-pro-max-skill) | поиск по дизайн-системам |

Маркетплейсы описаны в `extraKnownMarketplaces`: это те же четыре источника (ecc, mempalace, addy-agent-skills, ui-ux-pro-max-skill).

#### 3. Скиллы в `C:\Users\User\.claude\skills\` (ставились вручную)

- **graphify**: карта кода и знаний (`/graphify`). Файлы: `SKILL.md`, `references\*.md`.
- **unslop**: убирает «ИИ-вид» из интерфейсов. Скрипты `snapshot.mjs`, `story.mjs`; справочники `signs.md`, `tokens.md`, `visuals.md`, `effects.md`.
- **uipro-banner-design, uipro-brand, uipro-design, uipro-design-system, uipro-slides, uipro-ui-styling, uipro-ui-ux-pro-max**: переименованные копии ui-ux-pro-max. Путь `${CLAUDE_PLUGIN_ROOT}` заменён на `$HOME/.claude/skills/uipro-*`. Поиск: `search.py "<запрос>" --domain <домен>`.
- **gstack**: около 100 скиллов, версия 1.99.2.0, канал stable. Установлен 13.11.2026 через `./setup` (нужен Bun 1.4.4). Главные: `design-review`, `design-html`, `design-shotgun`, `design-consultation`, `design-motion`, `plan-design-review`, `plan-devex-review`, `browse`, `qa`, `review`, `ship`, `careful`, `freeze`, `guard`, `autoplan`, `benchmark`, `canary`, `cso`, `retro`.

#### 4. Репозитории-примеры (`C:\Users\User\.claude\skill-repos\`)

Клоны для изучения, в проект не подключены, если не сказано иное:

- **taste-skill**: `design-taste-frontend`, версия 2.5.1. Подключён симлинком в `skills`.
- **ui-ux-pro-max-skill**: источник uipro-скиллов.
- **gstack**: источник gstack.
- **react-three-fiber**: 3D для React (MIT), нужен React.
- **liquid-glass-js**: стеклянные панели (MIT).
- **shadergradient**: градиентные фоны (MIT), нужен React или Vue.

#### 5. Скиллы из плагинов и системного списка

Вызов через `Skill`. Список как он виден в сессии, не полный по всем пунктам.

**Процессные (superpowers):** brainstorming, systematic-debugging, test-driven-development, writing-plans, executing-plans, subagent-driven-development, dispatching-parallel-agents, requesting-code-review, receiving-code-review, verification-before-completion, finishing-a-development-branch, using-git-worktrees, writing-skills, using-superpowers, diagnosing-superpowers.

**Дизайн:** impeccable (+ агенты `impeccable-*`), design-taste-frontend, frontend-design, unslop, vectorlab-ux-skills (ux-audit, spacing, typography, colour-palette, anti-slop, forms, errors, motion и др.), design-skills (design-critique, accessibility-audit, design-systems, ux-writing и др.), design (design-critique, design-system, ux-copy, user-research и др.), figma (figma-use, figma-generate-design, figma-code-connect и др.), image-generation, dataviz, artifact-design, artifact-diagramming, artifact-capabilities.

**Код и проверка:** code-review, simplify, security-review, init, verify, run, learn, loop, schedule, update-config, keybindings-help, fewer-permission-prompts, claude-api, skill-creator, plugin-authoring, workflow-authoring, write-skill, skillify, spec, cso, health, review, ship, qa, qa-only, test-audit, document-generate, document-release, make-pdf, retro.

**Документы и данные:** anthropic-skills (docx, pdf, pptx, xlsx, docs, deep-research, explain-usage, google-workspace, morning, setup-claude, consolidate-memory, import-memory), data (analyze, build-dashboard, create-viz, sql-queries, statistical-analysis, validate-data, write-query и др.).

**Vercel:** bootstrap, deploy, env, status, ai-gateway, ai-sdk, auth, nextjs, vercel-functions, vercel-storage, vercel-firewall, workflow и др.

**Supabase:** supabase, supabase-postgres-best-practices.

**Telegram:** telegram:access, telegram:configure.

**Прочие:** find-skills, freeze, unfreeze, guard, careful, browse, connect-chrome, pair-agent, canary, benchmark, devex-review, diagram, scrape, eval-plan, office-hours, plan-ceo-review, plan-tune, autoplan, ubicloud, setup-deploy, setup-gbrain, sync-gbrain, setup-browser-cookies, runaway-stopper, landing-report, gstack-upgrade, codex, deslop-shared-libs, ios-* (clean, design-review, fix, qa, sync), team, mempalace:* (audit, init, mine, search, status), ui-ux-pro-max:* (banner-design, brand, design, design-system, slides, ui-styling), code-review:code-review, ecc:* (около 300 скиллов, например code-review, tdd-workflow, security-review, python-patterns, fastapi-patterns, postgres-patterns, dashboard-builder), agent-skills:* (api-and-interface-design, code-review-and-quality, debugging-and-error-recovery, spec-driven-development, test-driven-development, security-and-hardening и др.).

#### 6. Свои агенты и команда (`FridgeKeeper\.claude\`)

Папка `agents\`:

| Агент | Модель | Роль |
|---|---|---|
| team-coder | Haiku 5.5 | бэкенд по подтверждённому плану |
| team-designer | Sonnet 5.5, effort medium | дизайн сайта и Mini App |
| team-controller | Haiku 5.5 | контроль плана и проверок, только чтение |
| team-logs | Haiku 5.5 | логи Vercel, только чтение |
| team-refs | Sonnet 5.5 | разбор сайтов-референсов, скриншоты в `design-system\refs\` |
| unslop-reviewer | Haiku 5.5 | проверка дизайна, только чтение |
| unslop-fixer | Haiku 5.5 | правки по списку находок |
| impeccable-asset-producer | по умолчанию | растровые ассеты из утверждённых макетов |
| impeccable-documenter | по умолчанию | DESIGN.md по готовой сборке |
| impeccable-finish-reviewer | по умолчанию | проверка готовой сборки |
| impeccable-manual-edit-applier | по умолчанию | применение правок из live-режима |

Папка `commands\`: `team.md` (команда `/team <задача>`).

Папка `skills\impeccable\`: скилл impeccable и его `reference\*.md` (около 50 файлов).

#### 7. Агенты системы (не из проекта)

- Встроенные: general-purpose, Explore, Plan, claude-code-guide, statusline-setup.
- Плагинные: ecc:* (около 60, например code-reviewer, security-reviewer, python-reviewer, fastapi-reviewer, tdd-guide, planner, architect), agent-skills:* (code-reviewer, security-auditor, test-engineer, web-performance-auditor), vercel:* (ai-architect, deployment-expert, performance-optimizer), web-fetch.

#### 8. Память

Папка: `C:\Users\User\.claude\projects\C--Users-User-Desktop-FridgeKeeper\memory\`. На момент сбора в ней не найдено ни одного `.md` файла, включая `MEMORY.md`.

#### 9. Файлы с правилами

- `C:\Users\User\.claude\CLAUDE.md`: глобальные правила (по-русски, план до кода, проверка перед «готово», graphify).
- `C:\Users\User\Desktop\FridgeKeeper\CLAUDE.md`: контекст проекта, журнал работы, правила дизайна и команды агентов.
- `C:\Users\User\Desktop\FridgeKeeper\AGENTS.md`: описание проекта для других агентов.

#### 10. MCP-серверы

**Подключены (по системному контексту):**
- Railway (`mcp__006cc940…`)
- Docs для Claude (`mcp__1a59c906…`)
- Graphify (`mcp__4a5d54e7…`)
- Vercel (`mcp__6996b17f…`, 200+ инструментов, проект `fridge-keeper`)
- Supabase (`mcp__8849c7c2…`)
- Figma (`mcp__b6d09b04…`)
- Claude in Chrome (`mcp__claude-in-chrome__*`)
- Computer use (`mcp__computer-use__*`)
- Terminal (`mcp__terminal__*`)
- Scheduled tasks, MCP registry, ccd_* (сессии, окна, настройки)
- Playwright и mempalace (подключались в момент сбора, инструменты через ToolSearch)
- Abracadabrax (генерация изображений и видео из текста)

**Нужна авторизация через `/mcp`:** Atlassian, BigQuery, Hex, Asana, Figma (design), Intercom, Linear, Notion, Slack, Vercel (plugin).

**Не подключились:**
- Amplitude и Amplitude EU: ECONNREFUSED.
- Definite: ENDPOINT_NOT_FOUND.
- Telegram (plugin:telegram): кеш сбоя, повтор через 15 минут.

#### 11. Прочие инструменты

- Bun 1.4.4 (для gstack, установлен через npm).
- Node.js (`node --check` для JS проекта).
- uv и Python (проект).
- Хук GateGuard (ECC) блокирует первую правку файла и Bash без «фактов». Обход описан в его сообщении: `GATEGUARD_EXEMPT_GLOBS`, `GATEGUARD_BASH_ROUTINE_DISABLED=1`, `ECC_GATEGUARD=off`. Менять без решения пользователя не стоит.

#### 12. Оговорки

- Список ecc:* (около 300 скиллов и около 60 агентов) выписан группами, не поштучно.
- Папка памяти пуста по поиску `*.md`. Если память должна быть, стоит проверить путь.
- ui-ux-pro-max и gstack лежат и в `skills`, и в `skill-repos`. Дубли не удалялись.
- Файла `.mcp.json` в корне проекта не найдено, поэтому список MCP взят из системного контекста, а не из конфига.
