import { useMemo, useRef, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { ApiError } from '../../../api/client'
import { applications } from '../../../api/endpoints'
import type { Draft, FormStep } from '../../../api/types'
import { Arrow, Button, CheckIcon, ErrorNotice, Notice, StatusChip, useToast } from '../../../components/ui'
import { parseMoney, shortId } from '../../../lib/format'
import { requestedFieldLabel, STEPS } from '../../../lib/labels'
import { useCompany, useProducts } from '../../../lib/queries'
import { AdvisorDock, CalcPanel, ReadinessCard, useScenarios, Variants } from './Aside'
import { StepCompany, StepFinances, StepNeed, StepReview } from './steps'
import { readiness, useDraftEditor } from './useDraftEditor'
import { stepMissing, useStepConfirm } from './stepGate'
import { needTermsKey, submittedNeedKey } from './needConfirmation'

const uuid = () =>
  (crypto as Crypto & { randomUUID?: () => string }).randomUUID?.() ??
  'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, (c) => {
    const r = (Math.random() * 16) | 0
    return (c === 'x' ? r : (r & 0x3) | 0x8).toString(16)
  })

const FIELD_STEP = (f: string): FormStep =>
  f === 'draft_data.purchase_from_bank_partner' ? 'NEED' : f.startsWith('draft_data.financial_months') ? 'FINANCES' : f.startsWith('draft_data.') ? 'REVIEW' : 'NEED'

const CONFIRMABLE: FormStep[] = ['NEED', 'COMPANY', 'FINANCES', 'REVIEW']

const FIELD_ANCHOR = (f: string): string =>
  ({ requested_amount: 'amount', term_months: 'term', purpose_code: 'purpose', purpose_details: 'details', 'draft_data.info_response': 'info', 'draft_data.financial_months': 'months' } as Record<string, string>)[f] ?? f

export function Wizard({ draft, onSubmitted }: { draft: Draft; onSubmitted: (d: Draft) => void }) {
  const ed = useDraftEditor(draft)
  const products = useProducts()
  const product = products.data?.items.find((p) => p.id === draft.product_id)
  const company = useCompany(draft.company_id)
  const ready = readiness(ed.form, product)
  const scen = useScenarios(ed, ready)
  const toast = useToast()
  const step = ed.form.step
  const stepIdx = STEPS.findIndex((s) => s.id === step)
  const [submitting, setSubmitting] = useState(false)
  const [submitError, setSubmitError] = useState<ApiError | null>(null)
  const submitAttempt = useRef<{ key: string; version: number } | null>(null)
  const topRef = useRef<HTMLDivElement>(null)

  const info = ed.server.open_information_request
  const highlight = useMemo(() => new Set(info?.requested_fields ?? []), [info])
  const isReply = ed.server.status === 'NEEDS_INFO'
  const previous = useQuery({
    queryKey: ['revision', ed.server.id, ed.server.latest_revision_no],
    queryFn: () => applications.revision(ed.server.id, ed.server.latest_revision_no!),
    enabled: isReply && !!ed.server.latest_revision_no,
    staleTime: Infinity,
  })
  const baseline = previous.data?.application_id === ed.server.id && previous.data.revision_no === ed.server.latest_revision_no ? submittedNeedKey(previous.data) : null
  const waitingForBaseline = isReply && !baseline
  const currentNeedKey = stepMissing('NEED', ed.form, product, ed.fieldErrors).length ? null : needTermsKey({
    requested_amount: parseMoney(ed.form.amount), term_months: ed.form.term, purpose_code: ed.form.purpose, purchase_from_bank_partner: ed.form.partnerPurchase,
  })
  const gate = useStepConfirm(ed.server, currentNeedKey, baseline)
  // Only pages where the client makes choices are confirmed; read-only pages just move on.
  const needsConfirm = CONFIRMABLE.includes(step)
  const locked = needsConfirm && !!gate.confirmed[step] && !(step === 'NEED' && gate.editingNeed)
  const unchangedNeedEditor = step === 'NEED' && gate.editingNeed && gate.confirmed.NEED
  const missing = needsConfirm ? stepMissing(step, ed.form, product, ed.fieldErrors, highlight) : []
  const allConfirmed = CONFIRMABLE.every((s) => gate.confirmed[s])
  const [confirming, setConfirming] = useState(false)
  // ?ai=1 comes from the global helper: open the panel right away.
  const [aiOpen, setAiOpen] = useState(() => new URLSearchParams(window.location.search || window.location.hash.split('?')[1] || '').get('ai') === '1')
  const confirmStep = async () => {
    if (missing.length || confirming || submitting || submitAttempt.current || (step === 'NEED' && waitingForBaseline)) return
    setConfirming(true)
    try {
      await ed.flush()
      gate.confirm(step)
    } catch (e) {
      toast.error(e, 'Не удалось сохранить шаг')
    } finally {
      setConfirming(false)
    }
  }


  /** Opens a step; with an anchor, scrolls to that field, flashes it and puts the cursor in it. */
  const go = (s: FormStep, anchor?: string) => {
    if (submitting || submitAttempt.current || ed.commandBusy) return
    if (s !== 'NEED') gate.closeNeedEditor()
    if (s !== ed.form.step) ed.update({ step: s }, ['step'], true)
    if (!anchor) {
      topRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' })
      return
    }
    const find = (tries: number) => {
      const root = document.querySelector('.wz-main')
      let el: HTMLElement | null = null
      if (anchor === 'months') el = root?.querySelector<HTMLElement>('.fin-cell input.empty') ?? root?.querySelector<HTMLElement>('[data-anchor="months"]') ?? null
      if (!el) el = root?.querySelector<HTMLElement>(`[data-anchor="${CSS.escape(anchor)}"]`) ?? null
      if (!el) {
        if (tries > 0) setTimeout(() => find(tries - 1), 60)
        return
      }
      const box = (el.closest('[data-anchor]') as HTMLElement | null) ?? el
      box.scrollIntoView({ behavior: 'smooth', block: 'center' })
      box.classList.remove('pulse')
      void box.offsetWidth
      box.classList.add('pulse')
      setTimeout(() => box.classList.remove('pulse'), 2300)
      const focusable = el.matches('input, textarea, button') ? el : el.querySelector<HTMLElement>('input:not([type=range]), textarea, button, input')
      setTimeout(() => focusable?.focus({ preventScroll: true }), 350)
    }
    setTimeout(() => find(10), 40)
  }

  const submit = async () => {
    setSubmitting(true)
    setSubmitError(null)
    try {
      if (!submitAttempt.current) {
        await ed.flush()
        submitAttempt.current = { key: uuid(), version: ed.versionRef.current }
      }
      const attempt = submitAttempt.current
      const res = await applications.submit(ed.server.id, attempt.version, attempt.key)
      submitAttempt.current = null
      ed.adopt(res.application)
      onSubmitted(res.application)
    } catch (e) {
      const err = e instanceof ApiError ? e : new ApiError(0, null, 'Не удалось отправить')
      // A network error or 5xx can arrive after the transaction committed.
      if (err.status >= 400 && err.status < 500) submitAttempt.current = null
      setSubmitError(err)
      if (err.fieldErrors.length) gate.unlock(FIELD_STEP(err.fieldErrors[0].field))
      if (err.fieldErrors.length) go(FIELD_STEP(err.fieldErrors[0].field), FIELD_ANCHOR(err.fieldErrors[0].field.replace('draft_data.confirmations.data_confirmed', 'confirm').replace('draft_data.confirmations.credit_history_check_allowed', 'bki')))
      toast.error(err, 'Заявка не отправлена')
    } finally {
      setSubmitting(false)
    }
  }

  const saveLabel = {
    idle: 'Все изменения сохранены',
    saved: ed.savedAt ? `Сохранено в ${ed.savedAt.toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit' })}` : 'Сохранено',
    pending: 'Есть изменения',
    saving: 'Сохраняем…',
    error: 'Не сохранено',
    conflict: 'Конфликт версий',
  }[ed.state]

  return (
    <div className="page wizard" ref={topRef}>
      <div className="wz-head">
        <div>
          <Link to="/applications" className="back">
            <Arrow dir="left" /> Мои заявки
          </Link>
          <h1 className="page-title">
            {ed.server.status === 'NEEDS_INFO' ? 'Дополните заявку' : 'Подбор финансирования'}
          </h1>
          <div className="row wrap" style={{ marginTop: 12 }}>
            <StatusChip status={ed.server.status} />
            <span className="hint mono">№ {shortId(ed.server.id)}</span>
            {ed.server.latest_revision_no && (
              <Link className="link-btn" to={`?view=status`} style={{ fontSize: 13 }}>
                История отправок
              </Link>
            )}
          </div>
        </div>
        <div className={`save-pill s-${ed.state}`} aria-live="polite">
          <i />
          {saveLabel}
          {ed.state === 'error' && ed.error?.status !== 422 && (
            <button className="link-btn" onClick={ed.retry}>
              повторить
            </button>
          )}
        </div>
      </div>

      {ed.state === 'conflict' && (
        <div style={{ marginBottom: 18 }}>
          <Notice tone="error" title="Черновик изменён в другом окне или устройстве">
            Чтобы ничего не перезаписать, автосохранение остановлено. Загрузите актуальную версию — несохранённые здесь правки будут отброшены.
            <div style={{ marginTop: 10 }}>
              <Button size="sm" variant="red" onClick={() => ed.reload()}>
                Загрузить актуальную версию
              </Button>
            </div>
          </Notice>
        </div>
      )}

      {info && (
        <section className="panel violet dots info-req rise">
          <span className="tag white">Запрос от банка</span>
          <p className="info-msg">{info.message_to_client}</p>
          <div className="row wrap" style={{ gap: 8 }}>
            {info.requested_fields.map((f) => (
              <button key={f} className="field-pill" onClick={() => go(FIELD_STEP(f), FIELD_ANCHOR(f))}>
                {requestedFieldLabel(f)} <Arrow size={12} />
              </button>
            ))}
          </div>
        </section>
      )}
      {isReply && previous.error && <ErrorNotice error={previous.error} onRetry={() => previous.refetch()} />}
      {waitingForBaseline && !previous.error && <Notice tone="plain">Загружаем последнюю отправку, чтобы проверить, изменились ли условия финансирования.</Notice>}

      <nav className="stepper" aria-label="Шаги заявки">
        {STEPS.map((s, i) => (
          <button key={s.id} className={`step ${i === stepIdx ? 'cur' : ''} ${CONFIRMABLE.includes(s.id) && gate.confirmed[s.id] ? 'ok' : ''}`} onClick={() => go(s.id)} aria-current={i === stepIdx ? 'step' : undefined}>
            <span className="step-n display">{CONFIRMABLE.includes(s.id) && gate.confirmed[s.id] ? <CheckIcon size={18} color="currentColor" /> : i + 1}</span>
            <span className="step-t">
              <b>{s.title}</b>
              <span>{CONFIRMABLE.includes(s.id) && gate.confirmed[s.id] ? 'Подтверждено' : s.short}</span>
            </span>
          </button>
        ))}
      </nav>

      <div className="wz-grid">
        <div className="wz-main" key={step}>
          {locked && (
            <div className="locked-banner rise">
              <span className="lb-ic">
                <CheckIcon size={16} color="var(--ink)" />
              </span>
              <div className="grow">
                <b>Шаг «{STEPS[stepIdx].title}» подтверждён</b>
                <span>{step === 'NEED' && gate.inheritedNeed ? 'Условия совпадают с последней отправкой. Повторное подтверждение не требуется.' : 'Данные зафиксированы. Чтобы что-то поменять, нажмите «Редактировать».'}</span>
              </div>
              <Button size="sm" variant="white" disabled={submitting || !!submitAttempt.current} onClick={() => gate.unlock(step)}>
                Редактировать
              </Button>
            </div>
          )}
          <fieldset className={`step-fieldset rise ${locked ? 'locked' : ''}`} disabled={locked || submitting || ed.commandBusy || !!submitAttempt.current}>
            {step === 'NEED' && <StepNeed ed={ed} product={product} highlight={highlight} />}
            {step === 'COMPANY' && <StepCompany company={company.data} draft={ed.server} />}
            {step === 'FINANCES' && <StepFinances ed={ed} highlight={highlight} />}
            {step === 'REVIEW' && <StepReview ed={ed} company={company.data} product={product} ready={ready} highlight={highlight} candidate={!ed.busy && ed.state !== 'error' && ed.state !== 'conflict' && !scen.isPlaceholderData && scen.data?.application_version === ed.server.version ? scen.data.candidates[0] : undefined} />}
          </fieldset>

          {submitError && step === 'REVIEW' && (
            <div style={{ marginTop: 16 }}>
              <Notice tone="error" title={submitError.message}>
                {submitError.fieldErrors.map((f) => (
                  <div key={f.field}>{f.message}</div>
                ))}
                {(submitError.status === 0 || submitError.status >= 500) && 'Исход отправки пока не подтверждён. Повторите отправку с теми же данными — дубль не создастся.'}
              </Notice>
            </div>
          )}

          <div className={`step-bar ${!needsConfirm ? 'plain' : locked ? 'done' : missing.length ? 'todo' : 'ready'}`}>
            {!needsConfirm && <div className="sb-text">Здесь ничего выбирать не нужно — проверьте данные и переходите дальше.</div>}
            {!locked && missing.length > 0 && (
              <div className="sb-missing">
                <b>Чтобы подтвердить страницу, заполните:</b>
                <ul>
                  {missing.slice(0, 4).map((m) => (
                    <li key={m.anchor}>
                      <button type="button" onClick={() => go(step, m.anchor)}>
                        {m.label}
                      </button>
                    </li>
                  ))}
                  {missing.length > 4 && <li className="more">и ещё {missing.length - 4}</li>}
                </ul>
              </div>
            )}
            {needsConfirm && !locked && missing.length === 0 && <div className="sb-text">{unchangedNeedEditor ? 'Условия уже подтверждены. Можно переходить дальше.' : step === 'COMPANY' || step === 'FINANCES' ? 'Проверьте данные и подтвердите страницу.' : 'Всё заполнено. Проверьте данные и подтвердите страницу.'}</div>}
            {locked && (
              <div className="sb-text sb-ok">
                <CheckIcon size={14} color="var(--ink)" /> Страница подтверждена
              </div>
            )}
            <div className="sb-actions">
              {stepIdx > 0 && (
                <Button variant="ghost" onClick={() => go(STEPS[stepIdx - 1].id)}>
                  <Arrow dir="left" /> Назад
                </Button>
              )}
              {!needsConfirm || unchangedNeedEditor ? (
                <Button variant="ink" onClick={() => go(STEPS[stepIdx + 1].id)}>
                  Далее: {STEPS[stepIdx + 1].title} <Arrow />
                </Button>
              ) : !locked ? (
                <Button variant="lime" loading={confirming} disabled={missing.length > 0 || ed.state === 'conflict' || ed.commandBusy || (step === 'NEED' && waitingForBaseline)} onClick={confirmStep}>
                  Подтвердить
                </Button>
              ) : step !== 'REVIEW' ? (
                <Button variant="ink" onClick={() => go(STEPS[stepIdx + 1].id)}>
                  Далее: {STEPS[stepIdx + 1].title} <Arrow />
                </Button>
              ) : (
                <Button variant="red" size="lg" loading={submitting} disabled={!allConfirmed || waitingForBaseline || !ready.canSubmit || Object.keys(ed.fieldErrors).length > 0 || ed.state === 'conflict' || ed.commandBusy} onClick={submit}>
                  {ed.server.status === 'NEEDS_INFO' ? 'Отправить повторно' : 'Отправить заявку'} <Arrow />
                </Button>
              )}
            </div>
          </div>
          {step === 'REVIEW' && locked && !allConfirmed && (
            <p className="hint" style={{ textAlign: 'right', marginTop: 10 }}>
              Перед отправкой подтвердите страницы: {STEPS.filter((s) => CONFIRMABLE.includes(s.id) && !gate.confirmed[s.id]).map((s) => `«${s.title}»`).join(', ')}.
            </p>
          )}
        </div>

        <aside className="wz-aside">
          <CalcPanel ed={ed} ready={ready} scen={scen} locked={!!gate.confirmed.REVIEW} />
          <Variants ed={ed} scen={scen} locked={!!gate.confirmed.NEED && !gate.editingNeed} onAskAi={() => setAiOpen(true)} />
          <ReadinessCard ready={ready} onGo={go} />
        </aside>
      </div>
      <AdvisorDock ed={ed} open={aiOpen} onOpen={() => setAiOpen(true)} onClose={() => setAiOpen(false)} />
    </div>
  )
}
