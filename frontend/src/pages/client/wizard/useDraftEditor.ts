import { useQueryClient } from '@tanstack/react-query'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { ApiError } from '../../../api/client'
import { applications } from '../../../api/endpoints'
import type { Draft, DraftPatch, FormStep, Product, Purpose } from '../../../api/types'
import { moneyToInput, parseMoney } from '../../../lib/format'
import type { FinKey } from '../../../lib/labels'

export interface MonthRow {
  month: string
  cash_inflow: string
  operating_outflow: string
  existing_debt_payment: string
}

export interface FormState {
  amount: string
  term: number | null
  purpose: Purpose | null
  details: string
  months: MonthRow[]
  dataConfirmed: boolean
  bkiAllowed: boolean
  infoResponse: string
  step: FormStep
}

export type SaveState = 'idle' | 'pending' | 'saving' | 'saved' | 'error' | 'conflict'

const fromDraft = (d: Draft): FormState => ({
  amount: moneyToInput(d.requested_amount),
  term: d.term_months,
  purpose: d.purpose_code,
  details: d.purpose_details ?? '',
  months: d.draft_data.financial_months.map((m) => ({
    month: m.month,
    cash_inflow: moneyToInput(m.cash_inflow),
    operating_outflow: moneyToInput(m.operating_outflow),
    existing_debt_payment: moneyToInput(m.existing_debt_payment),
  })),
  dataConfirmed: d.draft_data.confirmations.data_confirmed,
  bkiAllowed: d.draft_data.confirmations.credit_history_check_allowed,
  infoResponse: d.draft_data.info_response ?? '',
  step: d.ui_step,
})

type Field = 'amount' | 'term' | 'purpose' | 'details' | 'months' | 'confirmations' | 'info' | 'step'
const DEBOUNCE_MS = 900

/** Local form state + serialized autosave with optimistic-lock version (expected_version).
    One request in flight at a time; edits made during a save are queued for the next one.
    409 stops autosave and asks the user to load the actual version, without overwriting. */
export function useDraftEditor(initial: Draft) {
  const qc = useQueryClient()
  const id = initial.id
  const [form, setForm] = useState<FormState>(() => fromDraft(initial))
  const [server, setServer] = useState<Draft>(initial)
  const [state, setState] = useState<SaveState>('idle')
  const [savedAt, setSavedAt] = useState<Date | null>(null)
  const [error, setError] = useState<ApiError | null>(null)
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({})

  const formRef = useRef(form)
  formRef.current = form
  const versionRef = useRef(initial.version)
  const dirty = useRef(new Set<Field>())
  const inflight = useRef<Promise<void> | null>(null)
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null)
  const blocked = useRef(false)
  const waiters = useRef<(() => void)[]>([])

  const localErrors = useMemo(() => {
    const e: Record<string, string> = {}
    if (parseMoney(form.amount) === 'invalid') e.requested_amount = 'Введите сумму числом, до двух знаков после запятой'
    form.months.forEach((m) =>
      (['cash_inflow', 'operating_outflow', 'existing_debt_payment'] as FinKey[]).forEach((k) => {
        if (parseMoney(m[k]) === 'invalid') e[`draft_data.financial_months.${m.month}.${k}`] = 'Некорректная сумма'
      }),
    )
    return e
  }, [form.amount, form.months])
  const localErrorsRef = useRef(localErrors)
  localErrorsRef.current = localErrors

  const buildPatch = useCallback((fields: Set<Field>): { patch: DraftPatch; sent: Set<Field> } => {
    const f = formRef.current
    const p: DraftPatch = { expected_version: versionRef.current }
    const sent = new Set<Field>()
    const dd: NonNullable<DraftPatch['draft_data']> = {}
    for (const k of fields) {
      if (k === 'amount') {
        const v = parseMoney(f.amount)
        if (v === 'invalid') continue
        p.requested_amount = v
      } else if (k === 'term') p.term_months = f.term
      else if (k === 'purpose') p.purpose_code = f.purpose
      else if (k === 'details') p.purpose_details = f.details.trim() ? f.details : null
      else if (k === 'step') p.ui_step = f.step
      else if (k === 'months') {
        const rows = f.months.map((m) => ({
          month: m.month,
          cash_inflow: parseMoney(m.cash_inflow),
          operating_outflow: parseMoney(m.operating_outflow),
          existing_debt_payment: parseMoney(m.existing_debt_payment),
        }))
        if (rows.some((r) => r.cash_inflow === 'invalid' || r.operating_outflow === 'invalid' || r.existing_debt_payment === 'invalid')) continue
        dd.financial_months = rows as NonNullable<typeof dd.financial_months>
      } else if (k === 'confirmations') dd.confirmations = { data_confirmed: f.dataConfirmed, credit_history_check_allowed: f.bkiAllowed }
      else if (k === 'info') dd.info_response = f.infoResponse.trim() ? f.infoResponse : null
      sent.add(k)
    }
    if (Object.keys(dd).length) p.draft_data = dd
    return { patch: p, sent }
  }, [])

  const lastFailed = useRef<ApiError | null>(null)
  const settle = () => {
    if (inflight.current) return
    waiters.current.forEach((w) => w())
    waiters.current = []
  }

  const run = useCallback(async (): Promise<void> => {
    if (blocked.current) return settle()
    if (inflight.current) return inflight.current
    if (!dirty.current.size) return settle()
    const fields = new Set(dirty.current)
    const { patch, sent } = buildPatch(fields)
    sent.forEach((k) => dirty.current.delete(k))
    if (!sent.size) {
      // Only locally invalid fields are dirty: nothing can be sent until the user fixes them.
      lastFailed.current = new ApiError(422, { code: 'VALIDATION_ERROR', message: 'Исправьте выделенные поля' }, '')
      setState('error')
      return settle()
    }
    setState('saving')
    let ok = false
    const p = (async () => {
      try {
        const d = await applications.patch(id, patch)
        ok = true
        lastFailed.current = null
        versionRef.current = d.version
        setServer(d)
        qc.setQueryData(['application', id], d)
        setSavedAt(new Date())
        setError(null)
        setFieldErrors((fe) => {
          const n = { ...fe }
          for (const k of Object.keys(n)) if (sent.has(fieldOf(k))) delete n[k]
          return n
        })
        setState(dirty.current.size ? 'pending' : 'saved')
      } catch (e) {
        const err = e instanceof ApiError ? e : new ApiError(0, null, 'Не удалось сохранить')
        lastFailed.current = err
        setError(err)
        if (err.status === 409) {
          blocked.current = true
          setState('conflict')
        } else if (err.status === 422) {
          // Invalid values are not resent automatically; the user fixes the field first.
          setFieldErrors((fe) => ({ ...fe, ...Object.fromEntries(err.fieldErrors.map((x) => [x.field, x.message])) }))
          setState('error')
        } else {
          sent.forEach((k) => dirty.current.add(k)) // network/5xx: keep for retry
          setState('error')
        }
      } finally {
        inflight.current = null
      }
    })()
    inflight.current = p
    await p
    if (ok && dirty.current.size && !blocked.current) {
      // Edits arrived during the request: send them right away (also serves flush waiters).
      await run()
      return
    }
    settle()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [buildPatch, id, qc])

  const schedule = useCallback(
    (ms = DEBOUNCE_MS) => {
      if (timer.current) clearTimeout(timer.current)
      timer.current = setTimeout(() => {
        timer.current = null
        void run()
      }, ms)
    },
    [run],
  )

  const update = useCallback(
    (patch: Partial<FormState>, fields: Field[], immediate = false) => {
      setForm((f) => ({ ...f, ...patch }))
      fields.forEach((k) => dirty.current.add(k))
      if (blocked.current) return
      setState('pending')
      schedule(immediate ? 60 : DEBOUNCE_MS)
    },
    [schedule],
  )

  /** Resolves when every edit made so far is confirmed by the server. */
  const flush = useCallback(async () => {
    if (blocked.current) throw new ApiError(409, { code: 'VERSION_CONFLICT', message: 'Черновик изменён в другом окне' }, '')
    if (timer.current) {
      clearTimeout(timer.current)
      timer.current = null
    }
    if (!dirty.current.size && !inflight.current) {
      if (Object.keys(localErrorsRef.current).length) throw new ApiError(422, { code: 'VALIDATION_ERROR', message: 'Исправьте выделенные поля' }, '')
      return
    }
    await new Promise<void>((resolve) => {
      waiters.current.push(resolve)
      void run()
    })
    if (blocked.current) throw new ApiError(409, { code: 'VERSION_CONFLICT', message: 'Черновик изменён в другом окне' }, '')
    if (dirty.current.size || lastFailed.current) throw lastFailed.current ?? new ApiError(0, null, 'Черновик не сохранён')
  }, [run])

  const retry = useCallback(() => {
    setState('pending')
    void run()
  }, [run])

  /** Conflict resolution: take the actual server version, drop local unsaved edits. */
  const reload = useCallback(async () => {
    const d = await applications.get(id)
    blocked.current = false
    dirty.current.clear()
    versionRef.current = d.version
    setServer(d)
    setForm(fromDraft(d))
    qc.setQueryData(['application', id], d)
    setError(null)
    setFieldErrors({})
    setState('saved')
    return d
  }, [id, qc])

  /** After submit the server draft changes status; adopt it. */
  const adopt = useCallback(
    (d: Draft) => {
      versionRef.current = d.version
      setServer(d)
      qc.setQueryData(['application', id], d)
    },
    [id, qc],
  )

  useEffect(() => () => {
    if (timer.current) clearTimeout(timer.current)
  }, [])

  // Best effort: flush pending edits when the tab is hidden.
  useEffect(() => {
    const h = () => {
      if (document.visibilityState === 'hidden' && dirty.current.size && !blocked.current) void run()
    }
    document.addEventListener('visibilitychange', h)
    return () => document.removeEventListener('visibilitychange', h)
  }, [run])

  const busy = state === 'saving' || state === 'pending'
  return { form, server, update, flush, retry, reload, adopt, state, savedAt, error, fieldErrors: { ...fieldErrors, ...localErrors }, busy, versionRef }
}

function fieldOf(path: string): Field {
  if (path.startsWith('draft_data.financial_months')) return 'months'
  if (path.startsWith('draft_data.confirmations')) return 'confirmations'
  if (path === 'draft_data.info_response') return 'info'
  return ({ requested_amount: 'amount', term_months: 'term', purpose_code: 'purpose', purpose_details: 'details', ui_step: 'step' } as Record<string, Field>)[path] ?? 'amount'
}

/** Readiness navigator: what is missing before submit (client-side mirror of required inputs). */
export function readiness(form: FormState, product?: Product) {
  const amount = parseMoney(form.amount)
  const amountNum = typeof amount === 'string' && amount !== 'invalid' ? Number(amount) : null
  const amountOk = amountNum !== null && (!product || (amountNum >= Number(product.min_amount) && amountNum <= Number(product.max_amount)))
  const termOk = form.term !== null && (!product || (form.term >= product.min_term_months && form.term <= product.max_term_months))
  const filled = form.months.filter((m) => m.cash_inflow && m.operating_outflow && m.existing_debt_payment).length
  const items = [
    { id: 'purpose', label: 'Цель финансирования', ok: !!form.purpose, step: 'NEED' as FormStep, blocking: true },
    { id: 'amount', label: 'Сумма в границах продукта', ok: amountOk, step: 'NEED' as FormStep, blocking: true },
    { id: 'term', label: 'Срок в границах продукта', ok: termOk, step: 'NEED' as FormStep, blocking: true },
    { id: 'months', label: `Финансы за 6 месяцев (${filled}/${form.months.length || 6})`, ok: filled === form.months.length && filled > 0, step: 'FINANCES' as FormStep, blocking: true },
    { id: 'confirm', label: 'Подтверждение данных', ok: form.dataConfirmed, step: 'REVIEW' as FormStep, blocking: true },
    { id: 'bki', label: 'Согласие на проверку истории', ok: form.bkiAllowed, step: 'REVIEW' as FormStep, blocking: true },
  ]
  return { items, done: items.filter((i) => i.ok).length, canSubmit: items.every((i) => i.ok || !i.blocking), amountNum }
}
