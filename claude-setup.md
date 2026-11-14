# Настройки Claude: всё в одном файле

Дата сбора: 14.11.2026. Источники: `~/.claude/settings.json`, папки `~/.claude/skills`, `~/.claude/skill-repos`, `FridgeKeeper\.claude\`, список скиллов и MCP из системного контекста сессии. Секреты и токены сюда не вписаны.

## 1. Общие настройки (`C:\Users\User\.claude\settings.json`)

| Параметр | Значение |
|---|---|
| Модель по умолчанию | `haiku` |
| Усилие для Haiku 5.5 | `low` (`modelSettings.claude-haiku-5-5.effortLevel`) |
| Тема | `dark` |
| Workflows | включены (`enableWorkflows: true`) |
| Хук `Stop` | gstack: `bash /c/Users/User/.claude/skills/gstack/hosts/claude/hooks/timeline-stop-hook`, таймаут 5 с |

## 2. Плагины (включены в `enabledPlugins`)

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

## 3. Скиллы в `C:\Users\User\.claude\skills\` (ставились вручную)

- **graphify**: карта кода и знаний (`/graphify`). Файлы: `SKILL.md`, `references\*.md`.
- **unslop**: убирает «ИИ-вид» из интерфейсов. Скрипты `snapshot.mjs`, `story.mjs`; справочники `signs.md`, `tokens.md`, `visuals.md`, `effects.md`.
- **uipro-banner-design, uipro-brand, uipro-design, uipro-design-system, uipro-slides, uipro-ui-styling, uipro-ui-ux-pro-max**: переименованные копии ui-ux-pro-max. Путь `${CLAUDE_PLUGIN_ROOT}` заменён на `$HOME/.claude/skills/uipro-*`. Поиск: `search.py "<запрос>" --domain <домен>`.
- **gstack**: около 100 скиллов, версия 1.99.2.0, канал stable. Установлен 13.11.2026 через `./setup` (нужен Bun 1.4.4). Главные: `design-review`, `design-html`, `design-shotgun`, `design-consultation`, `design-motion`, `plan-design-review`, `plan-devex-review`, `browse`, `qa`, `review`, `ship`, `careful`, `freeze`, `guard`, `autoplan`, `benchmark`, `canary`, `cso`, `retro`.

## 4. Репозитории-примеры (`C:\Users\User\.claude\skill-repos\`)

Клоны для изучения, в проект не подключены, если не сказано иное:

- **taste-skill**: `design-taste-frontend`, версия 2.5.1. Подключён симлинком в `skills`.
- **ui-ux-pro-max-skill**: источник uipro-скиллов.
- **gstack**: источник gstack.
- **react-three-fiber**: 3D для React (MIT), нужен React.
- **liquid-glass-js**: стеклянные панели (MIT).
- **shadergradient**: градиентные фоны (MIT), нужен React или Vue.

## 5. Скиллы из плагинов и системного списка

Вызов через `Skill`. Список как он виден в сессии, не полный по всем пунктам.

**Процессные (superpowers):** brainstorming, systematic-debugging, test-driven-development, writing-plans, executing-plans, subagent-driven-development, dispatching-parallel-agents, requesting-code-review, receiving-code-review, verification-before-completion, finishing-a-development-branch, using-git-worktrees, writing-skills, using-superpowers, diagnosing-superpowers.

**Дизайн:** impeccable (+ агенты `impeccable-*`), design-taste-frontend, frontend-design, unslop, vectorlab-ux-skills (ux-audit, spacing, typography, colour-palette, anti-slop, forms, errors, motion и др.), design-skills (design-critique, accessibility-audit, design-systems, ux-writing и др.), design (design-critique, design-system, ux-copy, user-research и др.), figma (figma-use, figma-generate-design, figma-code-connect и др.), image-generation, dataviz, artifact-design, artifact-diagramming, artifact-capabilities.

**Код и проверка:** code-review, simplify, security-review, init, verify, run, learn, loop, schedule, update-config, keybindings-help, fewer-permission-prompts, claude-api, skill-creator, plugin-authoring, workflow-authoring, write-skill, skillify, spec, cso, health, review, ship, qa, qa-only, test-audit, document-generate, document-release, make-pdf, retro.

**Документы и данные:** anthropic-skills (docx, pdf, pptx, xlsx, docs, deep-research, explain-usage, google-workspace, morning, setup-claude, consolidate-memory, import-memory), data (analyze, build-dashboard, create-viz, sql-queries, statistical-analysis, validate-data, write-query и др.).

**Vercel:** bootstrap, deploy, env, status, ai-gateway, ai-sdk, auth, nextjs, vercel-functions, vercel-storage, vercel-firewall, workflow и др.

**Supabase:** supabase, supabase-postgres-best-practices.

**Telegram:** telegram:access, telegram:configure.

**Прочие:** find-skills, freeze, unfreeze, guard, careful, browse, connect-chrome, pair-agent, canary, benchmark, devex-review, diagram, scrape, eval-plan, office-hours, plan-ceo-review, plan-tune, autoplan, ubicloud, setup-deploy, setup-gbrain, sync-gbrain, setup-browser-cookies, runaway-stopper, landing-report, gstack-upgrade, codex, deslop-shared-libs, ios-* (clean, design-review, fix, qa, sync), team, mempalace:* (audit, init, mine, search, status), ui-ux-pro-max:* (banner-design, brand, design, design-system, slides, ui-styling), code-review:code-review, ecc:* (около 300 скиллов, например code-review, tdd-workflow, security-review, python-patterns, fastapi-patterns, postgres-patterns, dashboard-builder), agent-skills:* (api-and-interface-design, code-review-and-quality, debugging-and-error-recovery, spec-driven-development, test-driven-development, security-and-hardening и др.).

## 6. Свои агенты и команда (`FridgeKeeper\.claude\`)

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

## 7. Агенты системы (не из проекта)

- Встроенные: general-purpose, Explore, Plan, claude-code-guide, statusline-setup.
- Плагинные: ecc:* (около 60, например code-reviewer, security-reviewer, python-reviewer, fastapi-reviewer, tdd-guide, planner, architect), agent-skills:* (code-reviewer, security-auditor, test-engineer, web-performance-auditor), vercel:* (ai-architect, deployment-expert, performance-optimizer), web-fetch.

## 8. Память

Папка: `C:\Users\User\.claude\projects\C--Users-User-Desktop-FridgeKeeper\memory\`. На момент сбора в ней не найдено ни одного `.md` файла, включая `MEMORY.md`.

## 9. Файлы с правилами

- `C:\Users\User\.claude\CLAUDE.md`: глобальные правила (по-русски, план до кода, проверка перед «готово», graphify).
- `C:\Users\User\Desktop\FridgeKeeper\CLAUDE.md`: контекст проекта, журнал работы, правила дизайна и команды агентов.
- `C:\Users\User\Desktop\FridgeKeeper\AGENTS.md`: описание проекта для других агентов.

## 10. MCP-серверы

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

## 11. Прочие инструменты

- Bun 1.4.4 (для gstack, установлен через npm).
- Node.js (`node --check` для JS проекта).
- uv и Python (проект).
- Хук GateGuard (ECC) блокирует первую правку файла и Bash без «фактов». Обход описан в его сообщении: `GATEGUARD_EXEMPT_GLOBS`, `GATEGUARD_BASH_ROUTINE_DISABLED=1`, `ECC_GATEGUARD=off`. Менять без решения пользователя не стоит.

## 12. Оговорки

- Список ecc:* (около 300 скиллов и около 60 агентов) выписан группами, не поштучно.
- Папка памяти пуста по поиску `*.md`. Если память должна быть, стоит проверить путь.
- ui-ux-pro-max и gstack лежат и в `skills`, и в `skill-repos`. Дубли не удалялись.
- Файла `.mcp.json` в корне проекта не найдено, поэтому список MCP взят из системного контекста, а не из конфига.
