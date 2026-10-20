# Умный кредитный кабинет предпринимателя

Прототип для хакатона: путь малого и микробизнеса от выбора финансирования до результата рассмотрения заявки, связанный с рабочим местом сотрудника банка.

**Текущий этап: сохраняемые черновики demo-0.2.** Работают авторизация, PostgreSQL/15 моделей, логирование, минимальный импорт C01/C02, доступ к компаниям/продукту, создание и сохранение заявок с version и восстановлением контекста. Последний полный прогон: 105 тестов, включая PostgreSQL и двух одновременных писателей. Отправка/скоринг/банк/AI — следующие этапы.

- [Пошаговая проверка импорта, доступа и черновиков через Swagger](DRAFTS_CHECK.md).
- [Разработка и правила Git](DEVELOPMENT.md).
- [Запуск backend, настройки и контракт авторизации для Ксюши и Димы](BACKEND.md).
- [Согласованная архитектура, данные и план MVP](ARCHITECTURE.md).
- [Действующий контракт demo-0.2: форма, синтетика, скоринг и сценарии](SYNTETIC.md).
- [Роли команды, сессии, контракты API/Docker и порядок разработки](IMPLEMENTATION_PLAN.md).
- [БД: таблицы, поля, снимки, связи и хранение за весь цикл](DATABASE.md).
- [Клиентский и банковский контуры, экраны и жизненный цикл](USER_FLOWS.md).

Границы MVP и demo-0.2 согласованы. Frontend зафиксирован на React/TypeScript/Vite, его реализует Ксюша. Backend запускается отдельно от frontend/Docker. Для авторизации нужна доступная PostgreSQL и учетные записи, созданные seed или CLI; сценарий до сохраненного черновика уже работает, отправка на рассмотрение пока недоступна.

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
    dependencies.py                 Сессия БД, проверка входа/роли/CSRF
    errors.py                       Единый формат ошибок
    health.py                       Liveness/readiness
  core/
    config.py                       Настройки из env
    constants.py
    demo.py                         Дата расчета и окно финансов demo-0.2
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
  services/
    auth.py                         Прикладная логика сессий
    access.py                       Membership и безопасное восстановление
    drafts.py                       Создание/сохранение черновика
    seed.py                         Проверка набора и транзакционный импорт
  integrations/                     Место под будущие адаптеры
migrations/
  env.py
  script.py.mako
  versions/0001_demo_02.py           Начальная схема из 15 таблиц
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
  test_drafts_postgres.py            Реальная конкуренция двух записей
demo_data/demo_0_2/                  Минимальный C01/C02; расширяют Валера и София
frontend/                           Область Ксюши
*.md                                Архитектура и контракты команды
```

Исходники находятся в `src/`, тесты и миграции — вне устанавливаемого Python-пакета. Точка входа — `python -m credit_cabinet`. Зависимости фиксируем в корневых `pyproject.toml` и `uv.lock`; конфигурацию запуска — в `.env.example`. Docker/Compose и reverse proxy добавляет Дима в корне, исходники frontend — Ксюша в `frontend/`. Будущий integrations отмечен .gitkeep. Контракт для React — frontend/README.md и docs/openapi.json.

## Быстрый запуск backend

Нужны uv, Python 3.12 и существующая PostgreSQL 17.x. Из корня репозитория:

```powershell
uv sync --locked
Copy-Item .env.example .env
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
| Ксюша | frontend/README.md и DRAFTS_CHECK.md: готовые черновики; затем BACKEND.md: готовый вход/сессии; затем SYNTETIC.md, разделы 3–4 и 11: поля/подтверждения, ошибки, provenance, калькулятор/AI; затем USER_FLOWS.md |
| Валера и София | SYNTETIC.md, разделы 2–3, 5 и 7–12: demo_data/demo_0_2, форматы, юридический факт, происхождение и ожидаемые исходы |
| Сергей | SYNTETIC.md и DATABASE.md: защита подтверждения БКИ перед вызовами, 15 шагов политики, снимки и хранение |
| Дима | BACKEND.md: команды процесса/миграций и health; затем DEVELOPMENT.md и IMPLEMENTATION_PLAN.md: manifest/schema 2, WC_DEMO/version 2, импорт demo-0.2 и воспроизводимый запуск |

Текущий AI: объяснение заявки, сравнение суммы/срока и недостающие данные. Стресс-сценарий отложен за пределы хакатона; дополнительных AI-функций в контракте нет. Предметные поля и пороги задает SYNTETIC.md, таблицы — DATABASE.md, UI и права — USER_FLOWS.md, запуск — DEVELOPMENT.md. При изменениях документы обновляются вместе.
