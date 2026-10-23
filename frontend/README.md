# Frontend — React / TypeScript / Vite

Кабинет предпринимателя и рабочее место сотрудника банка в одном SPA. Визуальный язык взят из брифа кейса: красный, кислотный лайм, электрический синий и фиолетовый на светло-сером, белые карточки, крупная широкая типографика (Unbounded + Onest, шрифты в бандле, без CDN), пиксельные мотивы и кнопки-клавиши.

## Запуск

Нужен Node.js 20+.

```bash
cd frontend
npm ci
npm run dev        # http://localhost:5173, /api и /health проксируются на http://localhost:8000
```

Backend запускается как в корневом README. Origin `http://localhost:5173` уже есть в `ALLOWED_ORIGINS` из `.env.example`. Proxy не переписывает Origin; не смешивайте localhost и 127.0.0.1.

Демо-режим без backend — API работает в браузере на синтетических данных C01/C02 (подходит любой пароль, состояние в localStorage, сброс кнопкой в бегущей строке):

```bash
npm run dev:mock   # или npm run build:mock → dist-demo/, открывается как статический сайт
```

Сборка для Docker/nginx: `npm run build` → `dist/`. Для browser-роутинга нужен fallback на `index.html`; если его нет, соберите с `VITE_ROUTER=hash`. Переменные — в `.env.example`.

| Команда | Что делает |
| --- | --- |
| `npm run dev` / `dev:mock` | Dev-сервер с реальным API / демо-API |
| `npm run build` / `build:mock` | Проверка типов и сборка |
| `npm run gen:api` | Перегенерировать `src/api/schema.d.ts` из `../docs/openapi.json` |

## Структура

```text
src/
  api/          client.ts (fetch, CSRF в памяти, ApiError, 401), endpoints.ts, types.ts, schema.d.ts (генерируется)
  api/mock/     демо-API: те же пути, DTO, 409/422/CSRF и упрощённая demo-policy-0.2
  components/   ui.tsx (кнопки-клавиши, чипы, модалки, тосты), pixel.tsx (пиксель-арт, курсор, клавиши), AppShell
  lib/          session.tsx (вход, /me, /activity раз в минуту), queries.ts, format.ts, labels.ts
  pages/        Login, client/ (Обзор, Мои заявки, Компания, мастер заявки, статус), bank/ (очередь, карточка)
  styles/       tokens.css, base.css, components.css, app.css
```

Мастер заявки: автосохранение PATCH с `expected_version` (одна операция в полёте, 409 останавливает автосохранение и предлагает загрузить актуальную версию), предварительный расчёт через `/scenarios` на каждую сохранённую версию, варианты «Сумма −20%» и «Срок +12», AI-разбор (EXPLAIN/COMPARE, только после согласия на БКИ), навигатор готовности, отправка с `submission_key`, который сохраняется при неизвестном исходе. При `NEEDS_INFO` запрошенные поля подсвечиваются. Банк: очередь с фильтрами и автообновлением, карточка с оценкой, проверками, снимком, дозапросами, историей, версиями, документами и AI; действия строго по `allowed_actions`, конфликт 409 обновляет карточку.

Шаги с выбором («Потребность» и «Проверка») подтверждаются кнопкой «Подтвердить»: она недоступна, пока на странице есть незаполненные поля (их список показан рядом и ведёт к полю). Подтверждённый шаг блокируется до нажатия «Редактировать»; отправка доступна, когда подтверждены оба. «Компания» и «Финансы» только для чтения; ячейки финансов редактируются, лишь если их запросил банк. ИИ-помощник открывается плавающей кнопкой справа внизу. Отметки хранятся в браузере по заявке и номеру отправки. В списке заявок есть удаление черновика. Оно вызывает DELETE /api/applications/{id}, которого пока нет в backend: что добавить — в ../BACKEND_REQUEST.md. До этого интерфейс показывает понятное сообщение, а в демо-режиме удаление работает.

Сквозной сценарий проверен против backend demo-0.2: клиент C01 (3 млн, 18 мес) → ручной разбор → дозапрос сотрудника → повторная отправка → ручное одобрение.

## Контракт API для frontend

## Что подключать первым

1. Dev proxy /api → http://localhost:8000, обращения frontend к относительным URL. В backend ALLOWED_ORIGINS должен включать точный origin Vite (обычно http://localhost:5173); .env.example уже содержит его. Не переписывать Origin на proxy и не смешивать localhost с 127.0.0.1. Cookie через браузер, X-CSRF-Token из /api/auth/csrf; после login получить новый CSRF.
2. /api/auth/me: роль, срок сессии и ui_context.last_application_id/step. Сначала /me, затем GET разрешенной заявки. 401 — повторный вход, 404 при восстановлении — обзор.
3. GET /api/companies и /products: списки items/total/limit/offset. Идентификаторы брать из API; C01/C02 — ключи файлов.
4. POST /api/applications с company_id/product_id, затем форма по возвращенному DTO. Предзаполнение уже делает backend.
5. PATCH с expected_version: отсутствующее поле сохраняется, null очищает nullable-поле, financial_months заменяется целиком. Отправлять только измененные поля, unknown/read-only поля не включать.
6. Сериализовать автосохранения с задержкой около секунды. После ответа обновлять version. При 409 получить актуальный GET и показать конфликт, без автоматической перезаписи.
7. Показать состояния «Сохраняем», «Сохранено», «Ошибка». Гарантировано сохраняется только подтвержденный сервером ввод. Шаг NEED/COMPANY/FINANCES/REVIEW сохраняется через тот же PATCH.
8. /api/auth/activity вызывать по реальному взаимодействию с ограничением частоты; фоновый GET не продлевает сессию. Успешный POST/PATCH черновика уже продлевает idle TTL.

Формат ошибок: code/message/field_errors/request_id. Деньги — строки с двумя десятичными знаками, ставка — с тремя; пустые деньги null, сроки — целые числа. Два отдельных checkbox; при частичном обновлении confirmations отсутствующий флаг сохраняется.

## Отправка и результат

- В DRAFT/NEEDS_INFO клиент получает EDIT_DRAFT/SUBMIT; в финале — пустой список. Сначала дождаться автосохранения, затем отправить POST /api/applications/{id}/submit с expected_version и новым submission_key (UUID). При потере ответа повторять тот же ключ и исходную версию. Пока исход не выяснен, новый ключ не создавать.
- Перед отправкой оба checkbox должны быть явно true; backend возвращает 422 с путем поля при отсутствии подтверждения. Неполные финансы дают NEEDS_INFO после отправки, а не кредитный отказ.
- Submit возвращает application/revision/assessment. Актуальный DTO application также доступен через GET; использовать возвращенную version, не увеличивать локально на единицу. Отправка фиксируется отдельно до проверки. При прерывании возможен SUBMITTED с assessment=null: показать незавершенную обработку; технический retry доступен сотруднику.
- В GET заявки есть latest_revision_id/no, assessment, decision и open_information_request. Финальные данные рисовать из них. decision=null означает, что решения еще нет. Во внутренние комментарии UI клиента доступа не получает.
- В NEEDS_INFO показать message_to_client/requested_fields; исправленные поля и info_response сохранять обычным PATCH. Новый submit — с новым ключом; сервер создает revision_no=2 и закрывает предыдущий дозапрос. GET /revisions/{revision_no} читает исторический снимок.
- GET /decision: 404 DECISION_NOT_FOUND до финала; после финала возвращает публичное решение. 404 чужой заявки означает отсутствие доступа.

## Предварительный калькулятор

POST /api/applications/{id}/scenarios принимает только expected_version. До вызова сохранить параметры. Ответ: mode и candidates (до трех; исходный запрос, сумма 80%, срок +12 с границами продукта и удалением дублей). Кнопка выбора варианта сохраняет сумму/срок обычным PATCH; это не отправка.

Без подтверждения БКИ mode=CALCULATION_ONLY: платеж/общая сумма/переплата доступны, риск/маршрут/нагрузка null. С подтверждением mode=PREVIEW; правила те же, что при отправке. preliminary_route показывать как предварительную оценку. is_binding всегда false. Поле reasons содержит code/message, reason_codes — список кодов. Обращение не меняет status/version и не создает официальное решение.

AI подключен по [AI_CHECK.md](../AI_CHECK.md): POST /api/applications/{id}/advisor с expected_version и mode=EXPLAIN/COMPARE; CSRF обязателен. Ответ содержит status SUCCESS/FALLBACK, error_code, is_current, scenarios, factors, explanation, ID и контекст отчета. GET того же пути восстанавливает последний отчет, /advisor-reports/{report_id} — конкретный; GET не вызывает модель. Сотруднику доступны только bank-маршруты и отчеты по отправленной версии. Числа показывать из scenarios; устаревший ответ не показывать текущим. Отдельная кнопка выбора варианта вызывает обычный PATCH, отправка остается отдельной. Свободного чата нет. Банковские API готовы по [BANK_CHECK.md](../BANK_CHECK.md); документы — по [DOCUMENTS_CHECK.md](../DOCUMENTS_CHECK.md).

## Документы

Клиент читает `application.documents`, сотрудник — `revision.document_refs` конкретной отправки. Элемент содержит `id`, `application_id`, `kind`, `original_filename`, `mime_type`, `content_sha256`, `size_bytes`, `source=DEMO`, `created_at`, `download_url`. Внутренних путей нет. GET по `download_url` требует cookie, CSRF не нужен. Общий origin/dev proxy; обычная ссылка скачивает CSV, для fetch обрабатывать ошибку до сохранения Blob. Ответ содержит Content-Disposition и X-Content-SHA256, кеширование запрещено. Банк до отправки, другой клиент и неизвестный UUID получают 404; без сессии — 401; поврежденный/отсутствующий файл — 503 DOCUMENT_UNAVAILABLE.

CSV — исходный синтетический профиль; после редактирования CLIENT_DECLARED финансов он не переписывается и не подтверждает новые значения. Загрузки/замены документов в UI нет. Старые снимки могут иметь пустой document_refs; не подменять его текущим application.documents. Текущий GET/скачивание не продлевает idle-сессию.

Банк не получает клиентские черновики: клиентские маршруты для BANK_STAFF возвращают 403. Для сотрудника использовать отдельные DTO и /api/bank/applications. Backend не заменяется логикой проверки прав на frontend.

## Банковский кабинет

1. После /auth/me с user.role=BANK_STAFF открыть банковский интерфейс. GET /api/bank/applications возвращает items/total/limit/offset. По умолчанию незавершенные статусы; для финальных передать status=APPROVED или REJECTED. status — повторяемый список; также есть company_id, limit=1–100, offset>=0. Сортировка: сначала более ранняя отправка. В строке есть продукт, риск и assessment_reasons.
2. GET /api/bank/applications/{id}: revision/assessment/decision, открытый и прошлые дозапросы, список revisions, version и allowed_actions. Все бизнес-поля — из отправки. Пока клиент печатает ответ или правит сумму, банк видит старый снимок. Version при этом может вырасти: это контроль конфликта.
3. GET /{id}/revisions/{revision_no} возвращает revision и все assessments по run_no. История /{id}/events включает автора и привязку к отправке. Кнопки действий относятся только к актуальной карточке, не к исторической версии.
4. POST /{id}/request-info: expected_version, message_to_client (20–1000 символов), requested_fields из enum OpenAPI. Для финансов доступны путь draft_data.financial_months целиком либо конкретный месяц/показатель; нельзя запрашивать role/is_bankrupt/provenance. Ответ — обновленная BankCard со статусом NEEDS_INFO.
5. POST /{id}/decision: expected_version, outcome=APPROVED/REJECTED, обязательное public_explanation (20–1000), необязательный internal_comment (1–2000 или null). Условия предложения сотрудник не вводит: сервер берет их из снимка. Ответ — BankCard с MANUAL-решением. Внутренний комментарий относится только к банковскому экрану; публичное обоснование увидит клиент.
6. Кнопки показывать по allowed_actions: BORDERLINE_RISK — REQUEST_INFO/APPROVE/REJECT; TREND_BASELINE_ZERO — REQUEST_INFO; техническая/неподтвержденная проверка — RETRY_PROCESSING. Для NEEDS_INFO и финальных статусов действий сотрудника нет. Retry остается POST /{id}/retry-processing по SUBMISSION_CHECK.md.
7. При 409 обновить карточку и показать конфликт, не повторять ручное решение с новой version автоматически. На время команды блокировать кнопку. Все POST требуют CSRF. После успешной команды обновить карточку и очередь; финальная заявка уйдет из очереди по умолчанию.

Assessment хранит рекомендацию правил: после ручного APPROVED он может по-прежнему иметь routing=MANUAL_REVIEW и risk_score=40. Финальный результат показывается из status/decision. Чтение и polling не продлевают idle-сессию; /auth/activity используется при реальном взаимодействии. Отдельных сотрудников-исполнителей и назначения заявки в MVP нет.
