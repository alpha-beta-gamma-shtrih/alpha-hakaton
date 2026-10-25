/* In-browser demo API (VITE_API_MODE=mock).
   Mirrors the FastAPI contract closely enough to walk the whole flow without a backend:
   same paths, DTO shapes, error format, versions/409, CSRF, and demo-policy-0.3 with personal pricing
   on the team's synthetic set (demo_data/demo_0_3, see npm run gen:mock).
   The real credit logic lives in the backend (services/policy.py, services/pricing.py); this mirrors it for the demo. */
import type { TransportResponse } from '../client'
import type {
  AdvisorReport,
  Agreement,
  ApplicationStatus,
  BankAssessment,
  BankCard,
  BankCheck,
  BankDecision,
  BankEvent,
  BankInfoRequest,
  BankQueueItem,
  OfferPreview,
  Candidate,
  Draft,
  FinancialMonth,
  Provenance,
  Reason,
  Revision,
  RiskBand,
  Routing,
  ScenarioSet,
} from '../types'
import { CALCULATION_DATE, DEMO_BKI, DEMO_COMPANIES, DEMO_FNS, DEMO_MONTHS, DEMO_PRODUCT, DEMO_SCENARIOS, DEMO_USERS, FINANCIAL_MONTHS, REASON_TEXT, type DemoCompany, type DemoUser, type SourceFixture } from './data'

/* ---------------- state ---------------- */
interface AppRec {
  id: string
  owner_id: string
  company_id: string
  product_id: string
  status: ApplicationStatus
  version: number
  requested_amount: string | null
  term_months: number | null
  purpose_code: Draft['purpose_code']
  purpose_details: string | null
  financial_months: FinancialMonth[]
  purchase_from_bank_partner: boolean
  fin_declared: boolean
  confirmations: { data_confirmed: boolean; credit_history_check_allowed: boolean }
  info_response: string | null
  ui_step: Draft['ui_step']
  documents: Draft['documents']
  revisions: Revision[]
  assessments: BankAssessment[]
  decision: BankDecision | null
  info_requests: BankInfoRequest[]
  events: BankEvent[]
  advisor: AdvisorReport | null
  created_at: string
  updated_at: string
  archived?: boolean
  scenario_set?: { value: ScenarioSet; context: string; manually_changed: boolean }
  agreement?: Agreement
}

interface State {
  apps: AppRec[]
  session: { user_id: string; csrf: string } | null
  loginCsrf: string | null
}

const KEY = 'credit-cabinet-demo-v3'
const uid = () =>
  (crypto as Crypto & { randomUUID?: () => string }).randomUUID?.() ??
  'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, (c) => {
    const r = (Math.random() * 16) | 0
    return (c === 'x' ? r : (r & 0x3) | 0x8).toString(16)
  })
const now = () => new Date().toISOString()
const clone = <T,>(v: T): T => JSON.parse(JSON.stringify(v))

// Initialized at the end of the module, after all constants are defined.
let state: State

function load(): State {
  try {
    const raw = localStorage.getItem(KEY)
    if (raw) return JSON.parse(raw)
  } catch {
    /* storage may be unavailable */
  }
  const s: State = { apps: [], session: null, loginCsrf: null }
  seed(s)
  return s
}
function save() {
  try {
    localStorage.setItem(KEY, JSON.stringify(state))
  } catch {
    /* ignore */
  }
}
export function resetDemo() {
  try {
    localStorage.removeItem(KEY)
  } catch {
    /* ignore */
  }
  state = load()
}

/* ---------------- helpers ---------------- */
const ok = (body: unknown, status = 200): TransportResponse => ({ status, body: clone(body) })
const err = (status: number, code: string, message: string, field_errors: { field: string; message: string }[] = []): TransportResponse => ({
  status,
  body: { code, message, field_errors, request_id: uid() },
})

const allUsers = (): DemoUser[] => DEMO_USERS
const allCompanies = (): DemoCompany[] => DEMO_COMPANIES
const companyById = (id: string) => allCompanies().find((c) => c.id === id)
const userById = (id: string) => allUsers().find((u) => u.id === id)
const monthsOf = (c: DemoCompany): FinancialMonth[] => DEMO_MONTHS[c.key] ?? []
/** Two decimals, half-up like Decimal.quantize(ROUND_HALF_UP) in the backend. */
const money2 = (n: number) => (Math.round((n + Math.sign(n) * 1e-9) * 100) / 100).toFixed(2)
const rate3 = (n: number) => n.toFixed(3)

function ageMonths(from: string, to: string) {
  const [fy, fm, fd] = from.split('-').map(Number)
  const [ty, tm, td] = to.split('-').map(Number)
  return (ty - fy) * 12 + tm - fm - (td < fd ? 1 : 0)
}

function annuity(amount: number, term: number, annualPct: number) {
  const r = annualPct / 100 / 12
  const raw = r === 0 ? amount / term : (amount * r) / (1 - Math.pow(1 + r, -term))
  const payment = Number(money2(raw))
  return { monthly_payment: money2(payment), estimated_total_payment: money2(payment * term), estimated_overpayment: money2(payment * term - amount) }
}

function hash(v: unknown) {
  const s = JSON.stringify(v)
  let h1 = 0x811c9dc5
  for (let i = 0; i < s.length; i++) h1 = Math.imul(h1 ^ s.charCodeAt(i), 16777619)
  return (h1 >>> 0).toString(16).padStart(8, '0').repeat(8)
}

const reason = (code: string): Reason => ({ code, message: REASON_TEXT[code] ?? code })
const BASE_RATE = Number(DEMO_PRODUCT.annual_rate_percent)
const PURCHASE_PURPOSES = ['INVENTORY', 'SEASONAL_PURCHASE', 'EQUIPMENT']

/* ---------------- demo-policy-0.3 (mirror of services/policy.py and services/pricing.py) ---------------- */
const PRICING = {
  base: 20,
  minimum: 20,
  age: [2, 1, 0],
  history: { absent: 2, clean: 0, '1_29': 2, '30_59': 4 } as Record<string, number>,
  trend: [0, 1, 2],
  term: [0, 1, 2, 3, 4],
  purpose: { INVENTORY: 0.5, OPERATING_EXPENSES: 0, SEASONAL_PURCHASE: 0.5, EQUIPMENT: 1, OTHER: 0 } as Record<string, number>,
  bankCustomer: 0.5,
  partner: 0.5,
}

function quote(o: { age: number; history: boolean; overdue: number; trend: number; term: number; purpose: string; bankCustomer: boolean; partner: boolean }) {
  const historyKey = !o.history ? 'absent' : o.overdue >= 30 ? '30_59' : o.overdue ? '1_29' : 'clean'
  const additions: [string, string, number][] = [
    ['BUSINESS_AGE', 'Возраст бизнеса', PRICING.age[o.age < 12 ? 0 : o.age < 24 ? 1 : 2]],
    ['CREDIT_HISTORY', 'Кредитная история', PRICING.history[historyKey]],
    ['INFLOW_TREND', 'Динамика поступлений', PRICING.trend[o.trend <= -0.3 ? 2 : o.trend <= -0.15 ? 1 : 0]],
    ['TERM', 'Срок кредита', PRICING.term[Math.min(4, Math.floor((o.term - 1) / 12))]],
  ]
  const discounts: [string, string, number][] = [
    ['PURPOSE', 'Целевая программа', PRICING.purpose[o.purpose] ?? 0],
    ['BANK_CUSTOMER', 'Исправный заёмщик нашего банка · DEMO', o.bankCustomer && o.history && o.overdue === 0 ? PRICING.bankCustomer : 0],
    ['PARTNER', 'Покупка у партнёра · заявлено клиентом · DEMO', o.partner && PURCHASE_PURPOSES.includes(o.purpose) ? PRICING.partner : 0],
  ]
  const before = PRICING.base + additions.reduce((s, r) => s + r[2], 0)
  const requested = discounts.reduce((s, r) => s + r[2], 0)
  const final = Math.max(PRICING.minimum, before - requested)
  return {
    status: 'PERSONALIZED',
    pricing_version: 'demo-pricing-0.3',
    base_rate_percent: rate3(PRICING.base),
    minimum_rate_percent: rate3(PRICING.minimum),
    rate_before_discounts: rate3(before),
    requested_discount_pp: rate3(requested),
    applied_discount_pp: rate3(before - final),
    floor_adjustment_pp: rate3(final - (before - requested)),
    annual_rate_percent: rate3(final),
    additions: additions.map(([code, label, v]) => ({ code, label, percentage_points: rate3(v) })),
    discounts: discounts.map(([code, label, v]) => ({ code, label, percentage_points: rate3(v) })),
    bank_relationship_source: 'DEMO_BANK_PROFILE',
    has_active_loan_in_our_bank: o.bankCustomer,
    purchase_from_bank_partner: o.partner,
    purpose_code: o.purpose,
  }
}

const unpriced = (code: string) => ({ status: 'INDICATIVE', annual_rate_percent: rate3(BASE_RATE), reason_code: code })

/** The latest fixture row for this attempt: an explicit revision wins, then the newest run_no. */
function fixture(list: SourceFixture[], company: DemoCompany, revisionNo: number, runNo: number) {
  const choices = list.filter((r) => r.company_key === company.key && (r.revision_no === null || r.revision_no === revisionNo) && r.run_no <= runNo)
  if (!choices.length) return null
  return choices.reduce((best, r) => {
    const k = (x: SourceFixture) => (x.revision_no !== null ? 1000 : 0) + x.run_no
    return k(r) > k(best) ? r : best
  })
}

interface Evaluation {
  routing: Routing
  reason_codes: string[]
  risk_score: number | null
  details: Record<string, unknown>
  checks: BankCheck[]
  requested_fields: string[]
  facts: Record<string, unknown>
}

function evaluate(o: { company: DemoCompany; months: FinancialMonth[]; amount: number; term: number; purpose: string; partner: boolean; revisionNo: number; runNo: number; saved?: BankCheck[] }): Evaluation {
  const t = now()
  const res: Evaluation = { routing: 'MANUAL_REVIEW', reason_codes: [], risk_score: null, details: {}, checks: [], requested_fields: [], facts: {} }
  const finish = (route: Routing, code: string, fields: string[] = []) => {
    res.routing = route
    res.reason_codes = [code]
    res.requested_fields = fields
    if (!res.details.pricing) res.details.pricing = unpriced(code)
    return res
  }
  const consult = (source: 'FNS' | 'BKI') => {
    const row = o.saved ? o.saved.find(c => c.source === source) : fixture(source === 'FNS' ? DEMO_FNS : DEMO_BKI, o.company, o.revisionNo, o.runNo)
    const provenanceItem = { source: source === 'FNS' ? 'MOCK_FNS' : 'MOCK_BKI', as_of_date: CALCULATION_DATE, checked_at: t }
    const status = row?.status ?? 'NO_DATA'
    const data = row?.normalized_data ? { ...row.normalized_data, provenance: provenanceItem } : null
    res.checks.push({ source, status, reasons: [], source_version: source === 'FNS' ? 'legal-mock-0.2' : 'bki-mock-0.2', completed_at: t, started_at: t, normalized_data: data, error_code: row?.error_code ?? null })
    res.facts[source.toLowerCase()] = data
    return { status, error: row?.error_code ?? null, data: (row?.normalized_data ?? {}) as Record<string, any> }
  }

  const legal = consult('FNS')
  if (legal.status !== 'SUCCESS') return finish('MANUAL_REVIEW', legal.error === 'SOURCE_RESPONSE_INVALID' ? 'SOURCE_RESPONSE_INVALID' : 'SOURCE_FNS_UNAVAILABLE')
  const c = o.company as unknown as Record<string, unknown>
  if (['inn', 'legal_form', 'registered_on'].some((k) => String(legal.data[k]) !== String(c[k]))) return finish('MANUAL_REVIEW', 'COMPANY_DATA_MISMATCH')
  if (legal.data.registry_status !== 'ACTIVE') return finish('REJECT', 'COMPANY_NOT_ACTIVE')
  if (legal.data.is_bankrupt === true) return finish('REJECT', 'COMPANY_BANKRUPTCY')
  if (legal.data.is_bankrupt == null) return finish('MANUAL_REVIEW', 'LEGAL_STATUS_UNCONFIRMED')
  const age = ageMonths(o.company.registered_on, CALCULATION_DATE)
  res.details.business_age_months = age
  if (age < 6) return finish('REJECT', 'BUSINESS_TOO_YOUNG')

  const credit = consult('BKI')
  if (credit.status !== 'SUCCESS') return finish('MANUAL_REVIEW', credit.error === 'SOURCE_RESPONSE_INVALID' ? 'SOURCE_RESPONSE_INVALID' : 'SOURCE_BKI_UNAVAILABLE')
  const f = credit.data
  if (Number(f.current_overdue_amount) > 0) return finish('REJECT', 'CURRENT_OVERDUE')
  if (Number(f.max_overdue_days_12m) >= 60) return finish('REJECT', 'SEVERE_OVERDUE_HISTORY')

  const byMonth = new Map(o.months.map((m) => [m.month, m]))
  const missing: string[] = []
  for (const month of FINANCIAL_MONTHS)
    for (const k of ['cash_inflow', 'operating_outflow', 'existing_debt_payment'] as const)
      if (byMonth.get(month)?.[k] == null) missing.push(`draft_data.financial_months.${month}.${k}`)
  res.checks.push({
    source: 'DATA_QUALITY',
    status: missing.length ? 'NO_DATA' : 'SUCCESS',
    reasons: missing.length ? [reason('FINANCIAL_HISTORY_INCOMPLETE')] : [],
    source_version: 'data-quality-0.2',
    completed_at: t,
    started_at: t,
    normalized_data: missing.length ? null : { financial_month_count: 6 },
    error_code: missing.length ? 'FINANCIAL_HISTORY_INCOMPLETE' : null,
  })
  if (missing.length) return finish('NEEDS_INFO', 'FINANCIAL_HISTORY_INCOMPLETE', missing)

  const months = FINANCIAL_MONTHS.map((m) => byMonth.get(m)!)
  const declared = Number(months[5].existing_debt_payment)
  const confirmed = Number(f.current_monthly_payment)
  Object.assign(res.details, { declared_current_payment: money2(declared), confirmed_current_payment: money2(confirmed) })
  if (Math.abs(declared - confirmed) > Math.max(1000, 0.1 * Math.max(declared, confirmed)))
    return finish('NEEDS_INFO', 'DEBT_PAYMENT_MISMATCH', [`draft_data.financial_months.${FINANCIAL_MONTHS[5]}.existing_debt_payment`])
  const average = months.reduce((s, m) => s + Number(m.cash_inflow) - Number(m.operating_outflow), 0) / 6
  res.details.average_operating_cashflow = String(average)
  if (average <= 0) return finish('REJECT', 'NON_POSITIVE_CASHFLOW')
  const first = months.slice(0, 3).reduce((s, m) => s + Number(m.cash_inflow), 0)
  if (first === 0) return finish('MANUAL_REVIEW', 'TREND_BASELINE_ZERO')
  const trend = months.slice(3).reduce((s, m) => s + Number(m.cash_inflow), 0) / first - 1
  const pricing = quote({ age, history: !!f.history_present, overdue: Number(f.max_overdue_days_12m), trend, term: o.term, purpose: o.purpose, bankCustomer: o.company.has_active_loan_in_our_bank, partner: o.partner })
  res.details.pricing = pricing
  res.details.annual_rate_percent = pricing.annual_rate_percent
  const pay = annuity(o.amount, o.term, Number(pricing.annual_rate_percent))
  const existing = Math.max(declared, confirmed)
  const load = (existing + Number(pay.monthly_payment)) / average
  Object.assign(res.details, pay, { existing_payment: money2(existing), load_ratio: String(load) })
  if (load > 0.8) return finish('REJECT', 'DEBT_LOAD_LIMIT_EXCEEDED')

  const factors: { factor_id: string; points: number; value: string }[] = []
  const add = (code: string, points: number, value: unknown) => points && factors.push({ factor_id: code, points, value: String(value) })
  add(age < 12 ? 'BUSINESS_AGE_6_11' : 'BUSINESS_AGE_12_23', age < 12 ? 20 : age < 24 ? 10 : 0, age)
  if (load > 0.65) add('LOAD_65_80', 40, load)
  else if (load > 0.5) add('LOAD_50_65', 25, load)
  else if (load > 0.35) add('LOAD_35_50', 10, load)
  if (trend < -0.3) add('INFLOW_DROP_OVER_30', 25, trend)
  else if (trend < -0.15) add('INFLOW_DROP_15_30', 15, trend)
  else if (trend < 0) add('INFLOW_DROP_0_15', 5, trend)
  const overdue = Number(f.max_overdue_days_12m)
  if (overdue >= 30) add('OVERDUE_30_59', 25, overdue)
  else if (overdue > 0) add('OVERDUE_1_29', 10, overdue)
  if (!f.history_present) add('CREDIT_HISTORY_ABSENT', 15, false)
  const score = Math.min(100, factors.reduce((s, x) => s + x.points, 0))
  res.risk_score = score
  res.routing = score <= 29 ? 'APPROVE' : score <= 59 ? 'MANUAL_REVIEW' : 'REJECT'
  res.reason_codes = [score <= 29 ? 'DEMO_POLICY_PASSED' : score <= 59 ? 'BORDERLINE_RISK' : 'RISK_SCORE_LIMIT_EXCEEDED', ...factors.map((x) => x.factor_id)]
  Object.assign(res.details, { inflow_trend: String(trend), factors })
  return res
}

const bandOf = (score: number | null): RiskBand => (score === null ? 'UNKNOWN' : score <= 29 ? 'LOW' : score <= 59 ? 'MEDIUM' : 'HIGH')

/** Dev check: runs one of the 18 reference scenarios from demo_data/demo_0_3/scenarios.json. */
export function evaluateScenario(key: string, runNo = 1) {
  const s = DEMO_SCENARIOS.find((x) => x.key === key)!
  const company = DEMO_COMPANIES.find((c) => c.key === s.company_key)!
  const r = evaluate({ company, months: monthsOf(company), amount: Number(s.requested_amount), term: s.term_months, purpose: s.purpose_code, partner: s.purchase_from_bank_partner, revisionNo: 1, runNo })
  return { routing: r.routing, risk_score: r.risk_score, reason_codes: r.reason_codes, annual_rate_percent: (r.details.pricing as { status: string; annual_rate_percent: string }).status === 'PERSONALIZED' ? r.details.annual_rate_percent : null, monthly_payment: r.details.monthly_payment ?? null, expected: s.expected, sequence: s.sequence }
}

function provenance(app: AppRec, checked?: string): Provenance {
  return {
    company: checked
      ? { source: 'MOCK_FNS', as_of_date: CALCULATION_DATE, checked_at: checked }
      : { source: 'DEMO_PROFILE', as_of_date: CALCULATION_DATE, checked_at: null },
    financial_months: { source: app.fin_declared ? 'CLIENT_DECLARED' : 'DEMO_PROFILE', as_of_date: '2026-09-30', checked_at: null },
    credit_history: checked ? { source: 'MOCK_BKI', as_of_date: CALCULATION_DATE, checked_at: checked } : null,
  }
}

function addEvent(app: AppRec, e: Partial<BankEvent> & Pick<BankEvent, 'event_type' | 'message'>) {
  app.events.push({
    id: uid(),
    sequence_no: app.events.length + 1,
    from_status: null,
    to_status: null,
    created_at: now(),
    revision_id: null,
    actor_user_id: null,
    visibility: 'CLIENT',
    details: {},
    ...e,
  })
}

function setStatus(app: AppRec, to: ApplicationStatus, e: { event_type: string; message: string; actor?: string | null; visibility?: 'CLIENT' | 'BANK'; details?: Record<string, unknown> }) {
  const from = app.status
  app.status = to
  app.version++
  app.updated_at = now()
  addEvent(app, {
    event_type: e.event_type,
    message: e.message,
    from_status: from,
    to_status: to,
    actor_user_id: e.actor ?? null,
    revision_id: app.revisions.at(-1)?.id ?? null,
    visibility: e.visibility ?? 'CLIENT',
    details: e.details ?? {},
  })
}

/* ---------------- processing ---------------- */
function processLatest(app: AppRec, actor: string | null = null) {
  const rev = app.revisions.at(-1)!
  const company = companyById(app.company_id)!
  const fin = rev.financial_snapshot as { financial_months: FinancialMonth[]; purchase_from_bank_partner?: boolean }
  const runNo = app.assessments.filter((a) => a.revision_id === rev.id).length + 1
  const res = evaluate({ company, months: fin.financial_months, amount: Number(rev.requested_amount), term: rev.term_months, purpose: rev.purpose_code, partner: !!fin.purchase_from_bank_partner, revisionNo: rev.revision_no, runNo })
  const reasons = res.reason_codes.map(reason)
  const done = now()
  const assessment: BankAssessment = {
    id: uid(),
    revision_id: rev.id,
    run_no: runNo,
    rules_version: DEMO_PRODUCT.policy_version,
    risk_score: res.risk_score,
    risk_band: bandOf(res.risk_score),
    routing: res.routing,
    reasons,
    calculation_details: res.details,
    checks: res.checks,
    provenance: provenance(app, done),
    completed_at: done,
    started_at: done,
    input_facts: { company: rev.company_snapshot, ...res.facts, financial_months: fin.financial_months, calculation_date: CALCULATION_DATE },
  }
  app.assessments.push(assessment)
  const msg = reasons[0]?.message ?? 'Проверки завершены'
  if (res.routing === 'APPROVE' || res.routing === 'REJECT') {
    const outcome = res.routing === 'APPROVE' ? 'APPROVED' : 'REJECTED'
    setStatus(app, outcome, { event_type: 'CHECKS_COMPLETED', message: msg, actor, details: { run_no: runNo, assessment_id: assessment.id } })
    app.decision = {
      id: uid(),
      revision_id: rev.id,
      assessment_id: assessment.id,
      outcome,
      source: 'AUTO',
      approved_amount: outcome === 'APPROVED' ? rev.requested_amount : null,
      approved_term_months: outcome === 'APPROVED' ? rev.term_months : null,
      annual_rate_percent: outcome === 'APPROVED' ? String(res.details.annual_rate_percent ?? DEMO_PRODUCT.annual_rate_percent) : null,
      monthly_payment: outcome === 'APPROVED' ? String(res.details.monthly_payment) : null,
      reasons,
      public_explanation: msg,
      policy_version: DEMO_PRODUCT.policy_version,
      created_at: now(),
      decided_by_user_id: null,
      internal_comment: null,
    }
    addEvent(app, { event_type: 'DECISION_MADE', message: 'Зафиксирован итог демонстрационной проверки', from_status: outcome, to_status: outcome, revision_id: rev.id })
  } else if (res.routing === 'NEEDS_INFO') {
    setStatus(app, 'NEEDS_INFO', { event_type: 'CHECKS_COMPLETED', message: msg, actor, details: { run_no: runNo } })
    app.info_requests.push({
      id: uid(),
      revision_id: rev.id,
      created_by_user_id: null,
      requested_fields: res.requested_fields.length ? res.requested_fields : ['draft_data.financial_months'],
      message_to_client: msg,
      status: 'OPEN',
      answer_text: null,
      answered_revision_id: null,
      answered_at: null,
      created_at: now(),
    })
  } else {
    setStatus(app, 'MANUAL_REVIEW', { event_type: 'CHECKS_COMPLETED', message: msg, actor, details: { run_no: runNo, assessment_id: assessment.id } })
  }
}

function makeRevision(app: AppRec, key: string, userId: string): Revision {
  const company = companyById(app.company_id)!
  const fin = {
    financial_months: clone(app.financial_months),
    purchase_from_bank_partner: app.purchase_from_bank_partner,
    confirmations: clone(app.confirmations),
    info_response: app.info_response,
    purpose_details: app.purpose_details,
    provenance: provenance(app),
  }
  return {
    id: uid(),
    application_id: app.id,
    revision_no: app.revisions.length + 1,
    source_lock_version: app.version,
    submission_key: key,
    input_hash: hash([app.requested_amount, app.term_months, app.purpose_code, fin]),
    requested_amount: app.requested_amount!,
    term_months: app.term_months!,
    purpose_code: app.purpose_code!,
    company_snapshot: { ...companyPublic(company), provenance: provenance(app).company },
    financial_snapshot: fin,
    product_snapshot: { ...DEMO_PRODUCT },
    document_refs: clone(app.documents),
    schema_version: 2,
    submitted_by_user_id: userId,
    created_at: now(),
  }
}

/* ---------------- projections ---------------- */
function companyPublic(c: DemoCompany) {
  const { key: _k, has_active_loan_in_our_bank: _b, members: _m, ...rest } = c
  return rest
}

function latestAssessment(app: AppRec) {
  const rev = app.revisions.at(-1)
  return rev ? app.assessments.filter((a) => a.revision_id === rev.id).at(-1) ?? null : null
}

function clientAssessment(a: BankAssessment | null) {
  if (!a) return null
  const { input_facts: _i, started_at: _s, checks, ...rest } = a
  return { ...rest, checks: checks.map(({ normalized_data: _n, error_code: _e, started_at: _st, ...c }) => c) }
}

function clientDraft(app: AppRec): Draft {
  const open = app.info_requests.find((r) => r.status === 'OPEN')
  const editable = app.status === 'DRAFT' || app.status === 'NEEDS_INFO'
  const d = app.decision
  return {
    documents: app.documents,
    id: app.id,
    company_id: app.company_id,
    product_id: app.product_id,
    status: app.status,
    version: app.version,
    requested_amount: app.requested_amount,
    term_months: app.term_months,
    purpose_code: app.purpose_code,
    purpose_details: app.purpose_details,
    draft_data: { financial_months: app.financial_months, purchase_from_bank_partner: app.purchase_from_bank_partner, confirmations: app.confirmations, info_response: app.info_response },
    ui_step: app.ui_step,
    calculation_date: CALCULATION_DATE,
    policy_version: DEMO_PRODUCT.policy_version,
    provenance: provenance(app),
    allowed_actions: editable ? ['EDIT_DRAFT', 'SUBMIT'] : app.status === 'APPROVED' ? ['SIGN_AGREEMENT'] : [],
    signature: app.agreement?.signature ?? null,
    open_information_request: open ? { id: open.id, message_to_client: open.message_to_client, requested_fields: open.requested_fields } : null,
    decision: d
      ? (({ decided_by_user_id: _u, internal_comment: _c, offer_risk_score: _s, offer_risk_band: _b, ...pub }) => pub)(d)
      : null,
    latest_revision_id: app.revisions.at(-1)?.id ?? null,
    latest_revision_no: app.revisions.at(-1)?.revision_no ?? null,
    assessment: clientAssessment(latestAssessment(app)),
    created_at: app.created_at,
    updated_at: app.updated_at,
  }
}

const RETRY_REASONS = ['SOURCE_FNS_UNAVAILABLE', 'SOURCE_BKI_UNAVAILABLE', 'SOURCE_RESPONSE_INVALID', 'COMPANY_DATA_MISMATCH', 'LEGAL_STATUS_UNCONFIRMED']

function bankActions(app: AppRec): BankQueueItem['allowed_actions'] {
  const a = latestAssessment(app)
  if (app.status === 'SUBMITTED' || app.status === 'CHECKING') return ['RETRY_PROCESSING']
  if (app.status !== 'MANUAL_REVIEW' || !a) return []
  const codes = a.reasons.map((r) => r.code)
  if (RETRY_REASONS.includes(codes[0])) return ['RETRY_PROCESSING']
  if (codes[0] === 'BORDERLINE_RISK' && a.risk_score !== null && a.risk_score >= 30 && a.risk_score <= 59) return ['REQUEST_INFO', 'APPROVE', 'REJECT']
  if (codes.length === 1 && codes[0] === 'TREND_BASELINE_ZERO') return ['REQUEST_INFO']
  return []
}

function queueItem(app: AppRec): BankQueueItem {
  const c = companyById(app.company_id)!
  const rev = app.revisions.at(-1)!
  const a = latestAssessment(app)
  return {
    id: app.id,
    company_id: c.id,
    company_name: c.legal_name,
    inn: c.inn,
    product_id: DEMO_PRODUCT.id,
    product_code: DEMO_PRODUCT.code,
    product_version: DEMO_PRODUCT.version,
    risk_score: a?.risk_score ?? null,
    risk_band: a?.risk_band ?? 'UNKNOWN',
    assessment_reasons: a?.reasons ?? [],
    status: app.status,
    version: app.version,
    latest_revision_id: rev.id,
    latest_revision_no: rev.revision_no,
    requested_amount: rev.requested_amount,
    approved_amount: app.decision?.approved_amount ?? null,
    approved_term_months: app.decision?.approved_term_months ?? null,
    terms_changed: !!app.decision?.offer,
    term_months: rev.term_months,
    purpose_code: rev.purpose_code,
    submitted_at: rev.created_at,
    allowed_actions: bankActions(app),
  }
}

function bankCard(app: AppRec): BankCard {
  const rev = app.revisions.at(-1)!
  return {
    ...queueItem(app),
    signature: app.agreement?.signature ?? null,
    revision: rev,
    assessment: latestAssessment(app),
    decision: app.decision,
    open_information_request: app.info_requests.find((r) => r.status === 'OPEN') ?? null,
    information_requests: app.info_requests,
    revisions: app.revisions.map((r) => ({ id: r.id, revision_no: r.revision_no, input_hash: r.input_hash, created_at: r.created_at })),
  }
}

async function mockAgreement(app: AppRec): Promise<Agreement | null> {
  if (app.status === 'SIGNED' && app.agreement) return clone(app.agreement)
  const d = app.decision
  const revision = app.revisions.at(-1)
  if (app.status !== 'APPROVED' || d?.outcome !== 'APPROVED' || !revision) return null
  const company = companyById(app.company_id)!
  const total = Number(d.monthly_payment) * d.approved_term_months!
  const content: Agreement['content'] = {
    schema_version: 'DEMO-1', title: 'Демонстрационные условия кредитного договора',
    notice: 'Демонстрационный документ хакатона. Кнопка «Подписать» имитирует электронную подпись; юридически значимая электронная подпись не создаётся, договор с реальным банком не заключается, средства не выдаются.',
    issued_at: d.created_at, application_id: app.id, revision_id: revision.id, decision_id: d.id,
    company_name: company.legal_name, inn: company.inn, purpose_code: revision.purpose_code,
    approved_amount: d.approved_amount!, term_months: d.approved_term_months!,
    annual_rate_percent: d.annual_rate_percent!, monthly_payment: d.monthly_payment!,
    estimated_total_payment: money2(total), estimated_overpayment: money2(total - Number(d.approved_amount)),
  }
  const digest = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(JSON.stringify(content)))
  return { content, content_sha256: Array.from(new Uint8Array(digest), (b) => b.toString(16).padStart(2, '0')).join(''), signature: null }
}

function scenarioCandidates(app: AppRec, preview: boolean): Candidate[] | TransportResponse {
  const binding = app.decision?.outcome === 'APPROVED' ? app.decision : null
  const amount = Number(binding?.approved_amount ?? app.requested_amount)
  const term = binding?.approved_term_months ?? app.term_months
  if (!app.requested_amount || !term) return err(422, 'SCENARIO_INPUT_INCOMPLETE', 'Укажите сумму и срок, чтобы рассчитать варианты', [{ field: 'requested_amount', message: 'Обязательное поле' }])
  const p = DEMO_PRODUCT
  if (amount < Number(p.min_amount) || amount > Number(p.max_amount) || term < p.min_term_months || term > p.max_term_months)
    return err(422, 'VALIDATION_ERROR', 'Параметры вне границ продукта', [{ field: 'requested_amount', message: 'Сумма или срок вне границ продукта' }])
  const company = companyById(app.company_id)!
  const raw: [Candidate['candidate_id'], number, number][] = [
    ['REQUESTED', amount, term],
    ['LOWER_AMOUNT', Math.max(Number(p.min_amount), Math.round(amount * 80) / 100), term],
    ['LONGER_TERM', amount, Math.min(p.max_term_months, term + 12)],
  ]
  if (binding) raw.splice(1)
  const seen = new Set<string>()
  const checked = now()
  return raw
    .filter(([, a, t]) => {
      const k = `${a}-${t}`
      if (seen.has(k)) return false
      seen.add(k)
      return true
    })
    .map(([id, a, t]) => {
      const res = preview
        ? evaluate({ company, months: app.financial_months, amount: a, term: t, purpose: app.purpose_code ?? 'OTHER', partner: app.purchase_from_bank_partner, revisionNo: (app.revisions.at(-1)?.revision_no ?? 0) + 1, runNo: 1, saved: binding ? latestAssessment(app)?.checks : undefined })
        : null
      const pricing = (binding?.offer?.pricing as { annual_rate_percent: string } | undefined) ?? (res?.details.pricing as { annual_rate_percent: string } | undefined) ?? unpriced('CONSENT_REQUIRED')
      const pay = annuity(a, t, Number(pricing.annual_rate_percent))
      const codes = res ? res.reason_codes : ['CREDIT_HISTORY_CONFIRMATION_REQUIRED']
      return {
        candidate_id: id,
        requested_amount: money2(a),
        term_months: t,
        annual_rate_percent: binding?.annual_rate_percent ?? pricing.annual_rate_percent,
        pricing,
        ...pay,
        ...(binding ? { monthly_payment: binding.monthly_payment!, estimated_total_payment: money2(Number(binding.monthly_payment) * t), estimated_overpayment: money2(Number(binding.monthly_payment) * t - a) } : {}),
        load_ratio: (res?.details.load_ratio as string | undefined) ?? null,
        risk_score: res?.risk_score ?? null,
        preliminary_route: res?.routing ?? null,
        reason_codes: codes,
        reasons: codes.map(reason),
        provenance: preview ? provenance(app, checked) : provenance(app),
        policy_version: p.policy_version,
        input_hash: hash([a, t, app.financial_months, app.purpose_code, app.purchase_from_bank_partner]),
        is_binding: false,
      } as Candidate
    })
}

function optionContext(app: AppRec) {
  return hash([app.company_id, companyById(app.company_id), DEMO_PRODUCT, app.purpose_code,
    app.purchase_from_bank_partner, app.financial_months, app.fin_declared,
    app.confirmations.credit_history_check_allowed, app.revisions.at(-1)?.id, latestAssessment(app)?.id])
}

function optionView(app: AppRec): ScenarioSet | null {
  const stored = app.scenario_set
  if (!stored) return null
  const selected = stored.value.candidates.find((c) => c.candidate_id === stored.value.selected_candidate_id)
  const editable = app.status === 'DRAFT' || app.status === 'NEEDS_INFO'
  const current = editable && !stored.manually_changed && stored.context === optionContext(app)
    && selected?.requested_amount === app.requested_amount && selected?.term_months === app.term_months
  const visible = app.confirmations.credit_history_check_allowed || stored.value.mode === 'CALCULATION_ONLY'
  return { ...clone(stored.value), application_version: app.version, is_current: current,
    stale_reason: current ? null : editable ? 'Условия или расчётные данные изменены. Обновите варианты.' : 'Заявка уже отправлена; изменение условий недоступно.',
    selected_candidate_id: current ? stored.value.selected_candidate_id : null,
    candidates: visible ? clone(stored.value.candidates) : [], mode: visible ? stored.value.mode : 'CALCULATION_ONLY' }
}

function advisorReport(app: AppRec, mode: 'EXPLAIN' | 'COMPARE', cands: Candidate[], priority: AdvisorReport['priority'] = 'BALANCED'): AdvisorReport {
  const fmt = (v: string) => Number(v).toLocaleString('ru-RU', { minimumFractionDigits: 2 })
  const factors: AdvisorReport['factors'] = [
    { factor_id: 'DATA_ORIGIN', candidate_id: null, text: 'Финансы взяты из синтетического демо-профиля; проверки также демонстрационные.' },
    { factor_id: 'PRELIMINARY_ONLY', candidate_id: null, text: 'Сравнение не является решением банка и не изменяет заявку.' },
  ]
  const base = cands[0]
  let eligible = mode === 'COMPARE' && priority !== 'BALANCED' && app.status === 'DRAFT'
    ? cands.filter((c) => c.preliminary_route === 'APPROVE' && (priority !== 'KEEP_AMOUNT' || Number(c.requested_amount) >= Number(base.requested_amount))) : []
  const metric = priority === 'LOWER_OVERPAYMENT' ? 'estimated_overpayment' : 'monthly_payment'
  const best = Math.min(...eligible.map((c) => Number(c[metric])))
  eligible = eligible.filter((c) => Number(c[metric]) === best)
  for (const c of cands) {
    const routeText = c.preliminary_route === 'APPROVE' ? 'Проходит предварительные демо-правила.' : c.preliminary_route === 'MANUAL_REVIEW' ? 'Потребуется оценка сотрудника.' : c.preliminary_route === 'REJECT' ? 'Не проходит предварительные демо-правила.' : 'Нужны дополнительные сведения.'
    factors.push({ factor_id: `${c.candidate_id}_PAYMENT`, candidate_id: c.candidate_id, text: `Сумма ${fmt(c.requested_amount)} RUB, срок ${c.term_months} мес., ставка ${c.annual_rate_percent}% годовых; платеж ${fmt(c.monthly_payment)} RUB в месяц, расчетная переплата ${fmt(c.estimated_overpayment)} RUB.` })
    factors.push({ factor_id: `${c.candidate_id}_ROUTE`, candidate_id: c.candidate_id, text: `${routeText} ${c.reasons.map((r) => r.message).join(' ')}` })
    if (c.load_ratio) factors.push({ factor_id: `${c.candidate_id}_LOAD`, candidate_id: c.candidate_id, text: `Демонстрационная долговая нагрузка: ${(Number(c.load_ratio) * 100).toFixed(2)}%.` })
    if (c !== base) {
      const dp = Number(base.monthly_payment) - Number(c.monthly_payment)
      const dov = Number(c.estimated_overpayment) - Number(base.estimated_overpayment)
      factors.push({ factor_id: `${c.candidate_id}_TRADEOFF`, candidate_id: c.candidate_id, text: `По сравнению с исходным запросом ежемесячный платеж меньше на ${fmt(money2(dp))} RUB; изменение расчетной переплаты ${dov >= 0 ? '+' : ''}${fmt(money2(dov))} RUB. ${c.candidate_id === 'LOWER_AMOUNT' ? 'Доступная сумма меньше.' : 'Срок возврата длиннее.'}` })
    }
  }
  const t = (id: string) => factors.find((f) => f.factor_id === id)?.text ?? ''
  return {
    id: uid(),
    application_id: app.id,
    revision_id: null,
    draft_lock_version: app.version,
    mode,
    priority,
    preferred_candidate_ids: eligible.map((c) => c.candidate_id),
    status: 'FALLBACK',
    is_current: true,
    input_hash: hash([app.version]),
    factors,
    scenarios: mode === 'COMPARE' ? cands : cands.slice(0, 1),
    explanation: {
      summary: { factor_ids: ['DATA_ORIGIN', 'REQUESTED_ROUTE', 'REQUESTED_PAYMENT'], text: `${t('DATA_ORIGIN')} ${t('REQUESTED_ROUTE')} ${t('REQUESTED_PAYMENT')}` },
      comparisons:
        mode === 'COMPARE'
          ? cands.map((c) => ({ candidate_id: c.candidate_id, factor_ids: [`${c.candidate_id}_PAYMENT`], text: `${t(`${c.candidate_id}_PAYMENT`)} ${t(`${c.candidate_id}_TRADEOFF`) || t(`${c.candidate_id}_ROUTE`)}`.trim() }))
          : [],
      next_step: { id: 'REVIEW_SUBMISSION', text: 'Проверьте сведения и отдельно отправьте заявку. Разбор сам ее не отправляет.' },
      notice: 'Демонстрационный разбор. Сравнение предварительное и не гарантирует одобрение или выдачу. Числа и формулировки фактов рассчитаны backend.',
    },
    model_id: null,
    model_digest: null,
    prompt_version: 'advisor-priority-0.3.0',
    generation_config: {},
    latency_ms: 0,
    error_code: 'LLM_DISABLED',
    created_at: now(),
  }
}

/* ---------------- seed ---------------- */
function newApp(ownerId: string, companyId: string): AppRec {
  const c = companyById(companyId)!
  const id = uid()
  const ts = now()
  const app: AppRec = {
    id,
    owner_id: ownerId,
    company_id: companyId,
    product_id: DEMO_PRODUCT.id,
    status: 'DRAFT',
    version: 1,
    requested_amount: null,
    term_months: null,
    purpose_code: null,
    purpose_details: null,
    financial_months: clone(monthsOf(c)),
    purchase_from_bank_partner: false,
    fin_declared: false,
    confirmations: { data_confirmed: false, credit_history_check_allowed: false },
    info_response: null,
    ui_step: 'NEED',
    documents: [
      {
        id: uid(),
        application_id: id,
        kind: 'FINANCIAL_STATEMENT',
        original_filename: `${c.key}.csv`,
        mime_type: 'text/csv',
        content_sha256: hash(c.key).slice(0, 64),
        size_bytes: 377,
        source: 'DEMO',
        created_at: ts,
        download_url: '',
      },
    ],
    revisions: [],
    assessments: [],
    decision: null,
    info_requests: [],
    events: [],
    advisor: null,
    created_at: ts,
    updated_at: ts,
  }
  app.documents = [{ ...app.documents[0], download_url: `/api/documents/${app.documents[0].id}` }]
  addEvent(app, { event_type: 'DRAFT_CREATED', message: 'Создан черновик заявки', to_status: 'DRAFT', actor_user_id: ownerId })
  return app
}

/** Submitted applications from the team's reference scenarios (demo_data/demo_0_3/scenarios.json). */
const SEEDED = ['C01_REFERENCE', 'C02_REFERENCE', 'C03_BORDERLINE', 'C03_SCORE_LIMIT_OVERDUE', 'C04_INCOMPLETE_FINANCE', 'C05_SEVERE_OVERDUE', 'C06_BKI_RETRY', 'C07_NO_CREDIT_HISTORY', 'C08_NEGATIVE_CASHFLOW', 'LEGAL_BANKRUPTCY', 'LEGAL_UNKNOWN', 'C09_BUSINESS_TOO_YOUNG']

function seed(s: State) {
  for (const key of SEEDED) {
    const sc = DEMO_SCENARIOS.find((x) => x.key === key)
    const c = sc && DEMO_COMPANIES.find((x) => x.key === sc.company_key)
    if (!sc || !c?.members[0]) continue
    const owner = c.members[0]
    const app = newApp(owner, c.id)
    Object.assign(app, { requested_amount: sc.requested_amount, term_months: sc.term_months, purpose_code: sc.purpose_code, purchase_from_bank_partner: sc.purchase_from_bank_partner, ui_step: 'REVIEW', version: 3 })
    app.confirmations = { data_confirmed: true, credit_history_check_allowed: true }
    app.revisions.push(makeRevision(app, uid(), owner))
    setStatus(app, 'SUBMITTED', { event_type: 'SUBMITTED', message: 'Заявка отправлена на демонстрационную проверку', actor: owner })
    processLatest(app)
    s.apps.push(app)
  }
}

/* ---------------- router ---------------- */
type Handler = (m: RegExpMatchArray, body: any, q: URLSearchParams, user: DemoUser | null) => TransportResponse | Promise<TransportResponse>

const routes: [string, RegExp, Handler, { auth?: 'any' | 'CLIENT' | 'BANK_STAFF' }][] = []
const on = (method: string, re: RegExp, h: Handler, opts: { auth?: 'any' | 'CLIENT' | 'BANK_STAFF' } = { auth: 'any' }) => routes.push([method, re, h, opts])
const U = '([0-9a-f-]{36})'

on('GET', new RegExp(`^/api/applications/${U}/agreement$`), async (m, _b, _q, user) => {
  const app = ownApp(m[1], user!)
  if (!app) return notFound()
  const document = await mockAgreement(app)
  return document ? ok(document) : err(409, 'AGREEMENT_NOT_AVAILABLE', 'Документ доступен после одобрения заявки')
}, { auth: 'CLIENT' })
on('POST', new RegExp(`^/api/applications/${U}/agreement/sign$`), async (m, body, _q, user) => {
  const app = ownApp(m[1], user!)
  if (!app) return notFound()
  const document = await mockAgreement(app)
  if (!document) return err(409, 'AGREEMENT_NOT_AVAILABLE', 'Документ доступен после одобрения заявки')
  if (body.accepted !== true) return err(422, 'SIGNING_CONFIRMATION_REQUIRED', 'Нужно подтвердить подписание демо-документа')
  if (body.decision_id !== document.content.decision_id || body.content_sha256 !== document.content_sha256) return err(409, 'AGREEMENT_CHANGED', 'Получите актуальный документ')
  if (app.status === 'SIGNED') return ok(clientDraft(app))
  if (body.expected_version !== app.version) return err(409, 'VERSION_CONFLICT', 'Заявка изменилась; обновите страницу')
  app.agreement = { ...document, signature: { decision_id: body.decision_id, content_sha256: body.content_sha256, signed_at: now(), signed_by_display_name: user!.display_name, method: 'DEMO' } }
  setStatus(app, 'SIGNED', { event_type: 'AGREEMENT_SIGNED', message: 'Демо-документ подписан: электронная подпись имитирована, выдача средств не выполнялась.', actor: user!.id })
  save()
  return ok(clientDraft(app))
}, { auth: 'CLIENT' })

function session(user: DemoUser) {
  const t = Date.now()
  return {
    user: { id: user.id, email: user.email, display_name: user.display_name, role: user.role, ui_context: uiContext(user.id) },
    absolute_expires_at: new Date(t + 8 * 3600e3).toISOString(),
    idle_expires_at: new Date(t + 3600e3).toISOString(),
  }
}
function uiContext(userId: string) {
  const last = state.apps.filter((a) => a.owner_id === userId && !a.archived).sort((a, b) => b.updated_at.localeCompare(a.updated_at))[0]
  return last ? { section: 'applications', last_application_id: last.id, last_step: last.ui_step } : {}
}

function ownApp(id: string, user: { id: string }) {
  const app = state.apps.find((a) => a.id === id && !a.archived)
  if (!app) return null
  const company = companyById(app.company_id)
  return company?.members.includes(user.id) ? app : null
}
const notFound = () => err(404, 'APPLICATION_NOT_FOUND', 'Заявка не найдена')

on('GET', /^\/api\/auth\/csrf$/, () => {
  if (state.session) return ok({ csrf_token: state.session.csrf })
  state.loginCsrf = uid()
  save()
  return ok({ csrf_token: state.loginCsrf })
}, {})
on('POST', /^\/api\/auth\/login$/, (_m, body) => {
  const user = allUsers().find((u) => u.email === String(body?.email ?? '').trim().toLowerCase())
  if (!user || !body?.password) return err(401, 'INVALID_CREDENTIALS', 'Неверный email или пароль')
  state.session = { user_id: user.id, csrf: uid() }
  state.loginCsrf = null
  save()
  return ok(session(user))
}, {})
on('GET', /^\/api\/auth\/me$/, (_m, _b, _q, user) => ok(session(user!)))
on('POST', /^\/api\/auth\/activity$/, (_m, _b, _q, user) => ok(session(user!)))
on('POST', /^\/api\/auth\/logout$/, () => {
  state.session = null
  save()
  return { status: 204, body: null }
})

on('GET', /^\/api\/companies$/, (_m, _b, _q, user) => {
  const items = allCompanies().filter((c) => c.members.includes(user!.id)).map(companyPublic)
  return ok({ items, total: items.length, limit: 100, offset: 0 })
}, { auth: 'CLIENT' })
on('GET', new RegExp(`^/api/companies/${U}$`), (m, _b, _q, user) => {
  const c = companyById(m[1])
  if (!c || !c.members.includes(user!.id)) return err(404, 'COMPANY_NOT_FOUND', 'Компания не найдена')
  return ok({ ...companyPublic(c), financial_months: monthsOf(c), provenance: { company: { source: 'DEMO_PROFILE', as_of_date: CALCULATION_DATE, checked_at: null }, financial_months: { source: 'DEMO_PROFILE', as_of_date: '2026-09-30', checked_at: null }, credit_history: null } })
}, { auth: 'CLIENT' })
on('GET', /^\/api\/products$/, () => ok({ items: [DEMO_PRODUCT], total: 1, limit: 100, offset: 0 }), { auth: 'CLIENT' })

on('GET', /^\/api\/applications$/, (_m, _b, q, user) => {
  const comp = q.get('company_id')
  const items = state.apps
    .filter((a) => !a.archived && companyById(a.company_id)?.members.includes(user!.id) && (!comp || a.company_id === comp))
    .sort((a, b) => b.created_at.localeCompare(a.created_at))
    .map(clientDraft)
  return ok({ items, total: items.length, limit: 100, offset: 0 })
}, { auth: 'CLIENT' })
on('POST', /^\/api\/applications$/, (_m, body, _q, user) => {
  const c = companyById(body?.company_id)
  if (!c || !c.members.includes(user!.id)) return err(404, 'COMPANY_NOT_FOUND', 'Компания не найдена')
  const app = newApp(user!.id, c.id)
  state.apps.push(app)
  return ok(clientDraft(app), 201)
}, { auth: 'CLIENT' })
on('GET', new RegExp(`^/api/applications/${U}$`), (m, _b, _q, user) => {
  const app = ownApp(m[1], user!)
  return app ? ok(clientDraft(app)) : notFound()
}, { auth: 'CLIENT' })
on('PATCH', new RegExp(`^/api/applications/${U}$`), (m, body, _q, user) => {
  const app = ownApp(m[1], user!)
  if (!app) return notFound()
  if (app.status !== 'DRAFT' && app.status !== 'NEEDS_INFO') return err(409, 'APPLICATION_NOT_EDITABLE', 'Заявку в этом статусе нельзя изменить')
  if (body.expected_version !== app.version) return err(409, 'VERSION_CONFLICT', 'Черновик уже изменён. Получите актуальную версию')
  const fe: { field: string; message: string }[] = []
  const moneyRe = /^(0|[1-9][0-9]{0,15})\.[0-9]{2}$/
  if ('requested_amount' in body && body.requested_amount !== null && !moneyRe.test(body.requested_amount)) fe.push({ field: 'requested_amount', message: 'Некорректное значение' })
  if ('term_months' in body && body.term_months !== null && (!Number.isInteger(body.term_months) || body.term_months < 1)) fe.push({ field: 'term_months', message: 'Некорректное значение' })
  for (const fm of body.draft_data?.financial_months ?? [])
    for (const k of ['cash_inflow', 'operating_outflow', 'existing_debt_payment'])
      if (fm[k] !== null && fm[k] !== undefined && !moneyRe.test(fm[k])) fe.push({ field: `draft_data.financial_months.${fm.month}.${k}`, message: 'Некорректное значение' })
  if (fe.length) return err(422, 'VALIDATION_ERROR', 'Проверьте поля запроса', fe)
  const dd = body.draft_data
  const purpose = 'purpose_code' in body ? body.purpose_code : app.purpose_code
  const partner = dd && 'purchase_from_bank_partner' in dd ? dd.purchase_from_bank_partner === true : app.purchase_from_bank_partner
  if (partner && !PURCHASE_PURPOSES.includes(purpose))
    return err(422, 'VALIDATION_ERROR', 'Партнёрская программа доступна только для закупочных целей', [{ field: 'draft_data.purchase_from_bank_partner', message: 'Снимите признак партнёрской покупки' }])
  if (app.scenario_set && (['requested_amount', 'term_months'] as const).some((k) => k in body && body[k] !== app[k])) app.scenario_set.manually_changed = true
  for (const k of ['requested_amount', 'term_months', 'purpose_code', 'purpose_details', 'ui_step'] as const) if (k in body) (app as any)[k] = body[k]
  if (dd?.financial_months) {
    // Same as the backend: the list replaces the stored months as a whole, sorted by month.
    app.financial_months = (dd.financial_months as FinancialMonth[])
      .map((n) => ({ month: n.month, cash_inflow: n.cash_inflow ?? null, operating_outflow: n.operating_outflow ?? null, existing_debt_payment: n.existing_debt_payment ?? null }))
      .sort((x, y) => x.month.localeCompare(y.month))
    app.fin_declared = true
  }
  app.purchase_from_bank_partner = partner
  if (dd?.confirmations) app.confirmations = { ...app.confirmations, ...dd.confirmations }
  if (dd && 'info_response' in dd) app.info_response = dd.info_response
  app.version++
  app.updated_at = now()
  return ok(clientDraft(app))
}, { auth: 'CLIENT' })
on('DELETE', new RegExp(`^/api/applications/${U}$`), (m, body, _q, user) => {
  const app = ownApp(m[1], user!)
  if (!app) return notFound()
  if (app.status !== 'DRAFT' || app.revisions.length) return err(409, 'APPLICATION_NOT_DELETABLE', 'Отправленную заявку удалить нельзя: она хранится в истории рассмотрения')
  if (body.expected_version !== app.version) return err(409, 'VERSION_CONFLICT', 'Черновик уже изменён. Получите актуальную версию')
  app.archived = true
  return { status: 204, body: null }
}, { auth: 'CLIENT' })
on('GET', new RegExp(`^/api/applications/${U}/events$`), (m, _b, _q, user) => {
  const app = ownApp(m[1], user!)
  if (!app) return notFound()
  return ok({ items: app.events.filter((e) => e.visibility === 'CLIENT').map(({ revision_id: _r, actor_user_id: _a, visibility: _v, details: _d, ...e }) => e) })
}, { auth: 'CLIENT' })
on('POST', new RegExp(`^/api/applications/${U}/submit$`), (m, body, _q, user) => {
  const app = ownApp(m[1], user!)
  if (!app) return notFound()
  const prev = app.revisions.find((r) => r.submission_key === body.submission_key)
  if (prev) return ok({ application: clientDraft(app), revision: prev, assessment: clientAssessment(latestAssessment(app)) })
  if (app.status !== 'DRAFT' && app.status !== 'NEEDS_INFO') return err(409, 'APPLICATION_NOT_EDITABLE', 'Заявка уже отправлена')
  if (body.expected_version !== app.version) return err(409, 'VERSION_CONFLICT', 'Черновик уже изменён. Получите актуальную версию')
  const fe: { field: string; message: string }[] = []
  const p = DEMO_PRODUCT
  const amt = Number(app.requested_amount)
  if (!app.purpose_code) fe.push({ field: 'purpose_code', message: 'Выберите цель финансирования' })
  if (!app.requested_amount) fe.push({ field: 'requested_amount', message: 'Укажите сумму' })
  else if (amt < Number(p.min_amount) || amt > Number(p.max_amount)) fe.push({ field: 'requested_amount', message: `Сумма от ${Number(p.min_amount).toLocaleString('ru-RU')} до ${Number(p.max_amount).toLocaleString('ru-RU')} ₽` })
  if (!app.term_months) fe.push({ field: 'term_months', message: 'Укажите срок' })
  else if (app.term_months < p.min_term_months || app.term_months > p.max_term_months) fe.push({ field: 'term_months', message: `Срок от ${p.min_term_months} до ${p.max_term_months} месяцев` })
  if (!app.confirmations.data_confirmed) fe.push({ field: 'draft_data.confirmations.data_confirmed', message: 'Подтвердите корректность данных' })
  if (!app.confirmations.credit_history_check_allowed) fe.push({ field: 'draft_data.confirmations.credit_history_check_allowed', message: 'Подтвердите демонстрационную проверку кредитной истории' })
  if (fe.length) return err(422, 'VALIDATION_ERROR', 'Проверьте поля заявки', fe)
  const wasNeedsInfo = app.status === 'NEEDS_INFO'
  const rev = makeRevision(app, body.submission_key, user!.id)
  app.revisions.push(rev)
  for (const r of app.info_requests) if (r.status === 'OPEN') Object.assign(r, { status: 'ANSWERED', answer_text: app.info_response, answered_revision_id: rev.id, answered_at: now() })
  setStatus(app, 'SUBMITTED', { event_type: wasNeedsInfo ? 'RESUBMITTED' : 'SUBMITTED', message: wasNeedsInfo ? 'Заявка дополнена и отправлена повторно' : 'Заявка отправлена на демонстрационную проверку', actor: user!.id })
  processLatest(app)
  save()
  return ok({ application: clientDraft(app), revision: rev, assessment: clientAssessment(latestAssessment(app)) })
}, { auth: 'CLIENT' })
on('GET', new RegExp(`^/api/applications/${U}/revisions/(\\d+)$`), (m, _b, _q, user) => {
  const app = ownApp(m[1], user!)
  const rev = app?.revisions.find((r) => r.revision_no === Number(m[2]))
  return rev ? ok(rev) : err(404, 'REVISION_NOT_FOUND', 'Версия не найдена')
}, { auth: 'CLIENT' })
on('GET', new RegExp(`^/api/applications/${U}/decision$`), (m, _b, _q, user) => {
  const app = ownApp(m[1], user!)
  if (!app) return notFound()
  return app.decision ? ok(clientDraft(app).decision) : err(404, 'DECISION_NOT_FOUND', 'Решения пока нет')
}, { auth: 'CLIENT' })
on('POST', new RegExp(`^/api/applications/${U}/scenarios$`), (m, body, _q, user) => {
  const app = ownApp(m[1], user!)
  if (!app) return notFound()
  if (body.expected_version !== app.version) return err(409, 'VERSION_CONFLICT', 'Черновик уже изменён. Получите актуальную версию')
  const preview = app.confirmations.credit_history_check_allowed
  const c = scenarioCandidates(app, preview)
  if (!Array.isArray(c)) return c
  return ok({ mode: preview ? 'PREVIEW' : 'CALCULATION_ONLY', application_version: app.version, candidates: c })
}, { auth: 'CLIENT' })
on('POST', new RegExp(`^/api/applications/${U}/advisor$`), (m, body, _q, user) => {
  const app = ownApp(m[1], user!)
  if (!app) return notFound()
  if (body.expected_version !== app.version) return err(409, 'VERSION_CONFLICT', 'Черновик уже изменён. Получите актуальную версию')
  if (!app.confirmations.credit_history_check_allowed)
    return err(422, 'CREDIT_HISTORY_CONFIRMATION_REQUIRED', 'Для разбора подтвердите демонстрационную проверку кредитной истории', [{ field: 'draft_data.confirmations.credit_history_check_allowed', message: 'Требуется подтверждение' }])
  const fixed = optionView(app)
  const compareFixed = body.mode === 'COMPARE' && fixed && (app.status === 'DRAFT' || app.status === 'NEEDS_INFO')
  if (compareFixed && !fixed.is_current) return err(409, 'SCENARIO_SET_STALE', 'Обновите варианты перед сравнением')
  const c = compareFixed ? fixed.candidates : scenarioCandidates(app, true)
  if (!Array.isArray(c)) return c
  if (!['BALANCED', 'KEEP_AMOUNT', 'LOWER_PAYMENT', 'LOWER_OVERPAYMENT'].includes(body.priority ?? 'BALANCED')) return err(422, 'VALIDATION_ERROR', 'Неизвестный приоритет')
  app.advisor = advisorReport(app, body.mode ?? 'EXPLAIN', c, body.priority ?? 'BALANCED')
  save()
  return ok(app.advisor)
}, { auth: 'CLIENT' })
on('GET', new RegExp(`^/api/applications/${U}/scenario-set$`), (m, _body, _q, user) => {
  const app = ownApp(m[1], user!)
  return app ? ok(optionView(app)) : notFound()
}, { auth: 'CLIENT' })
on('POST', new RegExp(`^/api/applications/${U}/scenario-set$`), (m, body, _q, user) => {
  const app = ownApp(m[1], user!)
  if (!app) return notFound()
  if (!['DRAFT', 'NEEDS_INFO'].includes(app.status)) return err(409, 'APPLICATION_NOT_EDITABLE', 'Условия отправленной заявки менять нельзя')
  if (body.expected_version !== app.version) return err(409, 'VERSION_CONFLICT', 'Заявка уже изменена')
  if (app.scenario_set && !body.refresh) return ok({ application: clientDraft(app), scenario_set: optionView(app) })
  const preview = app.confirmations.credit_history_check_allowed
  const candidates = scenarioCandidates(app, preview)
  if (!Array.isArray(candidates)) return candidates
  app.version++
  app.updated_at = now()
  app.scenario_set = { context: optionContext(app), manually_changed: false, value: {
    id: uid(), created_at: now(), mode: preview ? 'PREVIEW' : 'CALCULATION_ONLY',
    application_version: app.version, candidates, selected_candidate_id: 'REQUESTED', is_current: true, stale_reason: null,
  } }
  return ok({ application: clientDraft(app), scenario_set: optionView(app) })
}, { auth: 'CLIENT' })
on('POST', new RegExp(`^/api/applications/${U}/scenario-set/select$`), (m, body, _q, user) => {
  const app = ownApp(m[1], user!)
  if (!app) return notFound()
  if (!['DRAFT', 'NEEDS_INFO'].includes(app.status)) return err(409, 'APPLICATION_NOT_EDITABLE', 'Условия отправленной заявки менять нельзя')
  if (body.expected_version !== app.version) return err(409, 'VERSION_CONFLICT', 'Заявка уже изменена')
  if (!app.scenario_set || app.scenario_set.value.id !== body.scenario_set_id) return err(409, 'SCENARIO_SET_CONFLICT', 'Набор вариантов изменился')
  if (!optionView(app)?.is_current) return err(409, 'SCENARIO_SET_STALE', 'Обновите варианты')
  const candidate = app.scenario_set.value.candidates.find((c) => c.candidate_id === body.candidate_id)
  if (!candidate) return err(422, 'SCENARIO_NOT_FOUND', 'В этом наборе нет выбранного варианта')
  if (body.candidate_id !== app.scenario_set.value.selected_candidate_id) {
    app.requested_amount = candidate.requested_amount
    app.term_months = candidate.term_months
    app.scenario_set.value.selected_candidate_id = candidate.candidate_id
    app.version++
    app.updated_at = now()
  }
  return ok({ application: clientDraft(app), scenario_set: optionView(app) })
}, { auth: 'CLIENT' })
on('GET', new RegExp(`^/api/applications/${U}/advisor$`), (m, _b, _q, user) => {
  const app = ownApp(m[1], user!)
  if (!app?.advisor) return err(404, 'ADVISOR_REPORT_NOT_FOUND', 'Разбора пока нет')
  return ok({ ...app.advisor, is_current: app.advisor.draft_lock_version === app.version })
}, { auth: 'CLIENT' })

on('GET', new RegExp(`^/api/documents/${U}$`), (m, _b, _q, user) => {
  for (const app of state.apps) {
    const d = app.documents.find((x) => x.id === m[1])
    if (!d) continue
    const can = user!.role === 'BANK_STAFF' ? app.revisions.length > 0 : companyById(app.company_id)?.members.includes(user!.id)
    if (!can) break
    const c = companyById(app.company_id)!
    const lines = ['company_key,month,cash_inflow,operating_outflow,existing_debt_payment,source', ...monthsOf(c).map((x) => `${c.key},${x.month},${x.cash_inflow},${x.operating_outflow},${x.existing_debt_payment},DEMO`)]
    return { status: 200, body: lines.join('\n') + '\n' }
  }
  return err(404, 'DOCUMENT_NOT_FOUND', 'Документ не найден')
})

/* bank */
const ACTIVE: ApplicationStatus[] = ['SUBMITTED', 'CHECKING', 'NEEDS_INFO', 'MANUAL_REVIEW']
on('GET', /^\/api\/bank\/applications$/, (_m, _b, q) => {
  const statuses = q.getAll('status') as ApplicationStatus[]
  const want = statuses.length ? statuses : ACTIVE
  const comp = q.get('company_id')
  const all = state.apps
    .filter((a) => a.revisions.length && want.includes(a.status) && (!comp || a.company_id === comp))
    .map(queueItem)
    .sort((a, b) => a.submitted_at.localeCompare(b.submitted_at))
  const limit = Number(q.get('limit') ?? 20)
  const offset = Number(q.get('offset') ?? 0)
  return ok({ items: all.slice(offset, offset + limit), total: all.length, limit, offset })
}, { auth: 'BANK_STAFF' })
const bankApp = (id: string) => state.apps.find((a) => a.id === id && a.revisions.length)
on('GET', new RegExp(`^/api/bank/applications/${U}$`), (m) => {
  const app = bankApp(m[1])
  return app ? ok(bankCard(app)) : notFound()
}, { auth: 'BANK_STAFF' })
on('GET', new RegExp(`^/api/bank/applications/${U}/events$`), (m) => {
  const app = bankApp(m[1])
  return app ? ok({ items: app.events }) : notFound()
}, { auth: 'BANK_STAFF' })
on('GET', new RegExp(`^/api/bank/applications/${U}/revisions/(\\d+)$`), (m) => {
  const app = bankApp(m[1])
  const rev = app?.revisions.find((r) => r.revision_no === Number(m[2]))
  if (!app || !rev) return err(404, 'REVISION_NOT_FOUND', 'Версия не найдена')
  return ok({ revision: rev, assessments: app.assessments.filter((a) => a.revision_id === rev.id) })
}, { auth: 'BANK_STAFF' })
on('GET', new RegExp(`^/api/bank/applications/${U}/advisor$`), () => err(404, 'ADVISOR_REPORT_NOT_FOUND', 'Для отправленной версии разбора нет'), { auth: 'BANK_STAFF' })
on('POST', new RegExp(`^/api/bank/applications/${U}/request-info$`), (m, body, _q, user) => {
  const app = bankApp(m[1])
  if (!app) return notFound()
  if (body.expected_version !== app.version) return err(409, 'VERSION_CONFLICT', 'Заявка уже изменилась. Обновите карточку')
  if (!bankActions(app).includes('REQUEST_INFO')) return err(409, 'ACTION_NOT_ALLOWED', 'Действие недоступно в текущем состоянии')
  const msg = String(body.message_to_client ?? '')
  const fe = []
  if (msg.length < 20 || msg.length > 1000) fe.push({ field: 'message_to_client', message: 'От 20 до 1000 символов' })
  if (!body.requested_fields?.length) fe.push({ field: 'requested_fields', message: 'Выберите хотя бы одно поле' })
  if (fe.length) return err(422, 'VALIDATION_ERROR', 'Проверьте поля запроса', fe)
  app.info_requests.push({ id: uid(), revision_id: app.revisions.at(-1)!.id, created_by_user_id: user!.id, requested_fields: body.requested_fields, message_to_client: msg, status: 'OPEN', answer_text: null, answered_revision_id: null, answered_at: null, created_at: now() })
  setStatus(app, 'NEEDS_INFO', { event_type: 'INFO_REQUESTED', message: 'Сотрудник запросил уточнение сведений', actor: user!.id })
  save()
  return ok(bankCard(app))
}, { auth: 'BANK_STAFF' })
function offerPreview(app: AppRec, body: { amount: string; term_months: number }): OfferPreview | TransportResponse {
  const rev = app.revisions.at(-1)!
  const a = latestAssessment(app)!
  const product = rev.product_snapshot
  const amount = Number(body.amount), term = body.term_months
  if (!Number.isFinite(amount) || amount < Number(product.min_amount) || amount > Number(rev.requested_amount)) return err(422, 'OFFER_AMOUNT_INVALID', 'Проверьте сумму предложения')
  if (!Number.isInteger(term) || term < Number(product.min_term_months) || term > Number(product.max_term_months)) return err(422, 'OFFER_TERM_INVALID', 'Проверьте срок предложения')
  if (amount === Number(rev.requested_amount) && term === rev.term_months) return err(422, 'OFFER_UNCHANGED', 'Используйте обычное одобрение')
  const fin = rev.financial_snapshot as { financial_months: FinancialMonth[]; purchase_from_bank_partner?: boolean }
  const company = { ...companyById(app.company_id)!, ...rev.company_snapshot } as DemoCompany
  const res = evaluate({ company, months: fin.financial_months, amount, term, purpose: rev.purpose_code, partner: !!fin.purchase_from_bank_partner, revisionNo: rev.revision_no, runNo: a.run_no, saved: a.checks })
  const pricing = res.details.pricing as { annual_rate_percent: string }
  const terms: OfferPreview['terms'] = {
    original_amount: rev.requested_amount, original_term_months: rev.term_months,
    original_annual_rate_percent: String(a.calculation_details.annual_rate_percent ?? product.annual_rate_percent),
    original_monthly_payment: String(a.calculation_details.monthly_payment),
    amount: money2(amount), term_months: term, annual_rate_percent: pricing.annual_rate_percent,
    ...annuity(amount, term, Number(pricing.annual_rate_percent)),
    load_ratio: res.details.load_ratio as string | null ?? null, pricing,
  }
  const result = { application_version: app.version, terms, risk_score: res.risk_score, risk_band: bandOf(res.risk_score), routing: res.routing,
    reasons: res.reason_codes.map(reason), can_approve: res.routing === 'APPROVE' || (res.routing === 'MANUAL_REVIEW' && res.reason_codes[0] === 'BORDERLINE_RISK'), preview_hash: '' }
  result.preview_hash = hash(result)
  return result
}

on('POST', new RegExp(`^/api/bank/applications/${U}/offer-preview$`), (m, body) => {
  const app = bankApp(m[1])
  if (!app) return notFound()
  if (body.expected_version !== app.version) return err(409, 'VERSION_CONFLICT', 'Заявка уже изменилась')
  if (!bankActions(app).includes('APPROVE')) return err(409, 'BANK_ACTION_NOT_ALLOWED', 'Действие недоступно')
  const result = offerPreview(app, body)
  return 'terms' in result ? ok(result) : result
}, { auth: 'BANK_STAFF' })
on('POST', new RegExp(`^/api/bank/applications/${U}/decision$`), (m, body, _q, user) => {
  const app = bankApp(m[1])
  if (!app) return notFound()
  if (body.expected_version !== app.version) return err(409, 'VERSION_CONFLICT', 'Заявка уже изменилась. Обновите карточку')
  const outcome = body.outcome as 'APPROVED' | 'REJECTED'
  if (!bankActions(app).includes(outcome === 'APPROVED' ? 'APPROVE' : 'REJECT')) return err(409, 'ACTION_NOT_ALLOWED', 'Действие недоступно в текущем состоянии')
  const pe = String(body.public_explanation ?? '')
  if (pe.length < 20 || pe.length > 1000) return err(422, 'VALIDATION_ERROR', 'Проверьте поля запроса', [{ field: 'public_explanation', message: 'От 20 до 1000 символов' }])
  const rev = app.revisions.at(-1)!
  const a = latestAssessment(app)!
  let preview: OfferPreview | null = null
  if (body.offer) {
    if (outcome !== 'APPROVED') return err(422, 'VALIDATION_ERROR', 'Предложение допустимо только при одобрении')
    const calculated = offerPreview(app, body.offer)
    if (!('terms' in calculated)) return calculated
    preview = calculated
    if (preview.preview_hash !== body.offer.preview_hash) return err(409, 'OFFER_PREVIEW_CHANGED', 'Пересчитайте предложение')
    if (!preview.can_approve) return err(422, 'OFFER_NOT_APPROVABLE', 'Новые условия не проходят обязательные ограничения')
  }
  app.decision = {
    id: uid(),
    revision_id: rev.id,
    assessment_id: a.id,
    outcome,
    source: 'MANUAL',
    approved_amount: outcome === 'APPROVED' ? preview?.terms.amount ?? rev.requested_amount : null,
    approved_term_months: outcome === 'APPROVED' ? preview?.terms.term_months ?? rev.term_months : null,
    annual_rate_percent: outcome === 'APPROVED' ? preview?.terms.annual_rate_percent ?? String(a.calculation_details.annual_rate_percent ?? DEMO_PRODUCT.annual_rate_percent) : null,
    monthly_payment: outcome === 'APPROVED' ? preview?.terms.monthly_payment ?? String(a.calculation_details.monthly_payment) : null,
    offer: preview?.terms ?? null, offer_risk_score: preview?.risk_score ?? null, offer_risk_band: preview?.risk_band ?? null,
    reasons: preview?.reasons ?? a.reasons,
    public_explanation: pe,
    policy_version: DEMO_PRODUCT.policy_version,
    created_at: now(),
    decided_by_user_id: user!.id,
    internal_comment: body.internal_comment || null,
  }
  setStatus(app, outcome, { event_type: 'MANUAL_DECISION', message: outcome === 'APPROVED' ? 'Сотрудник одобрил заявку' : 'Сотрудник отказал по заявке', actor: user!.id })
  save()
  return ok(bankCard(app))
}, { auth: 'BANK_STAFF' })
on('POST', new RegExp(`^/api/bank/applications/${U}/retry-processing$`), (m, body, _q, user) => {
  const app = bankApp(m[1])
  if (!app) return notFound()
  if (body.expected_version !== app.version) return err(409, 'VERSION_CONFLICT', 'Заявка уже изменилась. Обновите карточку')
  if (!bankActions(app).includes('RETRY_PROCESSING')) return err(409, 'ACTION_NOT_ALLOWED', 'Повтор обработки недоступен')
  processLatest(app, user!.id)
  save()
  return ok({ application_id: app.id, version: app.version, status: app.status, revision_id: app.revisions.at(-1)!.id, assessment: clientAssessment(latestAssessment(app)), allowed_actions: [] })
}, { auth: 'BANK_STAFF' })

state = load()

export async function mockTransport(method: string, path: string, body: unknown, headers: Record<string, string>): Promise<TransportResponse> {
  await new Promise((r) => setTimeout(r, 120 + Math.random() * 180))
  const [pathname, search = ''] = path.split('?')
  const q = new URLSearchParams(search)
  const user = state.session ? userById(state.session.user_id) ?? null : null
  for (const [m, re, h, opts] of routes) {
    if (m !== method) continue
    const match = pathname.match(re)
    if (!match) continue
    if (opts.auth) {
      if (!user) return err(401, 'AUTH_REQUIRED', 'Требуется вход')
      if (opts.auth !== 'any' && user.role !== opts.auth) return err(403, 'ROLE_FORBIDDEN', 'Недоступно для вашей роли')
    }
    if (method !== 'GET') {
      const expected = state.session?.csrf ?? state.loginCsrf
      if (!expected || headers['X-CSRF-Token'] !== expected) return err(403, 'CSRF_INVALID', 'CSRF-токен устарел')
    }
    const res = await h(match, body ?? {}, q, user)
    if (method !== 'GET') save()
    return res
  }
  return err(404, 'NOT_FOUND', `Неизвестный маршрут ${method} ${pathname}`)
}
