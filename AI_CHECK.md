# AI-помощник demo-0.2: проверка через Swagger

> Обновление demo-0.3: для нового продукта WC_DEMO/version=3 действуют [PRICING.md](PRICING.md) и [PRICING_CHECK.md](PRICING_CHECK.md): 20% минимум, 6–60 месяцев, пять целей и персональные скидки. Числа и примеры demo-0.2 ниже относятся к историческому продукту v2; новые заявки проверять по PRICING_CHECK.md. Текущая миграция — 0005_personal_pricing.

Два режима одной формы: EXPLAIN объясняет заявку, COMPARE сравнивает исходный запрос, сумму 80% и срок +12 месяцев в пределах продукта. Помощник показывает недостающие финансовые данные и следующий шаг. Свободного чата, стресс-сценария, OCR/RAG, новых продуктов и автоматического изменения заявки нет.

Backend рассчитывает все варианты по прежним правилам demo-0.2 и формирует проверяемые карточки факторов. **Модель выбирает значимые карточки и их порядок, а итоговый текст собирается из этих карточек на сервере.** Это ограниченная генерация структуры объяснения: модель не пишет произвольные условия и числа. Ответ содержит ссылки factor_id/candidate_id; неизвестные, повторные и относящиеся к другому варианту ссылки приводят к явному FALLBACK. Числовые карточки UI брать из scenarios.

## 1. Запуск

Существующий `.env` и база сохраняются. Новых зависимостей и миграций нет; актуальна `0003_document_immutability`. Работает существующая таблица `advisor_reports`.

Из корня проекта:

```powershell
cd C:\alpha\alpha-hakaton
.\.venv\Scripts\alembic.exe upgrade head
.\.venv\Scripts\python.exe -m credit_cabinet.seed --check-only
.\.venv\Scripts\python.exe -m credit_cabinet
```

Открыть http://localhost:8000/docs. `GET /health/ready` → 200; доступность модели на readiness не влияет.

Без Ollama или модели endpoint тоже работает: вернет расчеты и шаблонное объяснение с `status=FALLBACK`, причиной в `error_code`. Это не результат генерации нейросети. Для настоящего `SUCCESS` нужен локальный Ollama и загруженная модель.

На этом ноутбуке Ollama находится в `%LOCALAPPDATA%\Programs\Ollama\ollama.exe`; если команда отсутствует в PATH, использовать полный путь:

```powershell
& "$env:LOCALAPPDATA\Programs\Ollama\ollama.exe" list
& "$env:LOCALAPPDATA\Programs\Ollama\ollama.exe" pull qwen3:4b
```

Если Ollama уже отвечает на `http://127.0.0.1:11434/api/tags`, он готов. Если не запущен, в отдельном терминале:

```powershell
& "$env:LOCALAPPDATA\Programs\Ollama\ollama.exe" serve
```

Оставить его терминал открытым на время проверки. Не запускать второй экземпляр на занятом порту. При доступном PATH команды эквивалентны `ollama list`, `ollama pull qwen3:4b`, `ollama serve`. Получение весов требует интернета; генерация после подготовки работает локально. Подготовленные веса сохраняются между перезапусками.

Параметры читаются из env, `.env.example` содержит шаблон. Добавлять их все в уже настроенный `.env` не обязательно — значения по умолчанию те же:

| Переменная | По умолчанию / назначение |
| --- | --- |
| LLM_ENABLED | true; false явно включает шаблонный режим |
| LLM_BASE_URL | http://127.0.0.1:11434; в Compose обычно http://ollama:11434 |
| LLM_MODEL | qwen3:4b |
| LLM_MODEL_DIGEST | Необязательный pin sha256:…; несовпадение → FALLBACK |
| LLM_TIMEOUT_SECONDS | 45; допустимо 1–120 секунд на обращение к модели |
| LLM_MAX_PARALLEL | 1; допустимо 1–4, лимит на процесс API |

После изменения env перезапустить backend. Адрес runtime задается только конфигурацией сервера, не телом HTTP-запроса. HTTP-адаптер не использует системный proxy и не следует redirect. Схема интеграции — [Ollama chat API](https://docs.ollama.com/api/chat), [structured outputs](https://docs.ollama.com/capabilities/structured-outputs).

## 2. Войти и подготовить новую заявку C01

1. `GET /api/auth/csrf` → скопировать csrf_token.
2. `POST /api/auth/login`: `client@example.com`, свой пароль, `X-CSRF-Token` из шага 1.
3. Снова `GET /api/auth/csrf` → токен текущей сессии для POST/PATCH/logout.
4. `GET /api/companies` → UUID C01 (ИНН 0000000001); `GET /api/products` → UUID WC_DEMO/version=2.
5. `POST /api/applications` с company_id/product_id; сохранить ID новой заявки и version.
6. `PATCH /api/applications/{id}` с CSRF:

```json
{
  "expected_version": 1,
  "requested_amount": "1000000.00",
  "term_months": 12,
  "purpose_code": "INVENTORY",
  "draft_data": {
    "confirmations": {
      "data_confirmed": true,
      "credit_history_check_allowed": true
    }
  }
}
```

Использовать фактическую expected_version, из ответа взять новую version. Для AI обязателен именно credit_history_check_allowed=true; data_confirmed отдельно обязателен только при отправке. Ни один флаг не устанавливается моделью.

## 3. Объяснить заявку

В группе advisor выполнить `POST /api/applications/{application_id}/advisor` с CSRF:

```json
{
  "expected_version": 2,
  "mode": "EXPLAIN"
}
```

Подставить актуальную версию. Ожидается 200:

- `status=SUCCESS` при проверенной генерации, иначе `FALLBACK` с error_code.
- `is_current=true`, `revision_id=null`, `draft_lock_version` — исходная версия.
- `explanation.summary` — текст и factor_ids; `next_step` — следующий шаг; `notice` отмечает демонстрационность и отсутствие гарантии выдачи.
- Для исходной C01 первый scenarios: сумма 1000000.00, срок 12, платеж 94559.60, риск-балл 10, preliminary_route=APPROVE. Это предварительные демо-правила, не финальное одобрение.
- `model_id`, `model_digest`, `prompt_version`, `generation_config`, `latency_ms` позволяют проверить фактическое происхождение ответа. В FALLBACK без вызова модели model_id/digest могут быть null.

Сохранить ID отчета. GET `/api/applications/{id}/advisor` возвращает последний отчет, GET `/api/applications/{id}/advisor-reports/{report_id}` — конкретный. Для GET CSRF не нужен, cookie обязательна. GET не вызывает модель и не продлевает idle-сессию.

Проверить GET заявки: status/version/сумма остались прежними. Создание отчета не создает отправку, assessment или решение и не меняет UI-шаг.

## 4. Сравнить варианты

Тот же POST, та же текущая версия заявки, `mode=COMPARE`:

```json
{
  "expected_version": 2,
  "mode": "COMPARE"
}
```

В scenarios до трех вариантов: REQUESTED, LOWER_AMOUNT, LONGER_TERM; дубли на границах продукта исключаются. В explanation.comparisons есть соответствующие candidate_id и проверенные ссылки. Модель не выбирает параметры вместо пользователя. UI-кнопка «Выбрать» должна отдельно вызвать существующий PATCH суммы/срока; затем отдельная отправка.

## 5. Актуальность и недостающие данные

1. Сохранить старый report_id. PATCH только ui_step=REVIEW с актуальной expected_version. GET старого отчета → is_current=true: служебная версия выросла, финансовый смысл тот же.
2. PATCH requested_amount=900000.00. GET старого отчета → is_current=false, старые расчеты не переписаны.
3. Новый POST advisor с новой expected_version → новый отчет с другим input_hash и актуальными числами.
4. Для дозапроса можно в отдельной демо-заявке убрать один месяц из draft_data.financial_months. При заполненных сумме/сроке/цели и подтверждении AI покажет MISSING_DATA и COMPLETE_DATA; пропуск не заменяется нулем. Исходный CSV-документ не редактируется.

При неполных базовых параметрах API вернет 422 с путями полей; сначала заполнить форму. Если в ходе генерации поменять сумму в другой вкладке, отчет сохранится по исходным данным и вернется с is_current=false. Он не перезапишет более свежую форму. Новая официальная оценка/решение тоже делает старый разбор неактуальным. Для предпросмотра также отслеживается изменение локальных файлов источников; GET проверяет отпечаток, не запускает проверки.

## 6. Подтверждение, права и банковский просмотр

На редактируемой заявке снять credit_history_check_allowed через PATCH. POST advisor и GET сохраненного отчета → 422 CREDIT_HISTORY_CONFIRMATION_REQUIRED. До этой проверки не читаются оценки/БКИ из кэша, не вызывается модель, новый отчет не создается. Возвращение флага true — отдельное действие пользователя.

Выйти через POST logout с CSRF, войти client2@example.com со своим паролем: чтение/генерация по чужой заявке → 404. Без сессии → 401. Устаревшая expected_version → 409, модель не вызывается. CSRF обязателен для POST.

Сотрудник не генерирует второй AI-продукт: он только читает отчеты клиента, **созданные по отправленному снимку**. Для проверки:

1. Войти первым клиентом, подтвердить данные и отправить заявку по SUBMISSION_CHECK.md.
2. С актуальной версией заявки выполнить новый POST advisor. Теперь revision_id заполнен, draft_lock_version=null; используются сохраненные официальные факты, без повторных вызовов источников.
3. Выйти и войти bank@example.com. GET `/api/bank/applications/{id}/advisor` → последний доступный отчет по отправке; GET `/api/bank/applications/{id}/advisor-reports/{report_id}` → конкретный.
4. Отчет, созданный до отправки по черновику, остается закрытым для банка даже после отправки той же заявки. Такой ID вернет 404. Внутренние комментарии банка не входят в AI-контекст.

## 7. Явная деградация

Для воспроизводимой проверки поставить `LLM_ENABLED=false` в `.env` и перезапустить API. Новый POST advisor → 200, status=FALLBACK/error_code=LLM_DISABLED с корректными расчетами и шаблонным объяснением. После проверки вернуть true и перезапустить.

Другие коды: LLM_UNAVAILABLE — runtime/HTTP недоступен; LLM_MODEL_UNAVAILABLE — нет модели; LLM_MODEL_MISMATCH — pin не совпал; LLM_TIMEOUT — время истекло; LLM_BUSY — лимит генераций занят; LLM_RESPONSE_INVALID — неприемлемый ответ; LLM_CONTEXT_TOO_LARGE — превышен предел контекста. Все они означают явный fallback, не кредитный отказ. Иных скрытых попыток/бесконечной очереди нет. Login, черновики, документы, рассмотрение и readiness продолжают работать.

## 8. Проверки разработчика и остановка

Обычные тесты используют подставной ответ адаптера или явный disabled-режим; сеть и веса не нужны. Отдельные тесты PostgreSQL проверяют сохранность JSONB и изменение заявки другим подключением во время генерации.

Реальная модель проверяется отдельно, без изменений основной БД:

```powershell
$env:TEST_OLLAMA_URL = 'http://127.0.0.1:11434'
$env:TEST_OLLAMA_MODEL = 'qwen3:4b'
.\.venv\Scripts\pytest.exe -q -s tests/test_advisor_live.py
Remove-Item Env:TEST_OLLAMA_URL
Remove-Item Env:TEST_OLLAMA_MODEL
```

Три сценария: объяснение C01, сравнение C01, пропущенный финансовый месяц. Метрики выводятся как live_benchmark; тест требует именно SUCCESS. Это проверка контракта и скорости конкретной машины, не исследование качества кредитной модели.

21 октября 2026 года три сценария прошли с настоящей qwen3:4b в Ollama 0.40.5. Замеры: EXPLAIN_C01 — 5746 мс (с загрузкой), COMPARE_C01 — 3399 мс, пропущенные финансы — 1461 мс. Сохранены [результаты, digest и параметры](docs/ai_benchmark.json). Измерена длительность вызовов адаптера, не всего API; трех запросов недостаточно для статистического вывода о производительности.

Остановить свой backend через Ctrl+C в его терминале. Если запускали Ollama serve сами — Ctrl+C в его терминале тоже. Работающий до проверки пользовательский Ollama автоматически не останавливать. Веса сохраняются.

Ксюше: обе кнопки используют один endpoint с mode, перед вызовом дождаться сохранения формы. Во время генерации показать загрузку; данные/платежи рисовать из scenarios, объяснение — из explanation со ссылками на factors. Всегда различать SUCCESS/FALLBACK и is_current; на 409 обновлять заявку, на 422 подсвечивать подтверждение/поля. Старый отчет можно восстановить GET без повторной генерации. Сотруднику использовать только bank-маршруты.

Диме: LLM_BASE_URL=http://ollama:11434, model runtime и веса в отдельном постоянном volume; подготовить модель до приемки. Зафиксировать версию runtime и digest, при желании выставить LLM_MODEL_DIGEST. AI не входит в health/ready backend. Ограничение параллелизма на процесс: демонстрационный запуск с одним worker; при нескольких worker нагрузку на GPU надо отдельно согласовать. Формат Ollama — stream=false, think=false, JSON Schema, temperature=0, seed=42, num_ctx=4096, num_predict=384. Секретов или платных API нет.
