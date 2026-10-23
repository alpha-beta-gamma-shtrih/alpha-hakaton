import { useCallback, useEffect, useState } from 'react'
import type { Draft, FormStep, Product } from '../../../api/types'
import { moneyShort, parseMoney } from '../../../lib/format'
import type { FormState } from './useDraftEditor'

export interface Missing {
  label: string
  anchor: string
}

/** What still has to be filled on a step before it can be confirmed. */
export function stepMissing(step: FormStep, form: FormState, product: Product | undefined, _localErrors: Record<string, string>): Missing[] {
  const out: Missing[] = []
  if (step === 'NEED') {
    const min = Number(product?.min_amount ?? 100000)
    const max = Number(product?.max_amount ?? 5000000)
    const tmin = product?.min_term_months ?? 6
    const tmax = product?.max_term_months ?? 24
    if (!form.purpose) out.push({ label: 'Цель финансирования', anchor: 'purpose' })
    const a = parseMoney(form.amount)
    const n = a && a !== 'invalid' ? Number(a) : null
    if (n === null || n < min || n > max) out.push({ label: `Сумма от ${moneyShort(min)} до ${moneyShort(max)}`, anchor: 'amount' })
    if (form.term === null || form.term < tmin || form.term > tmax) out.push({ label: `Срок от ${tmin} до ${tmax} месяцев`, anchor: 'term' })
  }
  if (step === 'REVIEW') {
    if (!form.dataConfirmed) out.push({ label: 'Подтверждение, что сведения верны', anchor: 'confirm' })
    if (!form.bkiAllowed) out.push({ label: 'Согласие на проверку кредитной истории', anchor: 'bki' })
  }
  return out
}

type Confirmed = Partial<Record<FormStep, boolean>>

/** Per-step confirmations. Kept in this browser per application and submission round,
    so a new round after a bank request starts unconfirmed. */
export function useStepConfirm(app: Draft) {
  const key = `cc-steps:${app.id}:${app.latest_revision_no ?? 0}`
  const read = (): Confirmed => {
    try {
      return JSON.parse(localStorage.getItem(key) || '{}')
    } catch {
      return {}
    }
  }
  const [confirmed, setConfirmed] = useState<Confirmed>(read)
  useEffect(() => {
    try {
      localStorage.setItem(key, JSON.stringify(confirmed))
    } catch {
      /* storage unavailable: confirmations live for this visit only */
    }
  }, [key, confirmed])

  const confirm = useCallback((s: FormStep) => setConfirmed((c) => ({ ...c, [s]: true })), [])
  /** Editing any earlier step also reopens the final review. */
  const unlock = useCallback((s: FormStep) => setConfirmed((c) => ({ ...c, [s]: false, REVIEW: false })), [])
  return { confirmed, confirm, unlock }
}
