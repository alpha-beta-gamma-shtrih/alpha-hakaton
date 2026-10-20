# Backend: запуск и контракт авторизации

Реализованный этап: FastAPI, 15 моделей demo-0.2, миграция 0001_demo_02, серверные сессии и CLI создания учетной записи. Предметные API заявок, скоринг, импорт полного набора, восстановление UI-контекста по последней заявке и AI еще не реализованы. Frontend и Docker добавляют Ксюша и Дима.

## Запуск из корня репозитория

Нужны Python 3.12, uv и доступная PostgreSQL 17.x. Зависимости закреплены в uv.lock. Backend не устанавливает PostgreSQL, не создает базу/роль и не запускает Docker. База и роль должны существовать до миграции. Версия Python текущего окружения — 3.12.14.

```powershell
uv sync --locked
Copy-Item .env.example .env
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

CLI дважды запрашивает пароль (12–1024 символа) скрытым вводом. Пароль не передается в аргументах и не коммитится. Повторное создание существующего email завершается ошибкой, пароль не сбрасывается. Это инструмент подготовки учетных записей; полный идемпотентный импорт demo-0.2 будет отдельной задачей.

API слушает 0.0.0.0:8000. Локально открыть http://localhost:8000/docs; OpenAPI — /openapi.json. Рабочая папка — корень проекта, оттуда читаются .env и alembic.ini. Эквивалентная команда ASGI: uv run uvicorn credit_cabinet.main:create_app --factory --host 0.0.0.0 --port 8000 --no-proxy-headers.

| Проверка | Что означает |
| --- | --- |
| GET /health/live → 200 | Процесс работает; БД не проверяется |
| GET /health/ready → 200 | Есть подключение и Alembic revision=0001_demo_02 |
| GET /health/ready → 503 | Нет БД/таблицы версий или не применена актуальная миграция |

При старте API нет create_all, миграций, генератора данных или сброса БД. Дима запускает миграции отдельным init-шагом перед API. AI не участвует в readiness.

## Настройки

| Переменная | Назначение |
| --- | --- |
| DATABASE_URL | postgresql+psycopg://user:password@host:5432/db; секрет |
| APP_ENV | development / production; test используется только тестами |
| CSRF_SIGNING_KEY | Случайный секрет 32+ символов для короткого контекста входа |
| PUBLIC_BASE_URL | Точный origin frontend, по умолчанию http://localhost:8080 |
| ALLOWED_ORIGINS | JSON-массив дополнительных точных origin без путей и завершающего / |
| COOKIE_SECURE | true для HTTPS; локальный HTTP требует false |
| CLIENT_SESSION_ABSOLUTE_TTL_SECONDS | 28800: не более 8 часов после входа |
| CLIENT_SESSION_IDLE_TTL_SECONDS | 3600: не более часа без активности |
| BANK_SESSION_ABSOLUTE_TTL_SECONDS | 14400: не более 4 часов |
| BANK_SESSION_IDLE_TTL_SECONDS | 900: не более 15 минут |
| LOGIN_RATE_LIMIT | 10 попыток на IP и отдельно на email за окно |
| LOGIN_RATE_WINDOW_SECONDS | Окно 300 секунд |

Production требует HTTPS origin и Secure-cookie. Общий секрет должен быть одинаковым у перезапускаемых экземпляров; сырой session token в БД не хранится. DATABASE_URL и CSRF_SIGNING_KEY не включаются в ответы или логи.

SQLite разрешена только с APP_ENV=test, как средство быстрых тестов. Рабочее приложение использует PostgreSQL с UUID, JSONB, NUMERIC и TIMESTAMPTZ.

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

Время реальное, UTC; дата demo-расчета 2026-10-01 не влияет на сессии. ui_context пока возвращает только безопасные section/step, если они уже сохранены; запись/восстановление последней заявки появится вместе с API заявок. Список компаний и банковские обращения в этом этапе еще не отдаются.

POST /api/auth/activity с текущим CSRF отмечает явное действие пользователя и возвращает тот же формат с обновленным idle_expires_at, ограниченным absolute_expires_at. Вызывать по реальному взаимодействию (навигация, ввод, сохранение) с ограничением частоты, например раз в минуту во время взаимодействий. Не вызывать по interval, фоновому polling или только потому, что вкладка открыта. Обычные GET /me, /csrf и будущие чтения статуса не продлевают сессию. Будущие бизнес-команды смогут использовать ту же функцию activity после успешного действия; сами по себе они пока не созданы.

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
- Init/миграции выполняются отдельно один раз. Полный importer/manifest-проверка еще не реализованы; не заявлять готовый seed.
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

Проверено 20 октября 2026 года: 46 тестов прошли, включая PostgreSQL 17.11, цикл upgrade/downgrade/upgrade, отсутствие drift ORM/миграции и вход после перезапуска API. Ruff check/format, генерация OpenAPI и сборка wheel также прошли. Временный PostgreSQL после проверки остановлен; постоянная БД разработки не настраивалась.

Следующий этап Сергея: импорт согласованного demo-0.2, membership-проверки, продукты и клиентские заявки с автосохранением/version; затем снимки, расчеты и банковские действия. Наличие моделей не означает готовность этих API.
