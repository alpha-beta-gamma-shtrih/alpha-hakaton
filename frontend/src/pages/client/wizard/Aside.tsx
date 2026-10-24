import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect } from 'react'
import { createPortal } from 'react-dom'
import { ApiError } from '../../../api/client'
import { PricingBreakdown } from '../../../components/PricingBreakdown'
import { applications } from '../../../api/endpoints'
import type { AdvisorMode, AdvisorReport, Candidate, FormStep } from '../../../api/types'
import { PixelArt } from '../../../components/pixel'
import { AnimatedNumber, Button, Checkbox, CheckIcon, useToast } from '../../../components/ui'
import { groupDigits, money, months, percent, relative } from '../../../lib/format'
import { ADVISOR_CANDIDATE, ROUTING } from '../../../lib/labels'
import type { readiness, useDraftEditor } from './useDraftEditor'

type Editor = ReturnType<typeof useDraftEditor>
type Ready = ReturnType<typeof readiness>

const fmtRub = (n: number) => `${Math.round(n).toLocaleString('ru-RU')} ₽`

/** Preliminary calculation via POST /scenarios. Recomputed for every saved version of the draft. */
export function useScenarios(ed: Editor, ready: Ready) {
  const v = ed.server.version
  const enabled = ready.items[0].ok && ready.items[1].ok && ready.items[2].ok && !ed.busy && ed.state !== 'conflict' && ed.state !== 'error' && ed.server.version === ed.versionRef.current
  return useQuery({
    queryKey: ['scenarios', ed.server.id, v],
    queryFn: () => applications.scenarios(ed.server.id, v),
    enabled,
    staleTime: Infinity,
    placeholderData: (prev) => prev,
    retry: false,
  })
}

export function CalcPanel({ ed, ready, scen, locked }: { ed: Editor; ready: Ready; scen: ReturnType<typeof useScenarios>; locked?: boolean }) {
  const base = scen.data?.candidates.find((c) => c.candidate_id === 'REQUESTED')
  const canCalc = ready.items[1].ok && ready.items[2].ok
  const stale = ed.busy || ed.state === 'conflict' || ed.state === 'error' || scen.isPlaceholderData || (scen.data && scen.data.application_version !== ed.server.version)
  const preview = !stale && ed.form.bkiAllowed && scen.data?.mode === 'PREVIEW'
  const load = base?.load_ratio ? Number(base.load_ratio) : null

  return (
    <section className="panel blue dots calc">
      <div className="row between">
        <span className="tag white sm">Предварительный расчёт</span>
        {scen.isFetching && <span className="calc-live">считаем…</span>}
      </div>
      {!canCalc ? (
        <div className="calc-empty">
          <PixelArt shape="question" size={7} color="rgba(255,255,255,.85)" />
          <p>Укажите сумму и срок в границах продукта — платёж появится здесь.</p>
        </div>
      ) : (
        <>
          <div className={`calc-main ${stale ? 'stale' : ''}`}>
            <span>Платёж в месяц</span>
            <div className="calc-pay display num">
              <AnimatedNumber value={base ? Number(base.monthly_payment) : null} format={fmtRub} />
            </div>
          </div>
          <div className="calc-grid">
            <div>
              <span>Переплата</span>
              <b className="num">{money(base?.estimated_overpayment)}</b>
            </div>
            <div>
              <span>Всего выплат</span>
              <b className="num">{money(base?.estimated_total_payment)}</b>
            </div>
            <div>
              <span>Срок</span>
              <b>{months(base?.term_months)}</b>
            </div>
            <div>
              <span>Ставка</span>
              <b>{base ? `${Number(base.annual_rate_percent)}%` : '—'}</b>
            </div>
          </div>
          {!stale && base && <PricingBreakdown value={base.pricing} />}
          {preview && base ? (
            <div className="calc-preview">
              <div className="row between">
                <span>Долговая нагрузка</span>
                <b className="num">{percent(base.load_ratio)}</b>
              </div>
              <div className="load-bar" aria-hidden="true">
                <i style={{ width: `${Math.min(100, (load ?? 0) * 100 / 0.9)}%`, background: load !== null && load > 0.8 ? 'var(--red)' : load !== null && load > 0.65 ? 'var(--amber)' : 'var(--lime)' }} />
                <em style={{ left: `${(0.8 / 0.9) * 100}%` }} />
              </div>
              <div className="row between" style={{ marginTop: 12 }}>
                <span className={`route r-${base.preliminary_route}`}>{base.preliminary_route ? ROUTING[base.preliminary_route] : '—'}</span>
                <span className="calc-score">риск-балл {base.risk_score ?? '—'}</span>
              </div>
            </div>
          ) : (
            <div className="calc-unlock">
              <p>Нагрузка и предварительный маршрут — после согласия на демо-проверку кредитной истории.</p>
              <Checkbox checked={ed.form.bkiAllowed} disabled={locked} onChange={(v) => ed.update({ bkiAllowed: v }, ['confirmations'], true)} title="Разрешаю демо-проверку истории" desc="Только синтетические данные" />
            </div>
          )}
          {scen.error && <p className="calc-err">{scen.error instanceof ApiError ? scen.error.message : 'Расчёт недоступен'}</p>}
          <p className="calc-foot">Расчёт предварительный и не является решением банка.</p>
        </>
      )}
    </section>
  )
}

export function Variants({ ed, scen, locked, onAskAi }: { ed: Editor; scen: ReturnType<typeof useScenarios>; locked?: boolean; onAskAi?: () => void }) {
  const cands = !ed.busy && ed.state !== 'conflict' && ed.state !== 'error' && !scen.isPlaceholderData && scen.data?.application_version === ed.server.version && (ed.form.bkiAllowed || scen.data.mode === 'CALCULATION_ONLY') ? scen.data.candidates : []
  if (cands.length < 2) return null
  const base = cands[0]
  const pick = (c: Candidate) => ed.update({ amount: groupDigits(String(Number(c.requested_amount))), term: c.term_months }, ['amount', 'term'], true)
  return (
    <section className="card variants">
      <div className="card-head" style={{ marginBottom: 12 }}>
        <div>
          <h3 className="card-title">Варианты</h3>
          <span className="hint">не меняют заявку, пока вы не выберете</span>
        </div>
        {onAskAi && (
          <button type="button" className="ask-ai" onClick={onAskAi}>
            Спросить ИИ
          </button>
        )}
      </div>
      <div className="stack">
        {cands.map((c) => {
          const meta = ADVISOR_CANDIDATE[c.candidate_id]
          const diff = Number(c.monthly_payment) - Number(base.monthly_payment)
          const isCurrent = c.candidate_id === 'REQUESTED'
          return (
            <div key={c.candidate_id} className={`variant ${isCurrent ? 'cur' : ''}`} style={{ ['--vc' as string]: meta.color }}>
              <div className="variant-top">
                <span className="variant-tag">{meta.label}</span>
                {c.preliminary_route && <span className={`route sm r-${c.preliminary_route}`}>{ROUTING[c.preliminary_route]}</span>}
              </div>
              <div className="variant-main">
                <div>
                  <b className="num">{money(c.requested_amount)}</b>
                  <span> · {months(c.term_months)}</span>
                  <span> · {Number(c.annual_rate_percent)}% годовых</span>
                </div>
                <div className="variant-pay num">
                  {money(c.monthly_payment)}
                  <span>/мес</span>
                </div>
              </div>
              {!isCurrent && (
                <div className="variant-foot">
                  <span className="hint num">
                    {diff < 0 ? '−' : '+'}
                    {money(Math.abs(diff))} в месяц · переплата {money(c.estimated_overpayment)}
                  </span>
                  <Button size="sm" variant="white" disabled={locked} title={locked ? 'Шаг «Потребность» подтверждён — нажмите «Редактировать»' : undefined} onClick={() => pick(c)}>
                    Выбрать
                  </Button>
                </div>
              )}
            </div>
          )
        })}
      </div>
    </section>
  )
}

export function AdvisorPanel({ ed }: { ed: Editor }) {
  const qc = useQueryClient()
  const toast = useToast()
  const id = ed.server.id
  const last = useQuery({
    queryKey: ['advisor', id, ed.server.version],
    queryFn: async () => {
      try {
        return await applications.lastAdvisor(id)
      } catch (e) {
        // 404: no report yet; 422: the backend reads reports only after the BKI confirmation.
        if (e instanceof ApiError && (e.status === 404 || e.status === 422)) return null
        throw e
      }
    },
    enabled: !ed.busy && ed.form.bkiAllowed && ed.server.draft_data.confirmations.credit_history_check_allowed,
    placeholderData: (p) => p,
    retry: false,
  })
  const run = useMutation({
    mutationFn: async (mode: AdvisorMode) => {
      await ed.flush()
      return applications.advisor(id, ed.versionRef.current, mode)
    },
    onSuccess: (r) => qc.setQueryData(['advisor', id, ed.server.version], r),
    onError: (e) => toast.error(e, 'AI-разбор не получен'),
  })
  const report: AdvisorReport | null | undefined = run.data && run.data.draft_lock_version === ed.server.version ? run.data : last.data
  const blocked = !ed.form.bkiAllowed

  return (
    <section className="panel violet dots advisor">
      <div className="row between">
        <span className="tag white sm">ИИ-помощник</span>
        <PixelArt shape="smile" size={4} gap={1} color="var(--lime)" animate={false} />
      </div>
      <h3 className="advisor-title">Объясню расчёт и сравню варианты</h3>
      <p className="advisor-sub">Опираюсь только на цифры, посчитанные банком. Решение не принимаю и заявку не меняю.</p>
      <div className="advisor-actions">
        <Button variant="lime" size="sm" loading={run.isPending && run.variables === 'EXPLAIN'} disabled={blocked || run.isPending} onClick={() => run.mutate('EXPLAIN')}>
          Объяснить расчёт
        </Button>
        <Button variant="white" size="sm" loading={run.isPending && run.variables === 'COMPARE'} disabled={blocked || run.isPending} onClick={() => run.mutate('COMPARE')}>
          Сравнить варианты
        </Button>
      </div>
      {blocked && <p className="advisor-lock">Нужно согласие на демо-проверку кредитной истории — оно в шаге «Проверка» и в блоке расчёта.</p>}
      {run.isPending && (
        <div className="advisor-thinking" aria-live="polite">
          <i />
          <i />
          <i />
          <span>Собираю факторы…</span>
        </div>
      )}
      {report && !blocked && !run.isPending && <AdvisorReportView report={{ ...report, is_current: report.is_current && !ed.busy && ed.state !== 'error' && ed.state !== 'conflict' && !last.isPlaceholderData }} />}
    </section>
  )
}

export function AdvisorReportView({ report, light }: { report: AdvisorReport; light?: boolean }) {
  const ex = report.explanation
  return (
    <div className={`advisor-report ${light ? 'light' : ''}`}>
      <div className="row wrap" style={{ gap: 6 }}>
        {report.status === 'SUCCESS' ? <span className="mini ok">модель {report.model_id ?? ''}</span> : <span className="mini">шаблонный разбор{report.error_code ? ` · ${report.error_code}` : ''}</span>}
        {!report.is_current && <span className="mini warn">неактуально — данные изменились</span>}
        <span className="mini">{relative(report.created_at)}</span>
      </div>
      <p className="advisor-summary">{ex.summary.text}</p>
      {ex.comparisons.length > 0 && (
        <div className="advisor-cmp">
          {ex.comparisons.map((c) => {
            const meta = ADVISOR_CANDIDATE[c.candidate_id] ?? { label: c.candidate_id, color: 'var(--ink)' }
            return (
              <div key={c.candidate_id}>
                <span className="variant-tag" style={{ ['--vc' as string]: meta.color }}>
                  {meta.label}
                </span>
                <p>{c.text}</p>
              </div>
            )
          })}
        </div>
      )}
      {ex.next_step?.text && (
        <div className="advisor-next">
          <b>Дальше:</b> {ex.next_step.text}
        </div>
      )}
      <p className="advisor-notice">{ex.notice}</p>
    </div>
  )
}

export function ReadinessCard({ ready, onGo }: { ready: Ready; onGo: (s: FormStep, anchor?: string) => void }) {
  const pct = Math.round((ready.done / ready.items.length) * 100)
  return (
    <section className="card ready">
      <div className="ready-head">
        <div className="ring" style={{ ['--p' as string]: `${pct}%` }}>
          <span className="num">{pct}%</span>
        </div>
        <div>
          <h3 className="card-title">Готовность заявки</h3>
          <p className="hint">Что осталось до отправки</p>
        </div>
      </div>
      <ul className="ready-list">
        {ready.items.map((i) => (
          <li key={i.id} className={i.ok ? 'ok' : ''}>
            <button type="button" onClick={() => onGo(i.step, i.id)} title={i.ok ? 'Готово — открыть поле' : 'Перейти к полю'}>
              <span className="ready-box">{i.ok && <CheckIcon size={11} color="var(--ink)" />}</span>
              <span className="grow">{i.label}</span>
              {!i.ok && !i.blocking && <span className="mini warn">можно позже</span>}
              <span className="ready-go" aria-hidden="true">→</span>
            </button>
          </li>
        ))}
      </ul>
    </section>
  )
}

/** Floating entry point for the AI helper: always one click away, opens a side panel over the page. */
export function AdvisorDock({ ed, open, onOpen, onClose }: { ed: Editor; open: boolean; onOpen: () => void; onClose: () => void }) {
  useEffect(() => {
    if (!open) return
    const h = (e: KeyboardEvent) => e.key === 'Escape' && onClose()
    window.addEventListener('keydown', h)
    return () => window.removeEventListener('keydown', h)
  }, [open, onClose])
  return createPortal(
    <>
      {!open && (
        <button type="button" className="ai-fab" onClick={onOpen} aria-label="Открыть ИИ-помощника">
          <span className="ai-fab-ic">
            <PixelArt shape="smile" size={3} gap={1} color="var(--lime)" animate={false} />
          </span>
          <span className="ai-fab-t">
            <b>ИИ-помощник</b>
            <span>{ed.form.bkiAllowed ? 'объяснит и сравнит' : 'нужно согласие на БКИ'}</span>
          </span>
        </button>
      )}
      {open && (
        <aside className="ai-drawer" role="dialog" aria-label="ИИ-помощник">
          <button type="button" className="ai-close" onClick={onClose} aria-label="Закрыть">
            <svg width="16" height="16" viewBox="0 0 16 16" aria-hidden="true">
              <path d="M3 3l10 10M13 3 3 13" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
            </svg>
          </button>
          <AdvisorPanel ed={ed} />
        </aside>
      )}
    </>,
    document.body,
  )
}
