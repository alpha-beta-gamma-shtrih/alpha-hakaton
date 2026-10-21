# Банковский контур demo-0.2: проверка через Swagger

Реализованы очередь, карточка, отправленные версии/оценки, история, ручной дозапрос и ручное решение. Все сотрудники демо-банка видят все отправленные обращения; назначения исполнителя нет. Банк не читает неотправленные правки клиента. Документы отправленных версий доступны по [DOCUMENTS_CHECK.md](DOCUMENTS_CHECK.md). AI остается следующим этапом.

## 1. Запуск

Существующий .env сохраняется. Если API работает в своем терминале — остановить Ctrl+C. Из корня проекта:

```powershell
cd C:\alpha\alpha-hakaton
.\.venv\Scripts\alembic.exe upgrade head
.\.venv\Scripts\python.exe -m credit_cabinet.seed --check-only
.\.venv\Scripts\python.exe -m credit_cabinet.seed
.\.venv\Scripts\python.exe -m credit_cabinet
```

Актуальна миграция 0003_document_immutability, таблиц по-прежнему 15. Повторный seed не сбрасывает заявки или пароли. Если аккаунт создается впервые, seed запрашивает пароль от 12 символов; он относится только к новым аккаунтам. Вход существующего bank@example.com использует его прежний пароль, а не обязательно пароль нового seed.

Открыть http://localhost:8000/docs. GET /health/ready → 200.

## 2. Подготовить заявку для ручного рассмотрения

Обычная C01 автоматически одобряется, поэтому для проверки сотрудника создадим отдельную заявку с другими финансовыми показателями. Файлы синтетики и профиль компании не меняются.

1. GET /api/auth/csrf → скопировать csrf_token.
2. POST /api/auth/login как client@example.com со своим паролем и X-CSRF-Token.
3. Снова GET /api/auth/csrf → токен авторизованной сессии для всех POST/PATCH.
4. GET /api/companies → UUID C01. GET /api/products → UUID WC_DEMO/version=2.
5. POST /api/applications с {"company_id":"UUID C01","product_id":"UUID продукта"}. Сохранить id НОВОЙ заявки.
6. PATCH /api/applications/{application_id}:

```json
{
  "expected_version": 1,
  "requested_amount": "1000000.00",
  "term_months": 12,
  "purpose_code": "INVENTORY",
  "ui_step": "REVIEW",
  "draft_data": {
    "financial_months": [
      {"month":"2026-04-01","cash_inflow":"1020000.00","operating_outflow":"850000.00","existing_debt_payment":"30000.00"},
      {"month":"2026-05-01","cash_inflow":"1020000.00","operating_outflow":"850000.00","existing_debt_payment":"30000.00"},
      {"month":"2026-06-01","cash_inflow":"1020000.00","operating_outflow":"850000.00","existing_debt_payment":"30000.00"},
      {"month":"2026-07-01","cash_inflow":"1020000.00","operating_outflow":"850000.00","existing_debt_payment":"30000.00"},
      {"month":"2026-08-01","cash_inflow":"1020000.00","operating_outflow":"850000.00","existing_debt_payment":"30000.00"},
      {"month":"2026-09-01","cash_inflow":"1020000.00","operating_outflow":"850000.00","existing_debt_payment":"30000.00"}
    ],
    "confirmations": {"data_confirmed":true,"credit_history_check_allowed":true}
  }
}
```

Ожидается 200, version=2. Сгенерировать ключ отправки в PowerShell:

```powershell
[guid]::NewGuid().ToString()
```

POST /api/applications/{id}/submit:

```json
{"expected_version":2,"submission_key":"полученный UUID"}
```

Ожидается 200: application.status=MANUAL_REVIEW, assessment.risk_score=40, risk_band=MEDIUM, причина BORDERLINE_RISK. Платеж 94559.60, средний поток 170000.00, нагрузка около 0.7327. Это оценка по фактам, а не назначенная компании метка. Сохранить application.id и revision.input_hash.

Если использован ранее существовавший черновик, брать его фактическую version. Значения version после submit не вычислять вручную.

## 3. Войти сотрудником и открыть очередь

Выйти через POST /api/auth/logout с текущим CSRF → GET /csrf → POST /login как bank@example.com → снова GET /csrf. После каждой смены пользователя нужен новый CSRF. Для двух одновременных пользователей удобны обычное и приватное окно браузера; вкладки одного профиля используют общие cookie.

GET /api/bank/applications, тег bank:

- по умолчанию SUBMITTED/CHECKING/NEEDS_INFO/MANUAL_REVIEW, сначала более ранние отправки;
- status принимает повторяемый список: например, MANUAL_REVIEW или APPROVED; финальные записи доступны через явный фильтр;
- company_id — необязательный UUID, limit=1–100, offset>=0;
- ответ items/total/limit/offset; в строке компания/ИНН/продукт/параметры из снимка, risk_score/risk_band/assessment_reasons, version и allowed_actions;
- DRAFT не появляется в очереди и не принимается как status-фильтр.

GET /api/bank/applications/{id} → карточка. Для подготовленного сценария allowed_actions=[REQUEST_INFO, APPROVE, REJECT]. В revision — отправленные входы; в assessment — сохраненные факты/проверки/причины; revisions перечисляет версии; decision и open_information_request пока null. Ни GET очереди, ни карточка не запускают источники и не продлевают idle-сессию фоновым чтением.

GET /api/bank/applications/{id}/revisions/1 возвращает revision и все assessments этой отправки по run_no. GET /api/bank/applications/{id}/events — историю с автором, revision_id и порядковым номером.

## 4. Ручное одобрение и приватный комментарий

POST /api/bank/applications/{id}/decision. Подставить ТЕКУЩУЮ version из банковской карточки; 4 ниже — пример:

```json
{
  "expected_version": 4,
  "outcome": "APPROVED",
  "public_explanation": "Показатели изучены, риск оценен в рамках демонстрационной политики.",
  "internal_comment": "Внутренняя заметка сотрудника для проверки разделения доступа."
}
```

Ожидается 200 и банковская карточка:

- status=APPROVED, allowed_actions=[];
- decision.source=MANUAL, decided_by_user_id — сотрудник, reason MANUAL_APPROVED;
- одобрены именно 1000000.00 / 12 / 24.000 / 94559.60 из снимка;
- assessment остается рекомендацией MANUAL_REVIEW/40, новая оценка не создается;
- внутренний комментарий есть только в банковском decision; public_explanation виден клиенту;
- в истории одно DECISION_MADE с автором, результатом и прежним статусом; исходный снимок/hash не меняется.

Обоснование обязательно: 20–1000 символов после удаления пробелов по краям. internal_comment необязателен, до 2000 символов. Сумму/срок/ставку/assessment_id/revision_id в команду не передавать: неизвестные поля дают 422. Для других условий сотрудник запрашивает изменения у клиента, не переписывает предложение.

Повтор того же действия со старой version → 409 VERSION_CONFLICT. С актуальной version финальной заявки → 409 BANK_ACTION_NOT_ALLOWED. Финал не открывается заново.

Для ручного отказа создать НОВУЮ пограничную заявку по разделу 2 и выбрать outcome=REJECTED, написав публичную причину. Итог source=MANUAL/MANUAL_REJECTED, поля одобренного предложения null.

Снова войти клиентом и проверить GET заявки, /decision, /events, список /api/applications. Публичная причина и итог доступны; internal_comment и внутренней заметки в ответах нет. Сотрудник не использует клиентские маршруты — там для BANK_STAFF ожидается 403.

## 5. Ручной дозапрос и новая отправка

Создать еще одну НОВУЮ пограничную заявку по разделу 2. Войти сотрудником, получить свежую карточку и CSRF.

POST /api/bank/applications/{id}/request-info, с актуальной version:

```json
{
  "expected_version": 4,
  "message_to_client": "Уточните требуемую сумму и срок с учетом ожидаемых поступлений компании.",
  "requested_fields": ["requested_amount","term_months","draft_data.info_response"]
}
```

Ожидается NEEDS_INFO, decision=null, allowed_actions=[]. open_information_request содержит вопрос, автора и revision_id первой отправки. Второй открытый дозапрос создать нельзя.

Вернуться к клиенту: GET заявки возвращает тот же вопрос. PATCH с фактической version:

```json
{
  "expected_version": 5,
  "requested_amount": "500000.00",
  "term_months": 24,
  "draft_data": {"info_response":"Потребность уточнена, сумма уменьшена и срок увеличен."}
}
```

До новой отправки банк по-прежнему видит сумму 1000000.00/срок 12 из revision 1, а answer_text дозапроса остается null. Текущая version карточки может увеличиться из-за сохранения клиентом — это механизм обнаружения конфликта, не выдача черновика.

POST клиентского /submit с новой version и НОВЫМ submission_key → APPROVED, revision_no=2, закрытый дозапрос, итог source=AUTO. Это результат нового расчета после уточнений. В банковской карточке information_requests[0] имеет status=ANSWERED, answer_text и answered_revision_id второй отправки. Старые revision 1 и assessment/40 сохраняются.

## 6. Что разрешено по политике

| Состояние/причина | Действия сотрудника |
| --- | --- |
| MANUAL_REVIEW / BORDERLINE_RISK, обязательные проверки успешны | REQUEST_INFO / APPROVE / REJECT |
| MANUAL_REVIEW / TREND_BASELINE_ZERO | Только REQUEST_INFO |
| Ошибка источника, неизвестное банкротство или противоречие реквизитов | Только RETRY_PROCESSING |
| SUBMITTED после прерывания обработки | RETRY_PROCESSING |
| NEEDS_INFO | Ждать новой отправки клиента |
| APPROVED / REJECTED | Только чтение |

Банковские действия повторно проверяют сохраненные обязательные факты и правила локально. Нет ручного обхода банкротства, просрочек, отсутствующих проверок или жестких ограничений. Технический сбой нельзя превращать в ручной отказ. Условия берутся из отправленной версии даже при последующем изменении каталога.

POST /api/bank/applications/{id}/retry-processing сохранен, тег bank-processing. Он принимает expected_version из карточки и сохраняет новый run_no той же revision; после ответа обновить карточку. Для BORDERLINE_RISK технический повтор недоступен. Проверка ошибок/повторов описана также в SUBMISSION_CHECK.md; базовые C01/C02 не требуют изменения fixtures для банковского сценария выше.

## 7. Права, конфликты и перезапуск

- Без входа банковские API дают 401, клиенту — 403; незнакомый UUID и неотправленный DRAFT сотруднику дают 404.
- POST требуют текущий CSRF и допустимый Origin. GET не требует CSRF.
- Всегда читать allowed_actions и version из карточки. После 409 обновить карточку и показать конфликт; автоматически повторять решение с новой версией нельзя.
- Два сотрудника, прочитавшие одну version, не могут оба решить/изменить заявку. Сохраняется одно действие, второй получает 409. PostgreSQL-тесты проверяют решение/решение, решение/дозапрос и дозапрос/дозапрос.
- Ctrl+C → снова python -m credit_cabinet. Решение, автор, приватный комментарий, дозапросы и история остаются в БД. Пока сессия действительна, повторный вход не нужен.

## 8. Автоматическая проверка и остановка

```powershell
.\.venv\Scripts\pytest.exe -q
.\.venv\Scripts\ruff.exe check src tests migrations
.\.venv\Scripts\ruff.exe format --check src tests migrations
```

Настройка TEST_DATABASE_URL — BACKEND.md; PostgreSQL-тесты работают в собственных временных схемах и не очищают рабочие таблицы.

После своей проверки остановить API Ctrl+C. Codex завершает запущенные им проверочные процессы перед передачей результата; службу PostgreSQL не останавливаем.
