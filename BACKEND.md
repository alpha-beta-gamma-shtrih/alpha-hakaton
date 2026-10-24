# Backend: запуск и контракты

Актуальные персональные условия, поля и совместимость версий — [PRICING.md](PRICING.md); обновление и приемка — [PRICING_CHECK.md](PRICING_CHECK.md).

Реализованы FastAPI, 15 моделей, миграции 0001–0005, авторизация/JSON-логи, импорт полного набора из 144 компаний, черновики, отправка/снимки/проверки, автоматическое решение, дозапрос/новая отправка, технический повтор сотрудником, сравнение вариантов и банковская очередь/карточка/ручные команды. Подготовленные CSV привязываются к заявкам и снимкам; скачивание проверяет права и целостность. AI-помощник объясняет заявку и сравнивает варианты, сохраняет отчеты и проверяет актуальность. Приёмка данных Валеры, новые аккаунты и обновление заполненной БД — [DATA_VALIDATION.md](DATA_VALIDATION.md). Проверка AI — [AI_CHECK.md](AI_CHECK.md), документов — [DOCUMENTS_CHECK.md](DOCUMENTS_CHECK.md); предыдущих этапов — [BANK_CHECK.md](BANK_CHECK.md), [SUBMISSION_CHECK.md](SUBMISSION_CHECK.md) и [DRAFTS_CHECK.md](DRAFTS_CHECK.md). Frontend React/TypeScript/Vite — Ксюша, Docker — Дима.

## Запуск из корня репозитория

Нужны Python 3.12, uv и доступная PostgreSQL 17.x. Зависимости закреплены в uv.lock. Backend не устанавливает PostgreSQL, не создает базу/роль и не запускает Docker. База и роль должны существовать до миграции. Версия Python текущего окружения — 3.12.14.

```powershell
uv sync --locked
if (!(Test-Path .env)) { Copy-Item .env.example .env }
uv run python -c "import secrets; print(secrets.token_urlsafe(48))"
```

Вставить сгенерированное значение в CSRF_SIGNING_KEY файла .env и выставить DATABASE_URL для своей БД. Пример URL в .env.example — демонстрационный шаблон, не созданные учетные данные. Если .env уже настроен, не перезаписывать его командой Copy-Item. .env исключен из Git.

На текущем ноутбуке uv находится в игнорируемой .tools/bin/uv.exe; вместо uv можно вызывать .\.tools\bin\uv.exe. Эта локальная папка не входит в поставку: остальным участникам нужен собственный uv ([установка](https://docs.astral.sh/uv/getting-started/installation/)).

```powershell
uv run alembic upgrade head
uv run credit-cabinet-user --email client@example.com --name "Демо-клиент" --role CLIENT
uv run credit-cabinet-user --email bank@example.com --name "Демо-сотрудник" --role BANK_STAFF
uv run python -m credit_cabinet
```

CLI дважды запрашивает пароль (12–1024 символа) скрытым вводом. Пароль не передается в аргументах и не коммитится. Повторное создание существующего email завершается ошибкой, пароль не сбрасывается. Это инструмент ручной подготовки учетной записи. Минимальный идемпотентный импорт уже доступен: uv run python -m credit_cabinet.seed; --check-only проверяет файлы без БД. Подробности — DRAFTS_CHECK.md.

API слушает 0.0.0.0:8000. Локально открыть http://localhost:8000/docs; OpenAPI — /openapi.json. Рабочая папка — корень проекта, оттуда читаются .env и alembic.ini. Эквивалентная команда ASGI: uv run uvicorn credit_cabinet.main:create_app --factory --host 0.0.0.0 --port 8000 --no-proxy-headers --no-access-log.

| Проверка | Что означает |
| --- | --- |
| GET /health/live → 200 | Процесс работает; БД не проверяется |
| GET /health/ready → 200 | Есть подключение и Alembic revision=0005_personal_pricing |
| GET /health/ready → 503 | Нет БД/таблицы версий или не применена актуальная миграция |

При старте API нет create_all, миграций, генератора данных или сброса БД. Дима запускает миграции отдельным init-шагом перед API. AI не участвует в readiness.

React подключен к реальному API; совместный запуск и приемка — [FRONTEND_CHECK.md](FRONTEND_CHECK.md). Удаление неотправленных черновиков: DELETE /api/applications/{id} с expected_version, Origin и CSRF, успех 204. Миграция 0005_personal_pricing добавляет archived_at и событие DRAFT_ARCHIVED; удаленные черновики и их документы/отчеты недоступны через API, физическая история сохраняется. Отправленные заявки, включая NEEDS_INFO, не удаляются.

Подробный порядок создания базы/роли, миграций, импорта, повторного запуска и приемки будущей Docker-поставки — [DOCKER_HANDOFF.md](DOCKER_HANDOFF.md). Compose пока не реализован. Набор CSV/JSON загружает seed, структуру таблиц создает Alembic; локальная база Windows автоматически в контейнер не переносится.

## Настройки

| Переменная | Назначение |
| --- | --- |
| DATABASE_URL | postgresql+psycopg://user:password@host:5432/db; секрет |
| APP_ENV | development / production; test используется только тестами |
| CSRF_SIGNING_KEY | Случайный секрет 32+ символов для короткого контекста входа |
| PUBLIC_BASE_URL | Точный origin frontend, по умолчанию http://localhost:8080 |
| ALLOWED_ORIGINS | JSON-массив дополнительных точных origin без путей и завершающего / |
| COOKIE_SECURE | true для HTTPS; локальный HTTP требует false |
| DEMO_USER_PASSWORD | Необязательный секрет 12+ символов для новых демо-аккаунтов при неинтерактивном seed; старые пароли не сбрасывает |
| DEMO_DATASET_DIR | Каталог локальных источников, по умолчанию demo_data/demo_0_3; нужен API на чтение и должен быть включен в Docker-поставку |
| DOCUMENTS_DIR | Приватные неизменяемые копии CSV, по умолчанию .data/documents; нужен на запись, отдельный постоянный volume. Не раздавать как static |
| LLM_ENABLED | true; false дает явный FALLBACK без вызова runtime |
| LLM_BASE_URL | http://127.0.0.1:11434; для Compose http://ollama:11434 |
| LLM_MODEL | qwen3:4b |
| LLM_MODEL_DIGEST | Необязательный pin sha256:…; реальные значения и замер — docs/ai_benchmark.json |
| LLM_TIMEOUT_SECONDS | 45 (1–120); время обращения к модели |
| LLM_MAX_PARALLEL | 1 (1–4); лимит генераций на процесс API |
| LOG_LEVEL | DEBUG / INFO / WARNING / ERROR / CRITICAL; по умолчанию INFO для логов приложения |
| CLIENT_SESSION_ABSOLUTE_TTL_SECONDS | 28800: не более 8 часов после входа |
| CLIENT_SESSION_IDLE_TTL_SECONDS | 3600: не более часа без активности |
| BANK_SESSION_ABSOLUTE_TTL_SECONDS | 14400: не более 4 часов |
| BANK_SESSION_IDLE_TTL_SECONDS | 900: не более 15 минут |
| LOGIN_RATE_LIMIT | 10 попыток на IP и отдельно на email за окно |
| LOGIN_RATE_WINDOW_SECONDS | Окно 300 секунд |

Production требует HTTPS origin и Secure-cookie. Общий секрет должен быть одинаковым у перезапускаемых экземпляров; сырой session token в БД не хранится. DATABASE_URL и CSRF_SIGNING_KEY не включаются в ответы или логи.

SQLite разрешена только с APP_ENV=test, как средство быстрых тестов. Рабочее приложение использует PostgreSQL с UUID, JSONB, NUMERIC и TIMESTAMPTZ.

## Логирование

Стандартный Python logging выводит события приложения в stdout: одно JSON-событие на строку. Отдельные серверы сбора логов и новые зависимости не нужны. Сообщения запуска/остановки Uvicorn остаются в его стандартном формате. При запуске через python -m credit_cabinet стандартный access-log Uvicorn отключен: запросы пишет наше middleware, без полного URL и query. При прямом запуске uvicorn обязательно сохранять флаг --no-access-log из команды выше.

Логи видны в терминале, где запущен API. Для постоянного локального сохранения можно запускать так из PowerShell:

```powershell
.\.venv\Scripts\python.exe -m credit_cabinet 2>&1 | Tee-Object -FilePath backend.log -Append
```

Обычный запуск и вариант с Tee-Object — альтернативы, второй экземпляр на том же порту запускать не нужно. Файлы *.log исключены из Git. В Docker Дима использует вывод stdout/stderr и docker compose logs; ротация контейнерных логов относится к его конфигурации.

Пример записи (значения иллюстративные):

```json
{"timestamp":"2026-10-20T10:00:00.000+00:00","level":"INFO","logger":"credit_cabinet.main","event":"http.request_completed","request_id":"71a92cc2-54cd-4d9b-b181-d11089dc5989","method":"GET","route":"/api/auth/me","status_code":200,"duration_ms":4.21}
```

Поля timestamp/level/logger/event/request_id присутствуют всегда; время в UTC. Для http.request_completed добавляются метод, шаблон маршрута, HTTP-код и duration_ms до формирования ответа. Сейчас API возвращает обычные JSON-ответы; это не метрика времени загрузки тела будущего streaming-ответа. Неизвестный путь обозначается <unmatched>; конкретные параметры пути и query не пишутся. Ответ 2xx/3xx — INFO, 4xx — WARNING, 5xx — ERROR. На уровне WARNING успешные запросы не выводятся.

request_id генерируется сервером и возвращается в X-Request-ID, а при ошибке — также в JSON. Все прикладные события одного запроса используют этот же идентификатор, включая код авторизации в потоках FastAPI. Входящий X-Request-ID не считается доверенным. События запуска/остановки имеют request_id=null.

Авторизация пишет auth.login_succeeded, auth.login_failed, auth.logout_succeeded, auth.session_expired, auth.session_rejected, auth.login_rate_limited и auth.request_rejected. Успешный вход/выход записывается после commit. Если личность известна, сохраняются внутренний user_id и роль; email, IP и имя не пишутся. Истечение фиксируется при обращении с истекшей сессией, а не отдельным фоновым таймером. Повторные обращения могут давать повторные события проверки.

Неожиданные ошибки пишутся как request.failed, ошибки БД — database.error. Диагностика включает тип исключения и стек: имя файла, функцию и номер строки, включая причины исключений. Текст исключений, строки исходного кода и локальные переменные не выводятся: они могут содержать секреты и SQL-параметры. Форматтер использует разрешенный набор дополнительных полей; новые события должны иметь постоянное имя, а не текст пользовательского ввода. Не передавать секреты в сообщение logger или его параметры.

Тела запросов/ответов, Cookie, Authorization, CSRF, пароли/хеши, строка подключения и документы в логи не включаются. Бизнес-история заявки по-прежнему хранится отдельно в application_events; логирование не заменяет ее и не создает вымышленные бизнес-события до реализации соответствующих API.

## Контракт для Ксюши

Frontend обращается к относительным /api с того же origin; dev-сервер проксирует /api на backend. CORS не включен. Для browser fetch cookie отправляются автоматически при same-origin; при выбранном режиме клиента можно явно задать credentials: "include". Не сохранять токены в localStorage.

1. При открытии приложения вызвать GET /api/auth/me. Ответ 401 переводит на вход.
2. Перед входом вызвать GET /api/auth/csrf: ответ {"csrf_token":"..."}, сервер поставит credit_login на 10 минут. Держать csrf_token в памяти.
3. POST /api/auth/login с JSON {"email":"client@example.com","password":"..."} и заголовком X-CSRF-Token из шага 2. Origin браузер передает автоматически; небраузерный клиент должен передать разрешенный Origin явно.
4. Успешный вход ставит HttpOnly-cookie credit_session, отзывает прежнюю сессию этого браузера и удаляет credit_login.
5. Снова GET /api/auth/csrf: теперь вернется стабильный CSRF-токен серверной сессии. Использовать его для POST/PATCH/DELETE; токен перед входом после входа уже не подходит.
6. GET /api/auth/me восстанавливает вход после закрытия вкладки/перезапуска API, пока не истек idle/absolute TTL.
7. POST /api/auth/logout с текущим X-CSRF-Token отзывает запись в БД и удаляет cookie; успешный ответ 204 без тела.

Если уже авторизованный пользователь повторно вызывает login, нужен CSRF текущей сессии. Успешный login всегда меняет session token и CSRF. При истечении сессии снова получить /csrf для нового входа. Logout с уже истекшей сессией возвращает 401; frontend все равно показывает вход. Все изменяющие авторизованные запросы требуют точного разрешенного Origin и текущего CSRF.

Вход и /me возвращают один формат:

```json
{
  "user": {
    "id": "UUID",
    "email": "client@example.com",
    "display_name": "Демо-клиент",
    "role": "CLIENT",
    "ui_context": {}
  },
  "absolute_expires_at": "2026-10-20T15:00:00Z",
  "idle_expires_at": "2026-10-20T08:00:00Z"
}
```

Время реальное, UTC; дата demo-расчета 2026-10-01 не влияет на сессии. ui_context возвращает безопасные section/step/last_application_id после создания или сохранения черновика. Доступ к сохраненной ссылке повторно проверяется по membership; недоступный контекст возвращает обзор. Компании/продукт/черновики доступны клиенту, для банка доступны отдельные очередь/карточка, версии/проверки, ручные команды и retry; клиентские DTO не содержат внутренних комментариев.

POST /api/auth/activity с текущим CSRF отмечает явное действие пользователя и возвращает тот же формат с обновленным idle_expires_at, ограниченным absolute_expires_at. Вызывать по реальному взаимодействию (навигация, ввод, сохранение) с ограничением частоты, например раз в минуту во время взаимодействий. Не вызывать по interval, фоновому polling или только потому, что вкладка открыта. Обычные GET /me, /csrf и будущие чтения статуса не продлевают сессию. Создание и PATCH черновика уже продлевают idle TTL в одной транзакции с сохранением; отдельный /activity для них не нужен.

Формат ошибки:

```json
{
  "code": "AUTH_REQUIRED",
  "message": "Требуется повторный вход",
  "field_errors": [],
  "request_id": "UUID"
}
```

| HTTP / code | Действие интерфейса |
| --- | --- |
| 401 AUTH_REQUIRED | Получить контекст входа и войти заново |
| 401 INVALID_CREDENTIALS | Общее сообщение о неверных данных, без раскрытия существования email |
| 403 CSRF_INVALID | Обновить /csrf и повторить осознанное действие |
| 403 ORIGIN_FORBIDDEN | Исправить proxy/ALLOWED_ORIGINS |
| 403 ROLE_FORBIDDEN | Не показывать недоступное действие; backend также проверяет роль |
| 422 VALIDATION_ERROR | Показать field_errors: field + message |
| 429 LOGIN_RATE_LIMITED | Учесть заголовок Retry-After |
| 503 DATABASE_UNAVAILABLE | Временная недоступность, не кредитный отказ |

Ответы /api имеют Cache-Control: no-store и X-Request-ID. Пароль/его хеш/session token не возвращаются JSON-ответом; cookie недоступна JavaScript.

## Контракт для Димы

- Python 3.12, зависимости из корневых pyproject.toml + uv.lock. Для образа достаточно uv sync --locked --no-dev.
- Устанавливается пакет из src/credit_cabinet; не подменять это произвольным PYTHONPATH и запуском файла из IDE.
- Команда процесса: python -m credit_cabinet; миграций: alembic upgrade head (в окружении установленных зависимостей).
- PostgreSQL 17.x; DATABASE_URL у контейнера использует host db, не localhost. API не требует внешнего LLM.
- Для dev proxy: /api → api:8000; /docs, /openapi.json и /health также можно проксировать. Внешний web-порт по общему договору 8080.
- Init/миграции выполняются отдельно один раз. Importer/manifest-проверка C01/C02 реализованы: python -m credit_cabinet.seed, для init нужен DEMO_USER_PASSWORD при создании новых аккаунтов. Полный C01–C08 расширяют Валера/София.
- DEMO_DATASET_DIR содержит manifest, companies.csv, fns_responses.json и bki_responses.json с верными SHA-256. Файлы читаются локально; нет сетевых ФНС/БКИ. Контракт попыток — demo_data/README.md. Миграция 0002 защищает снимки триггерами PostgreSQL.
- AI: LLM_BASE_URL=http://ollama:11434 в Compose, модель qwen3:4b и отдельный volume весов; LLM_ENABLED=false дает явный fallback. Ограничения и контракт — AI_CHECK.md. Readiness проверяет БД, не модель.
- Один API worker: лимитер попыток входа пока в памяти процесса и сбрасывается при рестарте. Сами сессии в БД и рестарт переживают. Для нескольких worker нужен общий лимитер.
- Встроенная точка входа отключает доверие к X-Forwarded-*; при proxy все соединения для лимитера могут иметь IP proxy. Если потребуется реальный IP, отдельно настроить доверенный адрес proxy в Uvicorn, не доверять всем присланным заголовкам.
- Нет Dockerfile/Compose, frontend-сборки и фоновых задач в этом изменении.

## Проверки и продолжение

```powershell
uv run pytest -q
uv run ruff check src tests migrations
uv run ruff format --check src tests migrations
uv run alembic current
uv run alembic check
```

Первые три команды не требуют установленной PostgreSQL: интеграционные проверки используют временные SQLite-файлы и настоящий Alembic; SQL PostgreSQL дополнительно проверяется offline. Последние две требуют настроенную PostgreSQL. Тест PostgreSQL при наличии TEST_DATABASE_URL использует только собственную временную схему, удаляя ее после проверки; не задавать туда произвольный рабочий URL без права создания тестовой схемы.

Для прогона также на PostgreSQL:

```powershell
$env:TEST_DATABASE_URL = "postgresql+psycopg://test_user:password@localhost:5432/test_db"
uv run pytest -q
Remove-Item Env:TEST_DATABASE_URL
```

Проверено 23 октября 2026 года: после интеграции frontend и удаления черновиков прошли 387 автоматических тестов, включая PostgreSQL 17.11, цикл upgrade/downgrade/upgrade, отсутствие drift ORM/миграции и вход после перезапуска API. Проверены импорт, пароли/сессии, membership, частичные черновики, 15 правил и границы скоринга, снимки/прямой SQL, дозапросы, восстановление после сбоя и реальные гонки PATCH/submit и банковских команд. Проверены запрет обхода обязательных проверок, скрытие неотправленных правок/внутренних комментариев и откат результата/события при ошибке сессии. Документы дополнительно проверены на права клиента/банка, точный ID/application_id/SHA-256 отправки, C01/C02, сохранность после перезапуска, неизменяемость метаданных, старые пустые снимки, идемпотентность и повреждение файлов. Среди тестов 12 проверок логирования: корреляция, отсутствие секретов/SQL/query в выводе, ошибки, авторизация и уровни. Ruff check/format также прошли. Сборка wheel, lock-файл и текущая OpenAPI (29 путей) проверены. Рабочая база не очищается; новую миграцию применить командой alembic upgrade head. Постоянная локальная PostgreSQL подключена через игнорируемый .env; тест PostgreSQL работает только в собственной временной схеме.

React подключен и проверен с API по FRONTEND_CHECK.md. Следующий этап: Docker/полный набор и приемка поставки. AI реализован по AI_CHECK.md; локальный runtime готовит Дима. Банк реализован по BANK_CHECK.md, документы — DOCUMENTS_CHECK.md. Новых Python-зависимостей нет. Защиту документов добавила 0003_document_immutability; актуальная вершина с удалением черновиков — 0005_personal_pricing. OpenAPI обновлена.

AI-приемка: дополнительно отдельно прошли 3 opt-in теста настоящей qwen3:4b в Ollama 0.40.5. В обычном прогоне они пропускаются без TEST_OLLAMA_URL. AI-отчеты проверены на согласие до кэша, права двух контуров, неизменность заявки, устаревание, работу другого подключения PostgreSQL во время inference и отзыв доступа до сохранения. Реальные времена/модель/digest — docs/ai_benchmark.json. В этом этапе новых миграций нет.
