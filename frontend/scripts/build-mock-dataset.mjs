// Builds src/api/mock/dataset.json for the in-browser demo API from the team's synthetic dataset.
// Usage: npm run gen:mock   (reads ../demo_data/demo_0_3 and ../src/credit_cabinet/services/reasons.py)
import { createHash } from 'node:crypto'
import { readFileSync, writeFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const here = dirname(fileURLToPath(import.meta.url))
const root = resolve(here, '..', '..')
const dataset = resolve(root, 'demo_data', 'demo_0_3')
const out = resolve(here, '..', 'src', 'api', 'mock', 'dataset.json')

const json = (name) => JSON.parse(readFileSync(resolve(dataset, name), 'utf8'))

function csv(name) {
  const [head, ...lines] = readFileSync(resolve(dataset, name), 'utf8').trim().split(/\r?\n/)
  const cols = head.split(',')
  return lines.map((line) => {
    const cells = []
    let cur = ''
    let quoted = false
    for (const ch of line) {
      if (ch === '"') quoted = !quoted
      else if (ch === ',' && !quoted) {
        cells.push(cur)
        cur = ''
      } else cur += ch
    }
    cells.push(cur)
    return Object.fromEntries(cols.map((c, i) => [c, cells[i] ?? '']))
  })
}

// Stable UUID-shaped ids, so links survive a rebuild of the demo data.
const uuid = (seed) => {
  const h = createHash('sha1').update(seed).digest('hex')
  return `${h.slice(0, 8)}-${h.slice(8, 12)}-5${h.slice(13, 16)}-a${h.slice(17, 20)}-${h.slice(20, 32)}`
}

const products = json('credit_products.json')
const product = products.find((p) => p.version === 3) ?? products[0]
const relationships = Object.fromEntries(json('bank_relationships.json').map((r) => [r.company_key, r.has_active_loan_in_our_bank]))
const memberships = csv('memberships.csv')
const users = json('demo_users.json').map((u) => ({ key: u.user_key, id: uuid(`user:${u.user_key}`), email: u.email, display_name: u.display_name, role: u.role }))
const userId = Object.fromEntries(users.map((u) => [u.key, u.id]))

const companies = csv('companies.csv').map((c) => ({
  key: c.company_key,
  id: uuid(`company:${c.company_key}`),
  legal_name: c.legal_name,
  legal_form: c.legal_form,
  inn: c.inn,
  registration_number: c.registration_number || null,
  registered_on: c.registered_on,
  okved_code: c.okved_code,
  region_code: c.region_code,
  business_description: c.business_description || null,
  has_active_loan_in_our_bank: relationships[c.company_key] === true,
  members: memberships.filter((m) => m.company_key === c.company_key).map((m) => userId[m.user_key]).filter(Boolean),
}))

const months = {}
for (const r of csv('financial_months.csv')) {
  const v = (x) => (x === '' ? null : x)
  ;(months[r.company_key] ??= []).push({ month: r.month, cash_inflow: v(r.cash_inflow), operating_outflow: v(r.operating_outflow), existing_debt_payment: v(r.existing_debt_payment) })
}
for (const k of Object.keys(months)) months[k].sort((a, b) => a.month.localeCompare(b.month))

const pick = ({ company_key, status, error_code, normalized_data, run_no, revision_no }) => ({ company_key, status, error_code, normalized_data, run_no: run_no ?? 1, revision_no: revision_no ?? null })
const fns = json('fns_responses.json').map(pick)
const bki = json('bki_responses.json').map(pick)

// Public reason texts: the same table the backend uses (services/reasons.py).
const reasonsPy = readFileSync(resolve(root, 'src', 'credit_cabinet', 'services', 'reasons.py'), 'utf8')
const reasons = Object.fromEntries([...reasonsPy.matchAll(/^\s+"([A-Z0-9_]+)":\s*"([^"]+)",?$/gm)].map((m) => [m[1], m[2]]))

const scenarios = json('scenarios.json').map((s) => ({
  key: s.scenario_key,
  company_key: s.company_key,
  requested_amount: s.requested_amount,
  term_months: s.term_months,
  purpose_code: s.purpose_code,
  purchase_from_bank_partner: s.purchase_from_bank_partner ?? false,
  sequence: s.sequence,
  expected: {
    status: s.expected_result.status,
    risk_score: s.expected_result.risk_score ?? null,
    reason_codes: s.expected_result.reason_codes ?? null,
    annual_rate_percent: s.expected_result.annual_rate_percent ?? null,
    monthly_payment: s.expected_result.monthly_payment ?? null,
  },
}))

const { policy_config, is_active, ...publicProduct } = product
writeFileSync(
  out,
  JSON.stringify({
    source: 'demo_data/demo_0_3',
    product: { id: uuid(`product:${product.code}:${product.version}`), currency: 'RUB', ...publicProduct },
    calculation_date: policy_config.calculation_date,
    financial_months: policy_config.financial_months,
    users,
    companies,
    months,
    fns,
    bki,
    reasons,
    scenarios,
  }),
)
console.log(`mock dataset: ${companies.length} companies, ${users.length} users, ${scenarios.length} scenarios -> ${out}`)
