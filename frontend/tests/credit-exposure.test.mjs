import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'
import ts from 'typescript'

// Exercise the shipped browser mock through the public API contract.
const transpile = (source) => ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022 } }).outputText
const moduleUrl = (source) => `data:text/javascript;base64,${Buffer.from(source).toString('base64')}`
const data = moduleUrl(transpile(await readFile(new URL('../src/api/mock/data.ts', import.meta.url), 'utf8'))
  .replace("import dataset from './dataset.json';", `import dataset from '${new URL('../src/api/mock/dataset.json', import.meta.url).href}' with { type: 'json' };`))
const source = transpile(await readFile(new URL('../src/api/mock/server.ts', import.meta.url), 'utf8')).replace("from './data'", `from '${data}'`)
const storage = new Map()
globalThis.localStorage = { getItem: (key) => storage.get(key) ?? null, setItem: (key, value) => storage.set(key, value), removeItem: (key) => storage.delete(key) }
const { mockTransport, resetDemo } = await import(moduleUrl(source))

async function api(method, path, body) {
  const headers = {}
  if (method !== 'GET') headers['X-CSRF-Token'] = (await mockTransport('GET', '/api/auth/csrf', null, {})).body.csrf_token
  return mockTransport(method, path, body, headers)
}

test('browser mock reserves approvals, counts signatures and releases refused offers', async () => {
  resetDemo()
  assert.equal((await api('POST', '/api/auth/login', { email: 'client@example.com', password: 'demo' })).status, 200)
  const first = (await api('GET', '/api/applications')).body.items.find(a => a.status === 'APPROVED')
  const summary = async () => (await api('GET', `/api/companies/${first.company_id}`)).body.credit_exposure
  assert.equal((await summary()).reserved_count, 1)
  const document = (await api('GET', `/api/applications/${first.id}/agreement`)).body
  const signed = await api('POST', `/api/applications/${first.id}/agreement/sign`, {
    expected_version: first.version, decision_id: first.decision.id, content_sha256: document.content_sha256, accepted: true,
  })
  assert.equal(signed.status, 200)
  assert.equal(signed.body.status, 'SIGNED')
  assert.equal((await summary()).signed_count, 1)
  assert.equal((await summary()).reserved_count, 0)
  assert.equal(Number((await summary()).current_payment), Number((await summary()).reported_payment) + Number(first.decision.monthly_payment))

  async function submit() {
    const draft = (await api('POST', '/api/applications', { company_id: first.company_id, product_id: first.product_id })).body
    const saved = (await api('PATCH', `/api/applications/${draft.id}`, {
      expected_version: draft.version, requested_amount: '1000000.00', term_months: 12, purpose_code: 'INVENTORY',
      draft_data: { confirmations: { data_confirmed: true, credit_history_check_allowed: true } },
    })).body
    const result = await api('POST', `/api/applications/${draft.id}/submit`, { expected_version: saved.version, submission_key: crypto.randomUUID() })
    assert.equal(result.status, 200)
    return result.body.application
  }
  const second = await submit()
  assert.equal(second.status, 'APPROVED')
  assert.equal((await submit()).status, 'REJECTED')
  assert.equal((await summary()).reserved_count, 1)
  assert.equal((await api('POST', `/api/applications/${second.id}/agreement/decline`, { expected_version: second.version, decision_id: second.decision.id })).status, 200)
  assert.equal((await summary()).reserved_count, 0)
})
