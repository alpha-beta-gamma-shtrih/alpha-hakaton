# Демо-документы: проверка через Swagger

> Обновление demo-0.3: для нового продукта WC_DEMO/version=3 действуют [PRICING.md](PRICING.md) и [PRICING_CHECK.md](PRICING_CHECK.md): 20% минимум, 6–60 месяцев, пять целей и персональные скидки. Числа и примеры demo-0.2 ниже относятся к историческому продукту v2; новые заявки проверять по PRICING_CHECK.md. Текущая миграция — 0005_personal_pricing.

Документ — подготовленное финансовое приложение к заявке. CSV позволяет клиенту и сотруднику скачать исходный демо-профиль, а `document_refs` в отправленном снимке фиксирует ID, метаданные и SHA-256 конкретного файла. Это помогает воспроизвести состав отправки. Документ не является подтвержденной банковской выпиской; решение считается по `financial_snapshot`, проверки содержимого документа и OCR отсутствуют.

## 1. Запустить из своего терминала

Существующий `.env` сохраняется. Новое необязательное поле `DOCUMENTS_DIR=.data/documents` уже имеет такое значение по умолчанию; добавлять его в настроенный `.env` не обязательно. PostgreSQL должен работать.

```powershell
cd C:\alpha\alpha-hakaton
.\.venv\Scripts\alembic.exe upgrade head
.\.venv\Scripts\python.exe -m credit_cabinet.seed --check-only
.\.venv\Scripts\python.exe -m credit_cabinet.seed
.\.venv\Scripts\python.exe -m credit_cabinet
```

Миграция `0003_document_immutability` запрещает UPDATE/DELETE метаданных документов. Старые заявки и снимки не меняет, таблиц по-прежнему 15. Повторный seed ничего не сбрасывает и сохраняет пароли существующих аккаунтов; для новых аккаунтов текущего набора использует индивидуальные пароли из demo_data/demo_0_3/demo_users.json.

Открыть http://localhost:8000/docs. `GET /health/ready` → 200, `schema_revision=0004_draft_archive`. При 503 сначала проверить миграции/доступность PostgreSQL.

## 2. Войти клиентом и создать новую заявку

1. `GET /api/auth/csrf` → скопировать `csrf_token`.
2. `POST /api/auth/login`: email `client@example.com`, свой ранее заданный пароль, в `X-CSRF-Token` — токен из шага 1.
3. Снова `GET /api/auth/csrf` → токен текущей сессии для всех POST/PATCH, включая logout. После каждого нового входа получать его заново.
4. `GET /api/companies` → ID компании C01 (ИНН `0000000001`). `GET /api/products` → ID WC_DEMO/version=2.
5. `POST /api/applications` с CSRF:

```json
{
  "company_id": "UUID компании C01",
  "product_id": "UUID продукта"
}
```

Ожидается 201. Сохранить `id` заявки, актуальную `version` и `documents[0].id`. В массиве один документ: `kind=FINANCIAL_STATEMENT`, `source=DEMO`, `original_filename=C01.csv`, `mime_type=text/csv`, `application_id` созданной заявки, размер и 64-символьный `content_sha256`. `download_url` указывает на `/api/documents/{id}`. Внутреннего `storage_key` и пути диска в ответе нет.

## 3. Скачать клиентом и проверить ограничения до отправки

В группе `documents` выполнить `GET /api/documents/{document_id}` с ID из ответа, нажать Try it out → Execute. **CSRF для скачивания не нужен**: это GET, достаточно cookie, установленной при входе.

Ожидается 200 и CSV с шестью месяцами апрель–сентябрь 2026 года. Заголовки: `Content-Disposition: attachment`, `Content-Type: text/csv; charset=utf-8`, `X-Content-SHA256`, `Cache-Control: no-store`, `X-Content-Type-Options: nosniff`. Swagger может показать Download file либо содержимое CSV. Можно открыть `http://localhost:8000/api/documents/UUID` в том же браузере — файл скачается с той же cookie. Имя скачанного файла содержит серверный UUID; исходное имя остается в метаданных.

При желании сравнить хеш скачанного файла из PowerShell:

```powershell
Get-FileHash -Algorithm SHA256 -LiteralPath 'C:\Users\user\Downloads\имя-скачанного-файла.csv'
```

Хеш должен совпасть с `content_sha256` без учета регистра. Не пересохранять CSV перед проверкой: редактор может изменить окончания строк.

Затем `POST /api/auth/logout` с текущим CSRF и войти как `bank@example.com` по той же последовательности csrf → login → csrf. Пароль — свой пароль сотрудника, он может отличаться от клиентского. `GET /api/documents/{тот же id}` **до отправки** → 404 `DOCUMENT_NOT_FOUND`. Наличие банковской роли само по себе не открывает документы черновика.

## 4. Отправить заявку и проверить снимок

Выйти сотрудником и снова войти клиентом. Получить заявку через `GET /api/applications/{id}` и взять фактическую `version`. `PATCH /api/applications/{id}` с CSRF:

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

В `expected_version` подставить актуальное значение. Ответ → 200, получить новую `version`. Создать ключ отправки (это не пароль):

```powershell
[guid]::NewGuid().ToString()
```

`POST /api/applications/{id}/submit` с CSRF:

```json
{
  "expected_version": 2,
  "submission_key": "полученный UUID"
}
```

Подставить версию из PATCH. Ожидается 200, для исходного C01 — `APPROVED`. В `revision.document_refs` тот же ID, SHA-256 и размер документа. `GET /api/applications/{id}/revisions/1` возвращает этот же список. Повтор submit с **тем же ключом и исходной expected_version** возвращает тот же снимок и не добавляет документы/версии.

## 5. Проверить сотрудника, другого клиента и выход

1. Выйти клиентом, войти `bank@example.com`, обновить CSRF.
2. `GET /api/bank/applications/{id}` → в `revision.document_refs` документ отправки. Финальная заявка не входит в очередь по умолчанию; при поиске через очередь нужен `status=APPROVED`.
3. `GET /api/documents/{document_id}` → 200, тот же CSV и SHA-256. Исторические отправленные документы также доступны через ссылки конкретной версии.
4. Выйти сотрудником, войти `client2@example.com` со своим паролем второго клиента: тот же download → 404 `DOCUMENT_NOT_FOUND`, как для неизвестного UUID.
5. Выйти, повторить GET без сессии → 401 `AUTH_REQUIRED`.

Документы проверяются на принадлежность при каждом запросе. Прямого публичного каталога, загрузки произвольных файлов, удаления и замены через API нет. При отсутствии/повреждении файла разрешенному пользователю возвращается 503 `DOCUMENT_UNAVAILABLE`, постороннему — 404. Это техническая ошибка, не кредитный отказ.

## 6. Что сохраняется и как остановить

Остановить **свой** API сочетанием `Ctrl+C` в терминале запуска. При следующем запуске файлы и связи сохраняются. PostgreSQL останавливать для этого не нужно.

- Исходные шаблоны: `demo_data/demo_0_2/documents/*.csv`, описаны в `manifest.json`; входят в Git/поставку.
- При создании заявки backend проверяет шаблон и создает приватную копию в `DOCUMENTS_DIR` и запись `documents` в БД. `.data/` исключена из Git. Смена исходного CSV не меняет существующую копию.
- Снимок сохраняет перечень файлов внутри транзакции отправки; до нее проверяется доступность и SHA-256 копии. Файл в БД бинарно не хранится.
- При откате создания возможен файл без записи БД: он недоступен через API. Автоматического удаления/сборщика таких файлов в MVP нет.
- Старые отправленные снимки с `document_refs=[]` остаются пустыми. Старый DRAFT/NEEDS_INFO без документов получает их при следующей **новой успешной отправке**; GET/preview/повтор старого submission_key ничего не прикрепляют.
- CSV представляет исходный **DEMO-профиль**, а редактируемые финансовые данные могут стать CLIENT_DECLARED. После редактирования CSV не переписывается и не подтверждает новый ввод. Расчет использует только сохраненный финансовый снимок; автоматической сверки CSV с вводом нет.

Ксюше: читать `application.documents` для клиента, `revision.document_refs` для банка/исторической версии. Скачивать только по `download_url` с cookie; через общий origin/dev proxy, при fetch — сохранять ответ как Blob и обрабатывать ошибки до скачивания. Если UI использует индикатор активности, учитывать реальное нажатие кнопки: сам GET не продлевает idle-сессию.

Диме: включить `DEMO_DATASET_DIR` в образ/поставку на чтение и смонтировать отдельный **постоянный записываемый volume** в `DOCUMENTS_DIR`; передать этот путь через env. Не публиковать каталог через nginx/static. Сохранять PostgreSQL и документы вместе при резервировании/переносе; потерянный volume нельзя восстановить простым повторным seed. Запуск и зависимости не изменились.
