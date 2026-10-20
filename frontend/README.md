# Frontend — React / TypeScript / Vite

Область Ксюши. Стек React подтвержден командой; TypeScript/Vite остаются согласованной основой. Здесь пока только инструкция, UI не реализован.

Работающие API: вход/CSRF/сессия, компании/продукт, черновики, submit, снимок/проверки/результат, автоматический дозапрос/ответ и scenarios. Контракты: [SUBMISSION_CHECK.md](../SUBMISSION_CHECK.md), [DRAFTS_CHECK.md](../DRAFTS_CHECK.md), [BACKEND.md](../BACKEND.md), [SYNTETIC.md](../SYNTETIC.md), [USER_FLOWS.md](../USER_FLOWS.md). Снимок OpenAPI — [docs/openapi.json](../docs/openapi.json); актуальная схема запущенного backend — GET /openapi.json.

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

AI, банковская очередь/ручные решения и документы пока не подключены. Для сотрудника есть только POST retry-processing по SUBMISSION_CHECK.md; макеты остальных экранов показывают состояние разработки.

Банк не получает клиентские черновики: эти маршруты для BANK_STAFF возвращают 403. Для банковских экранов позже будут отдельные DTO отправленных снимков. Backend не заменяется логикой проверки прав на frontend.
