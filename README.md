# Умный кредитный кабинет предпринимателя

Прототип для хакатона: путь малого и микробизнеса от выбора финансирования до результата рассмотрения заявки, связанный с рабочим местом сотрудника банка.

**Текущий этап: backend foundation для demo-0.2.** Реализованы FastAPI, 15 моделей БД, миграция Alembic и авторизация с серверными сессиями. Frontend и Docker разрабатывают Ксюша и Дима. Предметные API, скоринг, полный импорт и AI — следующие этапы.

- [Разработка и правила Git](DEVELOPMENT.md).
- [Запуск backend, настройки и контракт авторизации для Ксюши и Димы](BACKEND.md).
- [Согласованная архитектура, данные и план MVP](ARCHITECTURE.md).
- [Действующий контракт demo-0.2: форма, синтетика, скоринг и сценарии](SYNTETIC.md).
- [Роли команды, сессии, контракты API/Docker и порядок разработки](IMPLEMENTATION_PLAN.md).
- [БД: таблицы, поля, снимки, связи и хранение за весь цикл](DATABASE.md).
- [Клиентский и банковский контуры, экраны и жизненный цикл](USER_FLOWS.md).

Границы MVP и demo-0.2 согласованы. Рабочий вариант frontend — React/TypeScript/Vite; окончательный выбор инструмента остается за Ксюшей. Backend запускается отдельно от frontend/Docker. Для авторизации нужна доступная PostgreSQL и созданные CLI учетные записи; полного сквозного кредитного сценария пока нет.

## Структура проекта

```text
src/credit_cabinet/                  Python-пакет backend
  __init__.py
  __main__.py                       Запуск python -m credit_cabinet
  main.py                           Сборка FastAPI, lifespan, middleware
  cli.py                            Подготовка учетной записи
  api/
    auth.py                         Вход, CSRF, текущий пользователь, выход
    dependencies.py                 Сессия БД, проверка входа/роли/CSRF
    errors.py                       Единый формат ошибок
    health.py                       Liveness/readiness
  core/
    config.py                       Настройки из env
    constants.py
    logging.py
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
  services/
    auth.py                         Прикладная логика сессий
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
tests/                              Авторизация, БД, миграции и health
  conftest.py
  test_auth.py
  test_database.py
  test_health_config.py
  test_postgres.py                  Дополнительная проверка PostgreSQL
demo_data/demo_0_2/                  Набор Валеры и Софии, пока не наполнен
frontend/                           Область Ксюши
*.md                                Архитектура и контракты команды
```

Исходники находятся в `src/`, тесты и миграции — вне устанавливаемого Python-пакета. Точка входа — `python -m credit_cabinet`. Зависимости фиксируем в корневых `pyproject.toml` и `uv.lock`; конфигурацию запуска — в `.env.example`. Docker/Compose и reverse proxy добавляет Дима в корне, исходники frontend — Ксюша в `frontend/`. Пустой будущий integrations и место под синтетику отмечены `.gitkeep`.

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
uv run credit-cabinet-user --email client@example.com --name "Демо-клиент" --role CLIENT
uv run python -m credit_cabinet
```

Пароль CLI запрашивает скрытым вводом. Swagger: http://localhost:8000/docs; проверки: /health/live и /health/ready. Тесты: `uv run pytest -q`. Пошаговый cookie/CSRF-вход, банковский пользователь и параметры — [BACKEND.md](BACKEND.md).

## Передача контрактов команде

| Участник | С чего начать чтение |
| --- | --- |
| Ксюша | BACKEND.md: готовый вход/сессии; затем SYNTETIC.md, разделы 3–4 и 11: поля/подтверждения, ошибки, provenance, калькулятор/AI; затем USER_FLOWS.md |
| Валера и София | SYNTETIC.md, разделы 2–3, 5 и 7–12: demo_data/demo_0_2, форматы, юридический факт, происхождение и ожидаемые исходы |
| Сергей | SYNTETIC.md и DATABASE.md: защита подтверждения БКИ перед вызовами, 15 шагов политики, снимки и хранение |
| Дима | BACKEND.md: команды процесса/миграций и health; затем DEVELOPMENT.md и IMPLEMENTATION_PLAN.md: manifest/schema 2, WC_DEMO/version 2, импорт demo-0.2 и воспроизводимый запуск |

Текущий AI: объяснение заявки, сравнение суммы/срока и недостающие данные. Стресс-сценарий отложен за пределы хакатона; дополнительных AI-функций в контракте нет. Предметные поля и пороги задает SYNTETIC.md, таблицы — DATABASE.md, UI и права — USER_FLOWS.md, запуск — DEVELOPMENT.md. При изменениях документы обновляются вместе.
