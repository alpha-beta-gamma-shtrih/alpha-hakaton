# Проверка отправки и расчетов demo-0.2

Backend поддерживает отправку, неизменяемые снимки, локальные проверки ФНС/БКИ, автоматический результат, дозапрос/новую отправку и сравнение вариантов. Банковская очередь/карточка, ручной дозапрос и решение также реализованы: BANK_CHECK.md. AI и выдача документов остаются следующими этапами. Все условия и источники демонстрационные; внешних запросов нет.

## 1. Подготовка

Остановить прежний API через Ctrl+C в своем терминале. Существующий .env сохраняется. Из корня проекта:

```powershell
cd C:\alpha\alpha-hakaton
.\.venv\Scripts\alembic.exe upgrade head
.\.venv\Scripts\python.exe -m credit_cabinet.seed --check-only
.\.venv\Scripts\python.exe -m credit_cabinet.seed
.\.venv\Scripts\python.exe -m credit_cabinet
```

Новая миграция 0002_revision_immutability запрещает UPDATE/DELETE отправленных версий на уровне PostgreSQL; данных не удаляет. Схема по-прежнему содержит 15 предметных таблиц. Если seed уже выполнялся, он ничего не сбрасывает. Пароли существующих аккаунтов сохраняются. Если добавляются новые аккаунты — задать пароль от 12 символов скрытым вводом.

Открыть http://localhost:8000/docs. GET /health/ready должен вернуть 200 и schema_revision=0002_revision_immutability. При 503 проверить миграции и PostgreSQL.

## 2. Войти и создать C01

1. GET /api/auth/csrf → скопировать csrf_token.
2. POST /api/auth/login → client@example.com, свой прежний пароль и токен в X-CSRF-Token.
3. Снова GET /api/auth/csrf → получить токен авторизованной сессии. Он нужен для всех POST/PATCH ниже. Cookie браузер передает сам.
4. GET /api/companies → id компании C01. GET /api/products → id WC_DEMO/version=2.
5. POST /api/applications с этими UUID:

```json
{"company_id":"UUID компании","product_id":"UUID продукта"}
```

Скопировать id заявки. В новом черновике version=1. Для следующих действий использовать фактическую version из последнего ответа, а не вычислять ее самостоятельно.

## 3. Сохранить условия и проверить обязательные подтверждения

PATCH /api/applications/{application_id}:

```json
{
  "expected_version": 1,
  "requested_amount": "1000000.00",
  "term_months": 12,
  "purpose_code": "INVENTORY",
  "ui_step": "REVIEW"
}
```

Ожидается 200, version=2. Пока оба confirmations=false.

Сгенерировать ключ отправки в PowerShell и скопировать строку:

```powershell
[guid]::NewGuid().ToString()
```

POST /api/applications/{application_id}/submit:

```json
{"expected_version":2,"submission_key":"UUID ключа отправки"}
```

Ожидается 422 CREDIT_HISTORY_CONFIRMATION_REQUIRED с путем поля. Отправка/оценка/решение не создаются, версия заявки не меняется. При подтвержденном БКИ и неподтвержденных сведениях — 422 DATA_CONFIRMATION_REQUIRED.

## 4. Калькулятор без подтверждения

POST /api/applications/{application_id}/scenarios:

```json
{"expected_version":2}
```

Ожидается mode=CALCULATION_ONLY, до трех candidates. У REQUESTED платеж 94559.60, общая сумма 1134715.20, примерная переплата 134715.20. load_ratio/risk_score/preliminary_route и provenance.credit_history равны null, is_binding=false. Источники не вызываются, статус/версия/история не меняются. Альтернативы: сумма 80% при прежнем сроке; срок +12 с максимумом 24. Дубли удаляются.

## 5. Подтвердить сведения, получить PREVIEW и отправить

PATCH с актуальной version:

```json
{
  "expected_version":2,
  "draft_data":{
    "confirmations":{
      "data_confirmed":true,
      "credit_history_check_allowed":true
    }
  }
}
```

Для нового примера version станет 3. POST /scenarios с expected_version=3 → mode=PREVIEW. REQUESTED: preliminary_route=APPROVE, risk_score=10. Это предварительная оценка, не финальное одобрение. Все кандидаты используют один набор фактов; официальных записей checks/assessments/decisions еще нет.

POST /submit с expected_version=3 и UUID ключа:

```json
{"expected_version":3,"submission_key":"UUID ключа отправки"}
```

Ответ 200 содержит три блока:

- application: status=APPROVED, allowed_actions=[], latest_revision_no=1, decision с одобренными условиями;
- revision: неизменяемый снимок, source_lock_version=3, input_hash, company_snapshot/financial_snapshot/product_snapshot, оба подтверждения true;
- assessment: routing=APPROVE, risk_score=10, risk_band=LOW, причины DEMO_POLICY_PASSED и LOAD_35_50, платеж 94559.60. В checks — FNS/BKI/DATA_QUALITY; у успешных внешних демо-проверок есть реальный checked_at и фиксированный as_of_date=2026-10-01.

submitted snapshot сохраняет исходное provenance; результаты последующих проверок находятся в assessment, не дописываются в снимок. purpose_details сохранен в financial_snapshot.purpose_details; document_refs пока пустой, документы будут подключены отдельно.

После отправки читать новую application.version из ответа: один submit состоит из фиксации снимка и отдельной транзакции результата, поэтому версия может вырасти больше чем на один. Промежуточный SUBMITTED сохраняется при сбое; CHECKING пока не выдается как отдельный длительный этап синхронного локального обработчика.

## 6. Повтор, чтение и перезапуск

1. Повторить тот же POST /submit с ТЕМ ЖЕ submission_key и исходной expected_version=3 → 200, та же revision/assessment/decision, без дублей. Проверка повтора выполняется раньше проверки выросшей версии/финального статуса.
2. Новый ключ со старой expected_version → 409 VERSION_CONFLICT. Старый ключ с другой expected_version → 409 SUBMISSION_KEY_CONFLICT.
3. GET /api/applications/{id} → текущий результат и assessment. GET /api/applications/{id}/decision → только публичное решение, без internal_comment.
4. GET /api/applications/{id}/revisions/1 → сохраненный снимок и input_hash.
5. GET /api/applications/{id}/events → DRAFT_CREATED, SUBMITTED, CHECKS_COMPLETED, DECISION_MADE.
6. PATCH финальной заявки → 409 APPLICATION_NOT_EDITABLE.
7. Ctrl+C → снова python -m credit_cabinet. Пока сессия не истекла, данные доступны без повторного входа; после истечения достаточно войти заново.

## 7. C02: отказ по нагрузке

Выйти с CSRF, получить новый контекст входа, войти как client2@example.com с паролем новых демо-аккаунтов. Получить свежий CSRF. Создать свою заявку C02, сохранить сумму 2000000.00, срок 12, INVENTORY и оба подтверждения true. Отправить с актуальной version и новым ключом.

Ожидается REJECTED, причина DEBT_LOAD_LIMIT_EXCEEDED, risk_score=null, risk_band=UNKNOWN. Платеж 189119.19, нагрузка больше 0.80. У decision все поля одобренного предложения null. Первый клиент и сотрудник не могут использовать клиентские маршруты для доступа к этой заявке: чужому клиенту 404, сотруднику 403.

## 8. Дозапрос без изменения исходных файлов

Вернуться к client@example.com, создать НОВЫЙ черновик C01 с теми же условиями и обоими подтверждениями true. Не менять финальную заявку из предыдущего примера.

1. Скопировать полный массив draft_data.financial_months из GET новой заявки в отдельный текстовый редактор.
2. Удалить из копии строку июня 2026-06-01. PATCH с актуальной expected_version и draft_data.financial_months, содержащим оставшиеся пять строк. Массив заменяется целиком.
3. Отправить → NEEDS_INFO, risk_score=null, decision=null; open_information_request содержит требуемые июньские поля.
4. Сохранить GET /revisions/1 и его input_hash.
5. PATCH заявки с актуальной version: вернуть все шесть строк и передать draft_data.info_response="Добавлен июнь". NEEDS_INFO допускает EDIT_DRAFT/SUBMIT.
6. Отправить с НОВЫМ submission_key и актуальной version → APPROVED, latest_revision_no=2, открытого дозапроса нет.
7. GET /revisions/1 по-прежнему содержит пять месяцев и прежний hash. GET /revisions/2 содержит шесть месяцев и ответ. История включает INFO_REQUESTED и INFO_ANSWERED.

## 9. Технический повтор и границы текущего банка

Для SOURCE_FNS_UNAVAILABLE / SOURCE_BKI_UNAVAILABLE / SOURCE_RESPONSE_INVALID / COMPANY_DATA_MISMATCH / LEGAL_STATUS_UNCONFIRMED итогового decision нет. Сотрудник может повторить проверку; для BORDERLINE_RISK технический повтор недоступен. Ручное одобрение/отказ, банковские GET и очередь уже доступны по BANK_CHECK.md.

POST /api/bank/applications/{id}/retry-processing доступен только BANK_STAFF, с CSRF и {"expected_version":текущая_версия}. Сотрудник получает id/version из очереди/карточки GET /api/bank/applications и /{id}; после retry обновляет карточку. В успешном ответе есть status/version/revision_id/assessment/allowed_actions.

Повтор создает новый assessment.run_no для той же revision. Входы и подтверждения берутся из снимка. Он не меняет прежние проверки и не создает новую отправку. Уже финальное решение повторять нельзя. Если обработка прервалась после фиксации снимка, GET покажет SUBMITTED и assessment=null; повтор submit тем же ключом вернет сохраненную отправку, а запуск обработки выполняет этот банковский endpoint.

В базовом наборе C01/C02 технических ошибок нет; для ручной проверки основного этапа менять fixtures не требуется. Сбой/повтор, неизвестное банкротство, гонки, неизменность SQL и все восемь профилей покрыты автоматическими тестами. Расширение fixtures по run_no/revision_no — demo_data/README.md.

## 10. Проверки и остановка

```powershell
.\.venv\Scripts\pytest.exe -q
.\.venv\Scripts\ruff.exe check src tests migrations
.\.venv\Scripts\ruff.exe format --check src tests migrations
```

PostgreSQL-тесты включаются через TEST_DATABASE_URL по BACKEND.md и работают только в собственных временных схемах. Рабочие таблицы не очищают.

Завершить свой API через Ctrl+C. Codex перед передачей результата завершает запущенные им процессы; службу PostgreSQL не останавливаем.
