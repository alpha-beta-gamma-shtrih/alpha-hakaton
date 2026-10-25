import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'
import ts from 'typescript'

// Exercise the production policy with Node's test runner, without a DOM or new dependencies.
const source = await readFile(new URL('../src/pages/client/wizard/needConfirmation.ts', import.meta.url), 'utf8')
const { outputText } = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022 } })
const { needTermsKey, submittedNeedKey, needConfirmation } = await import(`data:text/javascript;base64,${Buffer.from(outputText).toString('base64')}`)

const terms = { requested_amount: '1000000.00', term_months: 12, purpose_code: 'INVENTORY', purchase_from_bank_partner: false }
const baseline = needTermsKey(terms)

test('a bank request inherits unchanged terms without any browser confirmation', () => {
  assert.deepEqual(needConfirmation(true, baseline, baseline, false, null), { confirmed: true, inherited: true })
})

for (const [name, change] of Object.entries({ amount: { requested_amount: '900000.00' }, term: { term_months: 24 }, purpose: { purpose_code: 'EQUIPMENT' }, partner: { purchase_from_bank_partner: true } })) {
  test(`changing ${name} requires confirmation even with a stale browser flag`, () => {
    const changed = needTermsKey({ ...terms, ...change })
    assert.deepEqual(needConfirmation(true, changed, baseline, true, baseline), { confirmed: false, inherited: false })
    assert.deepEqual(needConfirmation(true, changed, baseline, true, changed), { confirmed: true, inherited: false })
  })
}

test('editing then restoring the submitted amount restores confirmation', () => {
  const edited = needTermsKey({ ...terms, requested_amount: '950000.00' })
  assert.equal(needConfirmation(true, edited, baseline, false, null).confirmed, false)
  assert.deepEqual(needConfirmation(true, needTermsKey(terms), baseline, false, null), { confirmed: true, inherited: true })
})

test('equivalent amount formatting does not change the terms', () => {
  assert.equal(needTermsKey({ ...terms, requested_amount: '1000000' }), baseline)
  assert.notEqual(needTermsKey({ ...terms, requested_amount: '1000000.01' }), baseline)
})

test('financial corrections, answer text and purpose description do not change financing terms', () => {
  const corrected = { ...terms, purpose_details: 'Уточнённое описание', financial_months: [{ cash_inflow: '2500000.00' }], info_response: 'Данные дополнены' }
  assert.equal(needTermsKey(corrected), baseline)
})

test('an explicit confirmation only covers the exact current conditions', () => {
  const changed = needTermsKey({ ...terms, term_months: 24 })
  assert.equal(needConfirmation(true, changed, baseline, true, changed).confirmed, true)
  assert.equal(needConfirmation(true, needTermsKey({ ...terms, term_months: 36 }), baseline, true, changed).confirmed, false)
})

test('missing server snapshot never inherits or trusts a stored browser flag', () => {
  assert.deepEqual(needConfirmation(true, baseline, null, true, baseline), { confirmed: false, inherited: false })
})

test('legacy browser flags without condition keys cannot confirm changed terms', () => {
  assert.equal(needConfirmation(true, needTermsKey({ ...terms, term_months: 24 }), baseline, true, null).confirmed, false)
})

test('the latest submitted snapshot becomes the reference for the next request', () => {
  const revision = { ...terms, requested_amount: '900000.00', financial_snapshot: { purchase_from_bank_partner: true } }
  const latest = submittedNeedKey(revision)
  assert.notEqual(latest, baseline)
  assert.equal(needConfirmation(true, latest, latest, false, null).confirmed, true)
  assert.equal(needConfirmation(true, baseline, latest, true, latest).confirmed, false)
})

test('historical snapshots without a partner flag use false', () => {
  assert.equal(submittedNeedKey({ ...terms, financial_snapshot: {} }), baseline)
})

test('invalid or incomplete fields cannot inherit confirmation', () => {
  for (const change of [{ requested_amount: null }, { requested_amount: 'invalid' }, { requested_amount: 'Infinity' }, { requested_amount: '' }, { term_months: null }, { term_months: 0 }, { purpose_code: null }]) {
    const invalid = needTermsKey({ ...terms, ...change })
    assert.equal(invalid, null)
    assert.equal(needConfirmation(true, invalid, baseline, true, invalid).confirmed, false)
  }
})

test('initial drafts still require their own explicit confirmation', () => {
  assert.deepEqual(needConfirmation(false, baseline, baseline, false, null), { confirmed: false, inherited: false })
  assert.deepEqual(needConfirmation(false, baseline, null, true, baseline), { confirmed: true, inherited: false })
})
