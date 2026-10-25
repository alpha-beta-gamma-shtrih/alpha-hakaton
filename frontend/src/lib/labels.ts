import type { ApplicationStatus, CheckSource, CheckStatus, FormStep, ProvenanceItem, Purpose, RiskBand, Routing } from '../api/types'
import { monthName } from './format'

export const STATUS: Record<ApplicationStatus, { label: string; tone: string; color: string; hint: string }> = {
  DRAFT: { label: 'Черновик', tone: 'draft', color: 'var(--muted)', hint: 'Заявка ещё не отправлена. Данные сохраняются автоматически.' },
  SUBMITTED: { label: 'Заявка отправлена', tone: 'submitted', color: 'var(--blue)', hint: 'Данные зафиксированы, проверки запускаются.' },
  CHECKING: { label: 'Проверяем данные', tone: 'checking', color: 'var(--blue)', hint: 'Идут проверки и оценка риска.' },
  NEEDS_INFO: { label: 'Нужны уточнения', tone: 'needs_info', color: 'var(--amber)', hint: 'Дополните сведения и отправьте заявку снова.' },
  MANUAL_REVIEW: { label: 'На рассмотрении специалиста', tone: 'manual_review', color: 'var(--violet)', hint: 'Заявку изучает сотрудник банка.' },
  APPROVED: { label: 'Одобрено', tone: 'approved', color: 'var(--lime)', hint: 'Решение принято. Условия ниже.' },
  SIGNED: { label: 'Подписано', tone: 'approved', color: 'var(--lime)', hint: 'Демо-документ подписан. Электронная подпись имитирована, средства не выдаются.' },
  REJECTED: { label: 'Отказано', tone: 'rejected', color: 'var(--red)', hint: 'Решение принято. Причины ниже.' },
}

export const FINAL_STATUSES: ApplicationStatus[] = ['APPROVED', 'REJECTED', 'SIGNED']
export const EDITABLE_STATUSES: ApplicationStatus[] = ['DRAFT', 'NEEDS_INFO']
export const PROCESSING_STATUSES: ApplicationStatus[] = ['SUBMITTED', 'CHECKING']

export const PURPOSE: Record<Purpose, { label: string; desc: string }> = {
  INVENTORY: { label: 'Закупка товара или материалов', desc: 'Пополнить склад, закупить сырьё и комплектующие' },
  OPERATING_EXPENSES: { label: 'Текущие расходы бизнеса', desc: 'Зарплаты, аренда, налоги и платежи поставщикам' },
  SEASONAL_PURCHASE: { label: 'Закупка к сезону', desc: 'Подготовиться к пиковому спросу заранее' },
  EQUIPMENT: { label: 'Покупка или замена оборудования', desc: 'Обновить оборудование для работы бизнеса' },
  OTHER: { label: 'Иное', desc: 'Другая задача бизнеса, без целевой скидки' },
}

export const STEPS: { id: FormStep; title: string; short: string }[] = [
  { id: 'NEED', title: 'Потребность', short: 'Цель, сумма и срок' },
  { id: 'COMPANY', title: 'Компания', short: 'Реквизиты бизнеса' },
  { id: 'FINANCES', title: 'Финансы', short: 'Шесть месяцев' },
  { id: 'REVIEW', title: 'Проверка', short: 'Подтверждения и отправка' },
]

export const RISK: Record<RiskBand, { label: string; color: string }> = {
  LOW: { label: 'Низкий риск', color: 'var(--lime)' },
  MEDIUM: { label: 'Средний риск', color: 'var(--amber)' },
  HIGH: { label: 'Высокий риск', color: 'var(--red)' },
  UNKNOWN: { label: 'Риск не оценён', color: 'var(--muted-2)' },
}

export const ROUTING: Record<Routing, string> = {
  APPROVE: 'Проходит правила',
  REJECT: 'Не проходит правила',
  NEEDS_INFO: 'Нужны сведения',
  MANUAL_REVIEW: 'Ручной разбор',
}

export const CHECK_SOURCE: Record<CheckSource, { label: string; desc: string }> = {
  DATA_QUALITY: { label: 'Полнота данных', desc: 'Все месяцы и поля заполнены корректно' },
  FNS: { label: 'Юридическая проверка', desc: 'Демо-симулятор ЕГРЮЛ/ФНС' },
  BKI: { label: 'Кредитная история', desc: 'Демо-симулятор бюро кредитных историй' },
}

export const CHECK_STATUS: Record<CheckStatus, { label: string; tone: 'ok' | 'warn' | 'error' }> = {
  SUCCESS: { label: 'Успешно', tone: 'ok' },
  NO_DATA: { label: 'Нет данных', tone: 'warn' },
  ERROR: { label: 'Техническая ошибка', tone: 'error' },
}

export const PROVENANCE: Record<ProvenanceItem['source'], { label: string; mock: boolean }> = {
  DEMO_PROFILE: { label: 'Демонстрационный профиль', mock: true },
  CLIENT_DECLARED: { label: 'Указано пользователем', mock: false },
  MOCK_FNS: { label: 'Юридический демо-симулятор', mock: true },
  MOCK_BKI: { label: 'Демо-симулятор кредитной истории', mock: true },
}

export const LEGAL_FORM: Record<string, string> = { OOO: 'ООО', IP: 'ИП' }

export const FIN_FIELDS = [
  { key: 'cash_inflow', label: 'Поступления', hint: 'Выручка от деятельности. Без полученных кредитов, взносов собственника и внутренних переводов.' },
  { key: 'operating_outflow', label: 'Операционные выплаты', hint: 'Реальные расходы и налоги. Без платежей по долгам и внутренних переводов.' },
  { key: 'existing_debt_payment', label: 'Платежи по долгам', hint: 'Тело и проценты по действующим кредитам за месяц. Нет платежа — 0.' },
] as const

export type FinKey = (typeof FIN_FIELDS)[number]['key']

const FIELD_LABELS: Record<string, string> = {
  requested_amount: 'Сумма',
  term_months: 'Срок',
  purpose_code: 'Цель финансирования',
  purpose_details: 'Описание цели',
  'draft_data.info_response': 'Ответ на запрос',
  'draft_data.financial_months': 'Финансовые показатели целиком',
}

/** Human label for a requested_fields path such as draft_data.financial_months.2026-04-01.cash_inflow */
export function requestedFieldLabel(path: string): string {
  if (FIELD_LABELS[path]) return FIELD_LABELS[path]
  const m = path.match(/^draft_data\.financial_months\.(\d{4}-\d{2}-\d{2})\.(\w+)$/)
  if (m) {
    const f = FIN_FIELDS.find((x) => x.key === m[2])
    return `${f?.label ?? m[2]} · ${monthName(m[1])}`
  }
  return path
}

export const EVENT_LABELS: Record<string, string> = {
  DRAFT_CREATED: 'Черновик создан',
  DRAFT_ARCHIVED: 'Черновик удалён из кабинета',
  SUBMITTED: 'Заявка отправлена',
  RESUBMITTED: 'Заявка отправлена повторно',
  PROCESSING_STARTED: 'Начата обработка',
  CHECKS_COMPLETED: 'Проверки завершены',
  DECISION_MADE: 'Решение зафиксировано',
  AGREEMENT_SIGNED: 'Демо-документ подписан',
  INFO_REQUESTED: 'Запрошены уточнения',
  INFORMATION_REQUESTED: 'Запрошены уточнения',
  MANUAL_DECISION: 'Решение сотрудника',
  MANUAL_DECISION_MADE: 'Решение сотрудника',
  PROCESSING_RETRIED: 'Повтор обработки',
  RETRY_PROCESSING: 'Повтор обработки',
}

export const eventLabel = (t: string) => EVENT_LABELS[t] ?? t.replace(/_/g, ' ').toLowerCase().replace(/^\w/, (c) => c.toUpperCase())

export const ADVISOR_CANDIDATE: Record<string, { label: string; color: string }> = {
  REQUESTED: { label: 'Исходный запрос', color: 'var(--ink)' },
  LOWER_AMOUNT: { label: 'Меньше сумма', color: 'var(--blue)' },
  LONGER_TERM: { label: 'Дольше срок', color: 'var(--violet)' },
}
