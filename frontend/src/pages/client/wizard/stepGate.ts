import { useCallback, useEffect, useState } from 'react'
import type { Draft, FormStep, Product } from '../../../api/types'
import { moneyShort, parseMoney } from '../../../lib/format'
import type { FormState } from './useDraftEditor'
import { needConfirmation } from './needConfirmation'

export interface Missing {
  label: string
  anchor: string
}

/** What still has to be filled on a step before it can be confirmed. */
export function stepMissing(step: FormStep, form: FormState, product: Product | undefined, localErrors: Record<string, string>, requested: Set<string> = new Set()): Missing[] {
  const out: Missing[] = []
  if (step === 'NEED') {
    const min = Number(product?.min_amount ?? 100000)
    const max = Number(product?.max_amount ?? 5000000)
    const tmin = product?.min_term_months ?? 6
    const tmax = product?.max_term_months ?? 60
    if (!form.purpose) out.push({ label: 'Цель финансирования', anchor: 'purpose' })
    const a = parseMoney(form.amount)
    const n = a && a !== 'invalid' ? Number(a) : null
    if (n === null || n < min || n > max) out.push({ label: `Сумма от ${moneyShort(min)} до ${moneyShort(max)}`, anchor: 'amount' })
    if (form.term === null || form.term < tmin || form.term > tmax) out.push({ label: `Срок от ${tmin} до ${tmax} месяцев`, anchor: 'term' })
  }
  if (step === 'FINANCES') {
    // The table is read-only; only cells the bank asked for must be filled before confirming.
    const keys = ['cash_inflow', 'operating_outflow', 'existing_debt_payment'] as const
    const names = { cash_inflow: 'поступления', operating_outflow: 'операционные выплаты', existing_debt_payment: 'платежи по долгам' }
    for (const m of form.months) {
      for (const k of keys) {
        const path = `draft_data.financial_months.${m.month}.${k}`
        if (!requested.has(path) && !requested.has('draft_data.financial_months')) continue
        if (!m[k] || localErrors[path]) {
          const d = new Date(m.month + 'T00:00:00').toLocaleDateString('ru-RU', { month: 'long', year: 'numeric' }).replace(' г.', '')
          out.push({ label: `${d.charAt(0).toUpperCase() + d.slice(1)}: ${names[k]}`, anchor: path })
        }
      }
    }
  }
  if (step === 'REVIEW') {
    if (!form.dataConfirmed) out.push({ label: 'Подтверждение, что сведения верны', anchor: 'confirm' })
    if (!form.bkiAllowed) out.push({ label: 'Согласие на проверку кредитной истории', anchor: 'bki' })
  }
  if (step === 'NEED') {
    for (const [field, message] of Object.entries(localErrors)) {
      const anchor = ({ requested_amount: 'amount', term_months: 'term', purpose_code: 'purpose', purpose_details: 'details' } as Record<string, string>)[field]
      if (anchor && !out.some((item) => item.anchor === anchor)) out.push({ label: message, anchor })
    }
  }
  return out
}

type Confirmed = Partial<Record<FormStep, boolean>>

/** Final review starts fresh each round. NEED can inherit the last server submission. */
export function useStepConfirm(app: Draft, currentNeedKey: string | null, submittedKey: string | null) {
  const key = `cc-steps:${app.id}:${app.latest_revision_no ?? 0}`
  const read = () => {
    let confirmed: Confirmed = {}
    let needKey: string | null = null
    try {
      const value = JSON.parse(localStorage.getItem(key) || '{}')
      if (value && typeof value === 'object' && !Array.isArray(value)) {
        confirmed = Object.fromEntries(['NEED', 'REVIEW'].filter((s) => value[s] === true).map((s) => [s, true]))
        needKey = typeof value.needKey === 'string' ? value.needKey : null
      }
    } catch {
      /* No browser storage: the server snapshot still restores unchanged NEED. */
    }
    return { key, confirmed, needKey, editingNeed: false }
  }
  const [state, setState] = useState(read)
  const current = state.key === key ? state : read()
  const isReply = app.status === 'NEEDS_INFO'
  const need = needConfirmation(isReply, currentNeedKey, submittedKey, !!current.confirmed.NEED, current.needKey)
  const confirmed = { ...current.confirmed, NEED: need.confirmed }
  useEffect(() => {
    if (state.key !== key) setState(read())
  }, [key, state.key])
  useEffect(() => {
    if (state.key !== key) return
    try {
      localStorage.setItem(key, JSON.stringify({ ...state.confirmed, needKey: state.needKey }))
    } catch {
      /* storage unavailable: confirmations live for this visit only */
    }
  }, [key, state])

  const confirm = useCallback((s: FormStep) => setState((c) => {
    const previous = c.key === key ? c : read()
    return { ...previous, confirmed: { ...previous.confirmed, [s]: true }, needKey: s === 'NEED' ? currentNeedKey : previous.needKey, editingNeed: false }
  }), [key, currentNeedKey])
  /** Editing any earlier step also reopens the final review. */
  const unlock = useCallback((s: FormStep) => setState((c) => {
    const previous = c.key === key ? c : read()
    return { ...previous, confirmed: { ...previous.confirmed, [s]: false, REVIEW: false }, needKey: s === 'NEED' ? null : previous.needKey, editingNeed: isReply && s === 'NEED' }
  }), [key, isReply])
  const closeNeedEditor = useCallback(() => setState((c) => c.editingNeed ? { ...c, editingNeed: false } : c), [])
  return { confirmed, confirm, unlock, closeNeedEditor, editingNeed: current.editingNeed, inheritedNeed: need.inherited }
}
