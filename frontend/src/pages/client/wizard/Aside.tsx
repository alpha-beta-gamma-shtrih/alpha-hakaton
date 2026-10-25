import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { AiDockShell, useClaimAiDock } from '../../../components/AiDock'
import { ApiError } from '../../../api/client'
import { PricingBreakdown } from '../../../components/PricingBreakdown'
import { applications } from '../../../api/endpoints'
import type { AdvisorMode, AdvisorPriority, AdvisorReport, Candidate, FormStep, ScenarioSetUpdate } from '../../../api/types'
import { PixelArt } from '../../../components/pixel'
import { AnimatedNumber, Button, Checkbox, CheckIcon, useToast } from '../../../components/ui'
import { money, months, percent, relative } from '../../../lib/format'
import { clientExplanation } from '../../../lib/clientText'
import { ADVISOR_CANDIDATE, ROUTING } from '../../../lib/labels'
import type { readiness, useDraftEditor } from './useDraftEditor'

type Editor = ReturnType<typeof useDraftEditor>
type Ready = ReturnType<typeof readiness>

const fmtRub = (n: number) => `${Math.round(n).toLocaleString('ru-RU')} ₽`
const PRIORITIES: Record<AdvisorPriority, string> = {
  BALANCED: 'Без предпочтения — покажите компромиссы',
  KEEP_AMOUNT: 'Сохранить нужную сумму',
  LOWER_PAYMENT: 'Снизить ежемесячный платёж',
  LOWER_OVERPAYMENT: 'Снизить общую переплату',
}

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
  const qc = useQueryClient()
  const toast = useToast()
  const id = ed.server.id
  const canCreate = !ed.busy && ed.state !== 'conflict' && ed.state !== 'error' && !scen.isPlaceholderData && scen.data?.application_version === ed.server.version
  const cache = (result: ScenarioSetUpdate) => {
    for (const ready of [true, false]) qc.setQueryData(['scenario-set', id, result.application.version, ready], result.scenario_set)
  }
  const options = useQuery({
    queryKey: ['scenario-set', id, ed.server.version, canCreate],
    enabled: !ed.busy,
    queryFn: async () => {
      const saved = await applications.scenarioSet(id)
      if (saved || !canCreate) return saved
      const result = await ed.command((version) => applications.createScenarioSet(id, version))
      cache(result)
      return result.scenario_set
    },
    placeholderData: (previous) => previous,
    staleTime: Infinity,
    retry: false,
  })
  const mutate = useMutation({
    mutationFn: (candidate: Candidate['candidate_id'] | null) => ed.command((version) => candidate && options.data
      ? applications.selectScenario(id, version, options.data.id, candidate)
      : applications.createScenarioSet(id, version, true)),
    onSuccess: cache,
    onError: (error) => {
      toast.error(error, 'Не удалось сохранить вариант')
      void qc.invalidateQueries({ queryKey: ['scenario-set', id] })
    },
  })
  const saved = options.data
  const fresh = !!saved && saved.is_current && saved.application_version === ed.server.version && !options.isPlaceholderData
  const busy = ed.busy || mutate.isPending || options.isFetching
  const blocked = busy || ed.state === 'conflict' || ed.state === 'error'
  // Never retain credit-derived calculations in the UI after consent is withdrawn,
  // including the brief interval before the refreshed server response arrives.
  const cands = saved && (ed.form.bkiAllowed || saved.mode === 'CALCULATION_ONLY') ? saved.candidates : []
  if (!saved && !canCreate && !options.error) return null
  const base = cands.find((c) => c.candidate_id === 'REQUESTED')
  return (
    <section className="card variants">
      <div className="card-head" style={{ marginBottom: 12 }}>
        <div>
          <h3 className="card-title">Варианты финансирования</h3>
          <span className="hint">набор сохраняется; выбор меняет только условия заявки</span>
        </div>
        {onAskAi && (
          <button type="button" className="ask-ai" onClick={onAskAi} disabled={!fresh || blocked}>
            Спросить ИИ
          </button>
        )}
      </div>
      {saved && !saved.is_current && <p className="hint" role="status">{saved.stale_reason} Сохранённые карточки ниже не применяются до обновления.</p>}
      {options.error && <p className="calc-err" role="alert">{options.error instanceof ApiError ? options.error.message : 'Варианты недоступны'}</p>}
      {locked && <p className="hint">Для выбора другого варианта откройте «Потребность» и нажмите «Редактировать».</p>}
      {!ed.form.bkiAllowed && saved?.mode === 'PREVIEW' && <p className="hint">Прежняя оценка скрыта: согласие на проверку истории отозвано.</p>}
      <div style={{ marginBottom: 16 }}>
        <Button size="sm" variant="white" disabled={!canCreate || blocked} onClick={() => mutate.mutate(null)}>
          {saved ? 'Обновить варианты' : 'Рассчитать варианты'}
        </Button>
        {saved && <p className="hint" style={{ marginTop: 8 }}>Обновление построит новый набор от текущей суммы и срока. Переключение карточек набор не меняет.</p>}
      </div>
      <div className="stack">
        {cands.map((c) => {
          const meta = ADVISOR_CANDIDATE[c.candidate_id]
          const diff = Number(c.monthly_payment) - Number(base?.monthly_payment ?? c.monthly_payment)
          const isCurrent = fresh && saved?.selected_candidate_id === c.candidate_id
          return (
            <div key={c.candidate_id} className={`variant ${isCurrent ? 'cur' : ''}`} style={{ ['--vc' as string]: meta.color }}>
              <div className="variant-top">
                <span className="variant-tag">{meta.label}</span>
                {fresh && c.preliminary_route && <span className={`route sm r-${c.preliminary_route}`}>{ROUTING[c.preliminary_route]}</span>}
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
              <div className="variant-foot">
                {c.candidate_id !== 'REQUESTED' ? (
                  <span className="hint num">
                    {diff < 0 ? '−' : '+'}
                    {money(Math.abs(diff))} в месяц к исходному запросу · переплата {money(c.estimated_overpayment)}
                  </span>
                ) : <span className="hint">Сохранённая отправная точка сравнения</span>}
                  <Button size="sm" variant="white" disabled={locked || blocked || !fresh || isCurrent} title={locked ? 'Шаг «Потребность» подтверждён — нажмите «Редактировать»' : undefined} onClick={() => mutate.mutate(c.candidate_id)}>
                    {isCurrent ? 'Выбран' : 'Выбрать'}
                  </Button>
                </div>
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
  const [choice, setChoice] = useState<{ id: string; priority: AdvisorPriority } | null>(null)
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
  const priority = choice?.id === id ? choice.priority : last.data?.priority ?? 'BALANCED'
  const run = useMutation({
    mutationFn: async ({ mode, priority }: { mode: AdvisorMode; priority: AdvisorPriority }) => {
      await ed.flush()
      return applications.advisor(id, ed.versionRef.current, mode, priority)
    },
    onSuccess: (r) => qc.setQueryData(['advisor', id, ed.versionRef.current], r),
    onError: (e) => toast.error(e, 'AI-разбор не получен'),
  })
  const report = last.data
  const blocked = !ed.form.bkiAllowed

  return (
    <section className="panel violet dots advisor">
      <div className="row between">
        <span className="tag white sm">ИИ-помощник</span>
        <PixelArt shape="smile" size={4} gap={1} color="var(--lime)" animate={false} />
      </div>
      <h3 className="advisor-title">Объясню расчёт и сравню варианты</h3>
      <p className="advisor-sub">Опираюсь только на цифры, посчитанные банком. Решение не принимаю и заявку не меняю.</p>
      <label className="advisor-priority">
        <span>Что важнее при сравнении?</span>
        <select value={priority} disabled={run.isPending} onChange={(e) => setChoice({ id, priority: e.target.value as AdvisorPriority })}>
          {Object.entries(PRIORITIES).map(([value, title]) => <option value={value} key={value}>{title}</option>)}
        </select>
      </label>
      <p className="advisor-sub">Выбор приоритета не вызывает модель. Нажмите «Сравнить варианты», чтобы получить разбор.</p>
      <div className="advisor-actions">
        <Button variant="lime" size="sm" loading={run.isPending && run.variables?.mode === 'EXPLAIN'} disabled={blocked || run.isPending} onClick={() => run.mutate({ mode: 'EXPLAIN', priority: 'BALANCED' })}>
          Объяснить расчёт
        </Button>
        <Button variant="white" size="sm" loading={run.isPending && run.variables?.mode === 'COMPARE'} disabled={blocked || run.isPending} onClick={() => run.mutate({ mode: 'COMPARE', priority })}>
          Сравнить варианты
        </Button>
      </div>
      {blocked && <p className="advisor-lock">Нужно согласие на демо-проверку кредитной истории — оно в шаге «Проверка» и в блоке расчёта.</p>}
      {run.isPending && (
        <div className="advisor-thinking" aria-live="polite">
          <i />
          <i />
          <i />
          <span>Объясняю пользу и компромиссы…</span>
        </div>
      )}
      {report?.mode === 'COMPARE' && report.priority !== priority && !run.isPending && <p className="advisor-lock" role="status">Ниже разбор для другого приоритета. Нажмите «Сравнить варианты» для выбранного.</p>}
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
      {report.mode === 'COMPARE' && <p className="hint">Приоритет разбора: {PRIORITIES[report.priority ?? 'BALANCED']}. {report.preferred_candidate_ids?.length
        ? `По демо-правилам и этому критерию: ${report.preferred_candidate_ids.map((id) => ADVISOR_CANDIDATE[id as Candidate['candidate_id']]?.label ?? id).join(', ')}. Выбор остаётся за вами.`
        : 'Победитель не выбран: сравнение условное, проверьте ограничения каждого варианта.'}</p>}
      <p className="advisor-summary">{clientExplanation(ex.summary.text)}</p>
      {ex.comparisons.length > 0 && (
        <div className="advisor-cmp">
          {ex.comparisons.map((c) => {
            const meta = ADVISOR_CANDIDATE[c.candidate_id] ?? { label: c.candidate_id, color: 'var(--ink)' }
            return (
              <div key={c.candidate_id}>
                <span className="variant-tag" style={{ ['--vc' as string]: meta.color }}>
                  {meta.label}
                </span>
                <p>{clientExplanation(c.text)}</p>
              </div>
            )
          })}
        </div>
      )}
      {ex.next_step?.text && (
        <div className="advisor-next">
          <b>Дальше:</b> {clientExplanation(ex.next_step.text)}
        </div>
      )}
      <p className="advisor-notice">{clientExplanation(ex.notice)}</p>
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
  useClaimAiDock()
  return (
    <AiDockShell open={open} onOpen={onOpen} onClose={onClose} subtitle={ed.form.bkiAllowed ? 'объяснит и сравнит' : 'нужно согласие на БКИ'}>
      <AdvisorPanel ed={ed} />
    </AiDockShell>
  )
}
