# Умный кредитный кабинет предпринимателя

Прототип для хакатона: путь малого и микробизнеса от выбора финансирования до результата рассмотрения заявки, связанный с рабочим местом сотрудника банка.

**Текущий этап: AI-помощник demo-0.2.** Работают авторизация, импорт C01/C02, сохраняемые черновики, неизменяемые отправки, локальные ФНС/БКИ, 15 правил решения, автоматическое решение, дозапрос/новая отправка, технический повтор сотрудником и предварительное сравнение вариантов. Работают банковская очередь/карточка, история версий/оценок, ручной дозапрос и решение с разграничением публичного обоснования и внутреннего комментария. Подготовленные CSV привязываются к заявкам и снимкам; скачивание проверяет права и SHA-256. AI объясняет заявку и сравнивает варианты на рассчитанных backend факторах; есть сохраненные отчеты, актуальность и явный fallback.

Проверка: 341 автоматический тест в полном прогоне, включая PostgreSQL 17.11, права и перезапуск. Еще три опциональных сценария прошли с настоящей qwen3:4b; замеры — docs/ai_benchmark.json. Ruff, миграции и сборка wheel прошли. Актуальная миграция — 0003_document_immutability. Подробности — BACKEND.md и AI_CHECK.md.

- [Проверка AI-помощника через Swagger](AI_CHECK.md).
- [Пошаговая проверка документов и прав скачивания через Swagger](DOCUMENTS_CHECK.md).
- [Проверка банковской очереди, дозапроса и решения](BANK_CHECK.md).
- [Проверка отправки и расчетов](SUBMISSION_CHECK.md).
- [Проверка импорта, доступа и черновиков](DRAFTS_CHECK.md).
- [Разработка и правила Git](DEVELOPMENT.md).
- [Запуск backend, настройки и контракт авторизации для Ксюши и Димы](BACKEND.md).
- [Передача Диме: создание БД, миграции, импорт и сохранность данных в Docker](DOCKER_HANDOFF.md).
- [Согласованная архитектура, данные и план MVP](ARCHITECTURE.md).
- [Действующий контракт demo-0.2: форма, синтетика, скоринг и сценарии](SYNTETIC.md).
- [Роли команды, сессии, контракты API/Docker и порядок разработки](IMPLEMENTATION_PLAN.md).
- [БД: таблицы, поля, снимки, связи и хранение за весь цикл](DATABASE.md).
- [Клиентский и банковский контуры, экраны и жизненный цикл](USER_FLOWS.md).

Границы MVP и demo-0.2 согласованы. Frontend зафиксирован на React/TypeScript/Vite, его реализует Ксюша. Backend запускается отдельно от frontend/Docker. Для авторизации нужна доступная PostgreSQL и учетные записи, созданные seed или CLI; работает путь от черновика до автоматического результата, а также дозапрос/новая отправка.

## Структура проекта

```text
src/credit_cabinet/                  Python-пакет backend
  __init__.py
  __main__.py                       Запуск python -m credit_cabinet
  main.py                           Сборка FastAPI, lifespan, middleware
  cli.py                            Подготовка учетной записи
  seed.py                           CLI проверки/импорта demo-0.2
  api/
    auth.py                         Вход, CSRF, текущий пользователь, выход
    business.py                     Компании, продукт, черновики и события
    bank.py                         Банковская очередь/карточка и ручные действия
    submissions.py                  Отправка, чтение снимка/решения, технический повтор
    scenarios.py                    Предварительное сравнение вариантов
    documents.py                    Закрытое скачивание синтетических CSV
    advisor.py                      Объяснение и сравнение, чтение отчетов
    dependencies.py                 Сессия БД, проверка входа/роли/CSRF
    errors.py                       Единый формат ошибок
    health.py                       Liveness/readiness
  core/
    config.py                       Настройки из env
    constants.py
    demo.py                         Дата расчета и окно финансов demo-0.2
    policy_contract.json            Зафиксированная конфигурация demo-policy-0.2
    logging.py                      JSON-логи, request_id, безопасный стек ошибок
    security.py                     Argon2id, случайные токены, UTC
  db/
    base.py                         DeclarativeBase, типы и naming convention
    session.py                      Engine и сессии SQLAlchemy
  models/
    identity.py                     Пользователи, сессии, компании, финансы
    applications.py                 Продукты, заявки, отправки, документы
    processing.py                   Проверки, оценки, решения, дозапросы
    history.py                      События и AI-отчеты
    enums.py
    types.py
  schemas/
    auth.py                         Pydantic DTO авторизации
    errors.py
    business.py                     DTO формы и каталога
    seed.py                         Типы файлов набора
    submissions.py                  DTO снимка, отправки и повтора
    scenarios.py                    DTO предварительного сравнения
    bank.py                         DTO банка и разрешенные поля дозапроса
    documents.py                    Метаданные документов без внутренних путей
    advisor.py                      DTO отчета и строгого ответа модели
  services/
    auth.py                         Прикладная логика сессий
    access.py                       Membership и безопасное восстановление
    drafts.py                       Создание/сохранение черновика
    documents.py                    Привязка файлов и права на документы снимков
    advisor.py, advisor_context.py  Контекст, факторы, отчеты и актуальность
    snapshots.py                    Валидация отправки и содержательный hash
    submissions.py                  Фиксация отправки, проверки и результат
    policy.py                       Чистые Decimal-расчеты и правила
    scenarios.py                    Кандидаты на одном наборе фактов
    views.py, reasons.py            Публичные DTO и объяснения
    bank.py                         Чтение отправленных данных для банка
    bank_policy.py                  Допустимые действия по сохраненным проверкам
    bank_commands.py                Транзакционные ручные команды
    seed.py                         Проверка набора и транзакционный импорт
  integrations/fixtures.py          Локальные детерминированные ФНС/БКИ
  integrations/documents.py         Проверка и приватное хранение CSV
  integrations/ollama.py            Ограниченный HTTP-вызов модели, JSON Schema
migrations/
  env.py
  script.py.mako
  versions/0001_demo_02.py           Начальная схема из 15 таблиц
  versions/0002_revision_immutability.py  Защита снимков UPDATE/DELETE
  versions/0003_document_immutability.py  Защита метаданных документов
alembic.ini
pyproject.toml
uv.lock
.python-version
.env.example
tests/                              Авторизация, БД, миграции, health, импорт и черновики
  conftest.py
  test_auth.py
  test_database.py
  test_health_config.py
  test_postgres.py                  Дополнительная проверка PostgreSQL
  test_logging.py
  test_seed.py
  test_drafts.py
  test_drafts_postgres.py            Реальные гонки PATCH/submit и restart
  test_policy.py, test_fixtures.py   Пороги правил и симуляторы
  test_snapshots.py, test_submissions.py
  test_scenarios.py                  Сравнение без изменения заявки
  test_bank_*.py                    Права банка, снимки, команды и гонки PostgreSQL
demo_data/demo_0_2/                  Минимальный C01/C02; расширяют Валера и София
frontend/                           Область Ксюши
*.md                                Архитектура и контракты команды
```

Исходники находятся в `src/`, тесты и миграции — вне устанавливаемого Python-пакета. Точка входа — `python -m credit_cabinet`. Зависимости фиксируем в корневых `pyproject.toml` и `uv.lock`; конфигурацию запуска — в `.env.example`. Docker/Compose и reverse proxy добавляет Дима в корне, исходники frontend — Ксюша в `frontend/`. Локальные адаптеры читают версионированные fixtures из demo_data/demo_0_2. Контракт для React — frontend/README.md и docs/openapi.json.

## Быстрый запуск backend

Нужны uv, Python 3.12 и существующая PostgreSQL 17.x. Из корня репозитория:

```powershell
uv sync --locked
if (!(Test-Path .env)) { Copy-Item .env.example .env }
uv run python -c "import secrets; print(secrets.token_urlsafe(48))"
```

В .env указать свою DATABASE_URL и вставить сгенерированный CSRF_SIGNING_KEY. Готовый .env не перезаписывать. Затем:

```powershell
uv run alembic upgrade head
uv run python -m credit_cabinet.seed --check-only
uv run python -m credit_cabinet.seed
uv run python -m credit_cabinet
```

При первом seed пароль НОВЫХ демо-аккаунтов запрашивается скрытым вводом; существующие пароли сохраняются. Клиенты: client@example.com (C01), client2@example.com (C02). Swagger: http://localhost:8000/docs; проверки: /health/live и /health/ready. Тесты: `uv run pytest -q`. Пошаговый cookie/CSRF-вход, банковский пользователь и параметры — [BACKEND.md](BACKEND.md).

## Передача контрактов команде

| Участник | С чего начать чтение |
| --- | --- |
| Ксюша | frontend/README.md и BANK_CHECK.md: банковский кабинет; SUBMISSION_CHECK.md: отправка/результат/варианты; DRAFTS_CHECK.md: черновики; затем BACKEND.md: готовый вход/сессии; затем SYNTETIC.md, разделы 3–4 и 11: поля/подтверждения, ошибки, provenance, калькулятор/AI; затем USER_FLOWS.md |
| Валера и София | SYNTETIC.md, разделы 2–3, 5 и 7–12: demo_data/demo_0_2, форматы, юридический факт, происхождение и ожидаемые исходы |
| Сергей | SYNTETIC.md и DATABASE.md: защита подтверждения БКИ перед вызовами, 15 шагов политики, снимки и хранение |
| Дима | BACKEND.md: команды процесса/миграций и health; затем DEVELOPMENT.md и IMPLEMENTATION_PLAN.md: manifest/schema 2, WC_DEMO/version 2, импорт demo-0.2 и воспроизводимый запуск |

Текущий AI: объяснение заявки, сравнение суммы/срока и недостающие данные. Стресс-сценарий отложен за пределы хакатона; дополнительных AI-функций в контракте нет. Предметные поля и пороги задает SYNTETIC.md, таблицы — DATABASE.md, UI и права — USER_FLOWS.md, запуск — DEVELOPMENT.md. При изменениях документы обновляются вместе.
