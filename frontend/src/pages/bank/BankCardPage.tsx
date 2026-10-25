import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { PricingBreakdown } from '../../components/PricingBreakdown'
import { FinTable } from '../../components/FinTable'
import { Fragment, useMemo, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { ApiError } from '../../api/client'
import { bank } from '../../api/endpoints'
import type { BankAssessment, BankCard, BankCheck, RequestableField } from '../../api/types'
import { PixelArt } from '../../components/pixel'
import { Arrow, Button, Checkbox, ErrorNotice, Modal, Notice, PageLoader, ProvenanceBadge, Reasons, RiskMeter, SectionTitle, Skeleton, StatusChip, Tabs, useToast } from '../../components/ui'
import { date, dateTime, money, moneyShort, monthShort, months, percent, shortId } from '../../lib/format'
import { CHECK_SOURCE, CHECK_STATUS, FIN_FIELDS, LEGAL_FORM, PURPOSE, requestedFieldLabel, RISK, ROUTING } from '../../lib/labels'
import { DocumentsCard } from '../client/wizard/steps'
import { AdvisorReportView } from '../client/wizard/Aside'
import { Timeline } from '../client/StatusView'
import { AdjustedOfferModal } from './AdjustedOfferModal'
import { OfferComparison } from '../../components/OfferComparison'

type Tab = 'assess' | 'checks' | 'data' | 'requests' | 'history' | 'versions' | 'docs' | 'ai'

export function BankCardPage() {
  const { id = '' } = useParams()
  const qc = useQueryClient()
  const toast = useToast()
  const card = useQuery({ queryKey: ['bank-card', id], queryFn: () => bank.card(id), refetchInterval: 15_000 })
  const [tab, setTab] = useState<Tab>('assess')
  const [modal, setModal] = useState<null | 'info' | 'APPROVED' | 'REJECTED' | 'offer'>(null)
  const [conflict, setConflict] = useState(false)

  const onDone = (c: BankCard, msg: string) => {
    qc.setQueryData(['bank-card', id], c)
    qc.invalidateQueries({ queryKey: ['bank-queue'] })
    qc.invalidateQueries({ queryKey: ['bank-events', id] })
    setModal(null)
    setConflict(false)
    toast.push({ tone: 'ok', title: msg })
  }
  const onFail = (e: unknown) => {
    if (e instanceof ApiError && e.status === 409) {
      setConflict(true)
      setModal(null)
      card.refetch()
    }
    toast.error(e, 'Действие не выполнено')
  }

  const retry = useMutation({
    mutationFn: () => bank.retry(id, card.data!.version),
    onSuccess: async () => {
      const c = await card.refetch()
      if (c.data) onDone(c.data, 'Обработка повторена')
    },
    onError: onFail,
  })

  if (card.isLoading) return <PageLoader />
  if (card.error || !card.data)
    return (
      <div className="page">
        <Link to="/bank" className="back">
          <Arrow dir="left" /> Очередь
        </Link>
        <div style={{ marginTop: 20 }}>
          <ErrorNotice error={card.error} onRetry={() => card.refetch()} />
        </div>
      </div>
    )

  const c = card.data
  const a = c.assessment
  const acts = c.allowed_actions

  return (
    <div className="page">
      <div className="wz-head">
        <div>
          <Link to={c.status === 'APPROVED' || c.status === 'REJECTED' || c.status === 'SIGNED' ? '/bank/decisions' : '/bank'} className="back">
            <Arrow dir="left" /> {c.status === 'APPROVED' || c.status === 'REJECTED' || c.status === 'SIGNED' ? 'Решения' : 'Очередь'}
          </Link>
          <h1 className="page-title" style={{ fontSize: 'clamp(26px,3.6vw,42px)' }}>
            {c.company_name}
          </h1>
          <div className="row wrap" style={{ marginTop: 12 }}>
            <StatusChip status={c.status} />
            <span className="hint mono">№ {shortId(c.id)}</span>
            <span className="hint">
              отправка {c.latest_revision_no} · {dateTime(c.submitted_at)}
            </span>
            <span className="hint">ИНН {c.inn}</span>
          </div>
        </div>
      </div>

      {conflict && (
        <div style={{ marginBottom: 16 }}>
          <Notice tone="warn" title="Заявка изменилась, пока вы работали">
            Карточка обновлена до актуальной версии. Проверьте данные и повторите действие, если оно всё ещё нужно.
          </Notice>
        </div>
      )}

      <div className="bc-top">
        <section className="panel ink dots bc-hero">
          <div className="bc-hero-grid">
            <div>
              <span className="lbl">Запрошено</span>
              <div className="bc-amount display num">{money(c.requested_amount)}</div>
              <div className="bc-sub">
                {months(c.term_months)} · {PURPOSE[c.purpose_code].label}
              </div>
            </div>
            <div className="bc-risk">
              <span className="lbl">Оценка исходного запроса</span>
              <RiskMeter score={c.risk_score} band={c.risk_band} />
              {a && <span className={`route r-${a.routing}`}>{ROUTING[a.routing]}</span>}
            </div>
          </div>
          {c.assessment_reasons.length > 0 && (
            <div className="bc-reasons">
              {c.assessment_reasons.map((r) => (
                <span key={r.code} title={r.message}>
                  <code>{r.code}</code> {r.message}
                </span>
              ))}
            </div>
          )}
        </section>

        <section className="card bc-actions">
          {c.decline && <Notice tone="warn" title="Клиент отказался от условий">Заявка закрыта без подписания {dateTime(c.decline.declined_at)} · {c.decline.declined_by_display_name}. Решение банка ниже сохранено для истории.</Notice>}
          {c.signature && <Notice tone="ok">Демо-документ подписан {dateTime(c.signature.signed_at)} · {c.signature.signed_by_display_name}. Выдача средств не выполнялась.</Notice>}
          <h3 className="card-title">Действия</h3>
          {acts.length === 0 ? (
            <p className="muted" style={{ marginTop: 10 }}>
              {c.status === 'NEEDS_INFO'
                ? 'Ждём ответа клиента. После новой отправки заявка вернётся в очередь.'
                : c.status === 'APPROVED' || c.status === 'REJECTED' || c.status === 'SIGNED'
                  ? 'Заявка завершена. Новое решение по ней не принимается.'
                  : 'Сейчас действий сотрудника не требуется.'}
            </p>
          ) : (
            <div className="stack" style={{ marginTop: 14 }}>
              {acts.includes('APPROVE') && (
                <Button variant="lime" block onClick={() => setModal('APPROVED')}>
                  Одобрить
                </Button>
              )}
              {acts.includes('REJECT') && (
                <Button variant="red" block onClick={() => setModal('REJECTED')}>
                  Отказать
                </Button>
              )}
              {acts.includes('APPROVE') && <Button variant="violet" block onClick={() => setModal('offer')}>Изменить условия</Button>}
              {acts.includes('REQUEST_INFO') && (
                <Button variant="white" block onClick={() => setModal('info')}>
                  Запросить уточнение
                </Button>
              )}
              {acts.includes('RETRY_PROCESSING') && (
                <Button variant="blue" block loading={retry.isPending} onClick={() => retry.mutate()}>
                  Повторить обработку
                </Button>
              )}
            </div>
          )}
          {c.decision && (
            <div className={`bc-decision ${c.decision.outcome === 'APPROVED' ? 'ok' : 'no'}`}>
              <div className="row between">
                <b>{c.decision.outcome === 'APPROVED' ? 'Одобрено' : 'Отказано'}</b>
                <span className="mini">{c.decision.source === 'MANUAL' ? 'вручную' : 'автоматически'}</span>
              </div>
              {c.decision.outcome === 'APPROVED' && (
                <div className="hint" style={{ marginTop: 6 }}>
                  {money(c.decision.approved_amount)} · {months(c.decision.approved_term_months)} · платёж {money(c.decision.monthly_payment)}
                </div>
              )}
              <p style={{ marginTop: 8 }}>{c.decision.public_explanation}</p>
              {c.decision.internal_comment && (
                <p className="bc-internal">
                  <b>Внутренний комментарий:</b> {c.decision.internal_comment}
                </p>
              )}
              <span className="hint">{dateTime(c.decision.created_at)}</span>
            </div>
          )}
          {c.decision?.offer && <>
            <OfferComparison terms={c.decision.offer} />
            <p className="label">Оценка предложения банка</p>
            <RiskMeter score={c.decision.offer_risk_score ?? null} band={c.decision.offer_risk_band ?? 'UNKNOWN'} />
          </>}
        </section>
      </div>

      <Tabs<Tab>
        value={tab}
        onChange={setTab}
        items={[
          { id: 'assess', label: 'Оценка' },
          { id: 'checks', label: 'Проверки' },
          { id: 'data', label: 'Данные заявки' },
          { id: 'requests', label: `Дозапросы${c.information_requests.length ? ` · ${c.information_requests.length}` : ''}` },
          { id: 'history', label: 'История' },
          { id: 'versions', label: `Версии · ${c.revisions.length}` },
          { id: 'docs', label: 'Документы' },
          { id: 'ai', label: 'AI-разбор' },
        ]}
      />

      <div key={tab} className="rise">
        {tab === 'assess' && (a ? <AssessmentPanel a={a} productSnapshot={c.revision.product_snapshot} /> : <Notice tone="warn" title="Оценки нет">Обработка не завершилась. Доступен повтор обработки.</Notice>)}
        {tab === 'checks' && (a ? <ChecksPanel checks={a.checks} /> : <Notice tone="plain">Проверки не выполнялись.</Notice>)}
        {tab === 'data' && <DataPanel c={c} />}
        {tab === 'requests' && <RequestsPanel c={c} />}
        {tab === 'history' && <HistoryPanel id={id} />}
        {tab === 'versions' && <VersionsPanel c={c} />}
        {tab === 'docs' && <DocumentsCard docs={c.revision.document_refs} title={`Документы отправки ${c.revision.revision_no}`} />}
        {tab === 'ai' && <AiPanel id={id} />}
      </div>

      <InfoRequestModal open={modal === 'info'} c={c} onClose={() => setModal(null)} onDone={onDone} onFail={onFail} />
      {modal === 'offer' && <AdjustedOfferModal key={`${c.id}:${c.version}`} c={c} onClose={() => setModal(null)} onDone={onDone} onFail={onFail} />}
      <DecisionModal outcome={modal === 'APPROVED' || modal === 'REJECTED' ? modal : null} c={c} onClose={() => setModal(null)} onDone={onDone} onFail={onFail} />
    </div>
  )
}

/* ---------------- panels ---------------- */
function AssessmentPanel({ a, productSnapshot }: { a: BankAssessment; productSnapshot: Record<string, unknown> }) {
  const cd = a.calculation_details as Record<string, unknown>
  const factors = (cd.factors as { factor_id: string; points: number; value: string }[] | undefined) ?? []
  const rows: [string, string][] = [
    ['Платёж по новому кредиту', money(cd.monthly_payment as string, { kopecks: true })],
    ['Текущие платежи (заявлено)', money(cd.declared_current_payment as string, { kopecks: true })],
    ['Текущие платежи (БКИ)', money(cd.confirmed_current_payment as string, { kopecks: true })],
    ['Учтено в нагрузке', money(cd.existing_payment as string, { kopecks: true })],
    ['Средний операционный поток', money(cd.average_operating_cashflow as string, { kopecks: true })],
    ['Долговая нагрузка', percent(cd.load_ratio as string, 2)],
    ['Динамика поступлений', cd.inflow_trend !== undefined ? percent(cd.inflow_trend as string, 1) : '—'],
    ['Возраст бизнеса', cd.business_age_months !== undefined ? `${cd.business_age_months} мес` : '—'],
    ['Переплата', money(cd.estimated_overpayment as string, { kopecks: true })],
  ]
  const ps = productSnapshot as { min_amount?: string; max_amount?: string; min_term_months?: number; max_term_months?: number; annual_rate_percent?: string; policy_config?: { maximum_load_ratio?: string; approve_max_score?: number; manual_review_max_score?: number } }
  const pc = ps.policy_config
  return (
    <div className="bc-grid">
      <div className="card">
        <SectionTitle n="01" aside={<span className="hint">{a.rules_version} · запуск {a.run_no}</span>}>
          Расчёт
        </SectionTitle>
        <dl className="kv">
          {rows.map(([k, v]) => (
            <Fragment key={k}>
              <dt>{k}</dt>
              <dd className="num">{v}</dd>
            </Fragment>
          ))}
        </dl>
        <PricingBreakdown value={cd.pricing} />
      </div>
      <div className="stack-lg">
        <div className="card">
          <SectionTitle n="02" color="red">
            Факторы риска
          </SectionTitle>
          {factors.length === 0 ? (
            <p className="muted">Баллы не начислены{a.risk_score === null ? ' — оценка не выполнялась.' : '.'}</p>
          ) : (
            <div className="factors">
              {factors.map((f) => (
                <div key={f.factor_id} className="factor-bar">
                  <div className="row between">
                    <code>{f.factor_id}</code>
                    <b className="num">+{f.points}</b>
                  </div>
                  <div className="meter">
                    <i style={{ width: `${f.points}%`, background: f.points >= 40 ? 'var(--red)' : f.points >= 20 ? 'var(--amber)' : 'var(--lime)' }} />
                  </div>
                </div>
              ))}
              <div className="factor-total">
                <span>Итого</span>
                <b className="num">{a.risk_score ?? '—'}</b>
                <span className="hint">{RISK[a.risk_band].label}</span>
              </div>
            </div>
          )}
          <div style={{ marginTop: 16 }}>
            <Reasons items={a.reasons} />
          </div>
        </div>
        {pc && (
          <div className="card">
            <SectionTitle n="03" color="violet">
              Ограничения продукта
            </SectionTitle>
            <div className="limits">
              <span>
                Сумма <b>{money(ps.min_amount)} — {money(ps.max_amount)}</b>
              </span>
              <span>
                Срок <b>{ps.min_term_months}–{ps.max_term_months} мес</b>
              </span>
              <span>
                Базовая ставка <b>{Number(ps.annual_rate_percent)}%</b>
              </span>
              <span>
                Нагрузка ≤ <b>{percent(pc.maximum_load_ratio, 0)}</b>
              </span>
              <span>
                Авто-одобрение ≤ <b>{pc.approve_max_score}</b> баллов
              </span>
              <span>
                Ручной разбор ≤ <b>{pc.manual_review_max_score}</b> баллов
              </span>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}

const ND_LABELS: Record<string, string> = {
  inn: 'ИНН',
  legal_form: 'Форма',
  registered_on: 'Дата регистрации',
  registry_status: 'Статус в реестре',
  is_bankrupt: 'Банкротство',
  history_present: 'История есть',
  current_monthly_payment: 'Текущий платёж',
  current_overdue_amount: 'Текущая просрочка',
  max_overdue_days_12m: 'Макс. просрочка за 12 мес, дн.',
  financial_month_count: 'Месяцев в отправке',
  missing_fields: 'Пустых значений',
}

function ndValue(k: string, v: unknown) {
  if (k === 'is_bankrupt') return v === true ? 'да' : v === false ? 'нет' : 'неизвестно'
  if (typeof v === 'boolean') return v ? 'да' : 'нет'
  if (k === 'legal_form') return LEGAL_FORM[String(v)] ?? String(v)
  if (k === 'registered_on') return date(String(v))
  if (typeof v === 'string' && /^\d+\.\d{2}$/.test(v)) return money(v, { kopecks: true })
  if (v === null || v === undefined) return '—'
  return String(v)
}

function ChecksPanel({ checks }: { checks: BankCheck[] }) {
  return (
    <div className="grid grid-3">
      {checks.map((ch) => {
        const st = CHECK_STATUS[ch.status]
        const nd = (ch.normalized_data ?? {}) as Record<string, unknown>
        const prov = nd.provenance as { source: 'MOCK_FNS'; as_of_date: string; checked_at: string } | undefined
        return (
          <div key={ch.source} className={`card bc-check t-${st.tone}`}>
            <div className="row between">
              <span className="tag sm outline">{ch.source}</span>
              <span className={`mini ${st.tone === 'ok' ? 'ok' : st.tone === 'warn' ? 'warn' : 'err'}`}>{st.label}</span>
            </div>
            <h3 className="card-title" style={{ margin: '14px 0 4px' }}>
              {CHECK_SOURCE[ch.source].label}
            </h3>
            <p className="hint">{CHECK_SOURCE[ch.source].desc}</p>
            <dl className="kv sm" style={{ marginTop: 14 }}>
              {Object.entries(nd)
                .filter(([k]) => k !== 'provenance')
                .map(([k, v]) => (
                  <Fragment key={k}>
                    <dt>{ND_LABELS[k] ?? k}</dt>
                    <dd className={k === 'is_bankrupt' && v !== false ? 'bad' : ''}>{ndValue(k, v)}</dd>
                  </Fragment>
                ))}
            </dl>
            {ch.error_code && <Notice tone="error" title={ch.error_code} />}
            {ch.reasons.length > 0 && (
              <div style={{ marginTop: 12 }}>
                <Reasons items={ch.reasons} />
              </div>
            )}
            <div className="bc-check-foot">
              {prov && <ProvenanceBadge item={prov} />}
              <span className="hint">
                {ch.source_version} · {dateTime(ch.completed_at)}
              </span>
            </div>
          </div>
        )
      })}
    </div>
  )
}

function DataPanel({ c }: { c: BankCard }) {
  const cs = c.revision.company_snapshot as Record<string, string | null>
  const fs = c.revision.financial_snapshot as { purchase_from_bank_partner?: boolean; financial_months?: { month: string; cash_inflow: string | null; operating_outflow: string | null; existing_debt_payment: string | null }[]; confirmations?: { data_confirmed: boolean; credit_history_check_allowed: boolean }; info_response?: string | null; purpose_details?: string | null; provenance?: { financial_months?: { source: 'DEMO_PROFILE'; as_of_date: string; checked_at: string | null } } }
  return (
    <div className="bc-grid">
      <div className="card">
        <SectionTitle n="01" aside={<span className="hint">снимок отправки {c.revision.revision_no}</span>}>
          Компания
        </SectionTitle>
        <dl className="kv">
          <dt>Наименование</dt>
          <dd>{cs.legal_name}</dd>
          <dt>Форма</dt>
          <dd>{LEGAL_FORM[cs.legal_form ?? ''] ?? cs.legal_form}</dd>
          <dt>ИНН</dt>
          <dd className="num">{cs.inn}</dd>
          <dt>ОГРН</dt>
          <dd className="num">{cs.registration_number ?? '—'}</dd>
          <dt>Регистрация</dt>
          <dd>{date(cs.registered_on)}</dd>
          <dt>ОКВЭД</dt>
          <dd>{cs.okved_code}</dd>
          <dt>Регион</dt>
          <dd>{cs.region_code}</dd>
        </dl>
        <div className="divider" />
        <dl className="kv">
          <dt>Цель</dt>
          <dd>{PURPOSE[c.revision.purpose_code].label}</dd>
          <dt>Партнёрская покупка · DEMO</dt><dd>{fs.purchase_from_bank_partner ? 'Заявлено клиентом, не проверено' : 'Не заявлена'}</dd>
          <dt>Описание цели</dt>
          <dd>{fs.purpose_details || '—'}</dd>
          <dt>Подтверждение данных</dt>
          <dd>{fs.confirmations?.data_confirmed ? 'да' : 'нет'}</dd>
          <dt>Согласие на БКИ</dt>
          <dd>{fs.confirmations?.credit_history_check_allowed ? 'да' : 'нет'}</dd>
          <dt>Ответ клиента</dt>
          <dd>{fs.info_response || '—'}</dd>
          <dt>Хэш снимка</dt>
          <dd className="mono hint">{c.revision.input_hash.slice(0, 16)}…</dd>
        </dl>
      </div>
      <div className="card">
        <SectionTitle n="02" color="red" aside={<ProvenanceBadge item={fs.provenance?.financial_months} />}>
          Финансы из отправки
        </SectionTitle>
        <FinTable rows={fs.financial_months ?? []} missingLabel="нет" />
        <p className="hint" style={{ marginTop: 12 }}>
          Сотрудник видит только отправленный снимок. Неотправленные правки клиента сюда не попадают.
        </p>
      </div>
    </div>
  )
}

function RequestsPanel({ c }: { c: BankCard }) {
  if (!c.information_requests.length) return <Notice tone="plain">Дозапросов по заявке не было.</Notice>
  return (
    <div className="stack">
      {[...c.information_requests].reverse().map((r) => (
        <div key={r.id} className="card">
          <div className="row between wrap">
            <div className="row">
              <span className={`mini ${r.status === 'OPEN' ? 'warn' : 'ok'}`}>{r.status === 'OPEN' ? 'ждёт ответа' : 'отвечен'}</span>
              <span className="hint">{r.created_by_user_id ? 'сотрудник' : 'автоматически'} · {dateTime(r.created_at)}</span>
            </div>
          </div>
          <p style={{ margin: '12px 0', fontWeight: 600 }}>{r.message_to_client}</p>
          <div className="row wrap" style={{ gap: 6 }}>
            {r.requested_fields.map((f) => (
              <span key={f} className="field-pill static light">
                {requestedFieldLabel(f)}
              </span>
            ))}
          </div>
          {r.status === 'ANSWERED' && (
            <div className="answer">
              <b>Ответ клиента</b> · {dateTime(r.answered_at)}
              <p>{r.answer_text || 'Клиент исправил поля без комментария.'}</p>
            </div>
          )}
        </div>
      ))}
    </div>
  )
}

function HistoryPanel({ id }: { id: string }) {
  const ev = useQuery({ queryKey: ['bank-events', id], queryFn: () => bank.events(id) })
  return <div className="card">{ev.data ? <Timeline items={ev.data.items} /> : <Skeleton h={200} />}</div>
}

function VersionsPanel({ c }: { c: BankCard }) {
  const [no, setNo] = useState(c.latest_revision_no)
  const detail = useQuery({ queryKey: ['bank-rev', c.id, no], queryFn: () => bank.revision(c.id, no), staleTime: Infinity })
  return (
    <div className="bc-grid versions">
      <div className="card">
        <SectionTitle n="01">Отправки</SectionTitle>
        <div className="stack">
          {[...c.revisions].reverse().map((r) => (
            <button key={r.id} className={`ver ${no === r.revision_no ? 'on' : ''}`} onClick={() => setNo(r.revision_no)}>
              <span className="display">{r.revision_no}</span>
              <span className="grow">
                <b>Отправка {r.revision_no}</b>
                <span className="hint">{dateTime(r.created_at)}</span>
              </span>
              {r.revision_no === c.latest_revision_no && <span className="mini ok">актуальная</span>}
            </button>
          ))}
        </div>
      </div>
      <div className="card">
        {detail.isLoading ? (
          <Skeleton h={220} />
        ) : detail.data ? (
          <>
            <SectionTitle n="02" color="violet" aside={<span className="hint mono">{detail.data.revision.input_hash.slice(0, 12)}…</span>}>
              Снимок {detail.data.revision.revision_no}
            </SectionTitle>
            <div className="review-grid">
              <div className="review-item accent">
                <span>Сумма</span>
                <b className="num">{money(detail.data.revision.requested_amount)}</b>
              </div>
              <div className="review-item accent">
                <span>Срок</span>
                <b>{months(detail.data.revision.term_months)}</b>
              </div>
              <div className="review-item">
                <span>Цель</span>
                <b>{PURPOSE[detail.data.revision.purpose_code].label}</b>
              </div>
            </div>
            <h4 className="sub-h">Запуски оценки</h4>
            <div className="stack">
              {detail.data.assessments.map((as) => (
                <div key={as.id} className="run">
                  <span className="nb ink">#{as.run_no}</span>
                  <RiskMeter score={as.risk_score} band={as.risk_band} compact />
                  <span className={`route sm r-${as.routing}`}>{ROUTING[as.routing]}</span>
                  <span className="hint grow" style={{ textAlign: 'right' }}>
                    {dateTime(as.completed_at)}
                  </span>
                </div>
              ))}
              {!detail.data.assessments.length && <p className="muted">Оценок для этой отправки нет.</p>}
            </div>
          </>
        ) : (
          <ErrorNotice error={detail.error} />
        )}
      </div>
    </div>
  )
}

function AiPanel({ id }: { id: string }) {
  const q = useQuery({
    queryKey: ['bank-ai', id],
    queryFn: async () => {
      try {
        return await bank.advisor(id)
      } catch (e) {
        if (e instanceof ApiError && e.status === 404) return null
        throw e
      }
    },
  })
  if (q.isLoading) return <Skeleton h={160} r={22} />
  if (q.error) return <ErrorNotice error={q.error} />
  if (!q.data)
    return (
      <div className="card empty">
        <PixelArt shape="smile" size={8} color="var(--line-2)" />
        <b style={{ color: 'var(--ink)' }}>AI-разбора по этой отправке нет</b>
        <span>Разбор вспомогательный: он объясняет факторы и не влияет на решение.</span>
      </div>
    )
  return (
    <div className="card">
      <SectionTitle n="AI" color="violet">
        Разбор по отправке
      </SectionTitle>
      <AdvisorReportView report={q.data} light />
    </div>
  )
}

/* ---------------- modals ---------------- */
const BASE_FIELDS: { f: RequestableField; label: string; value: (c: BankCard) => string }[] = [
  { f: 'requested_amount', label: 'Сумма', value: (c) => money(c.revision.requested_amount) },
  { f: 'term_months', label: 'Срок', value: (c) => months(c.revision.term_months) },
  { f: 'purpose_code', label: 'Цель', value: (c) => PURPOSE[c.revision.purpose_code].label },
  { f: 'purpose_details', label: 'Описание цели', value: (c) => ((c.revision.financial_snapshot as { purpose_details?: string | null }).purpose_details ? 'есть' : 'пусто') },
  { f: 'draft_data.info_response', label: 'Пояснение клиента', value: (c) => ((c.revision.financial_snapshot as { info_response?: string | null }).info_response ? 'есть' : 'пусто') },
]

type SnapMonth = { month: string; cash_inflow: string | null; operating_outflow: string | null; existing_debt_payment: string | null }

function InfoRequestModal({ open, c, onClose, onDone, onFail }: { open: boolean; c: BankCard; onClose: () => void; onDone: (c: BankCard, m: string) => void; onFail: (e: unknown) => void }) {
  const [msg, setMsg] = useState('')
  const [fields, setFields] = useState<Set<RequestableField>>(new Set())
  const snapMonths = useMemo(() => (c.revision.financial_snapshot as { financial_months?: SnapMonth[] }).financial_months ?? [], [c])
  const path = (mo: string, k: string) => `draft_data.financial_months.${mo}.${k}` as RequestableField
  const toggle = (f: RequestableField) =>
    setFields((s) => {
      const n = new Set(s)
      if (n.has(f)) n.delete(f)
      else n.add(f)
      n.delete('draft_data.financial_months')
      return n
    })
  const allFin = fields.has('draft_data.financial_months')
  const setAllFin = () =>
    setFields((s) => {
      const n = new Set([...s].filter((f) => !f.startsWith('draft_data.financial_months')))
      if (!allFin) n.add('draft_data.financial_months')
      return n
    })
  const rowState = (k: string) => {
    const sel = snapMonths.filter((m) => fields.has(path(m.month, k))).length
    return sel === 0 ? 'none' : sel === snapMonths.length ? 'all' : 'some'
  }
  const toggleRow = (k: string) =>
    setFields((s) => {
      const n = new Set(s)
      n.delete('draft_data.financial_months')
      const all = snapMonths.every((m) => n.has(path(m.month, k)))
      snapMonths.forEach((m) => (all ? n.delete(path(m.month, k)) : n.add(path(m.month, k))))
      return n
    })
  const m = useMutation({
    mutationFn: () => bank.requestInfo(c.id, { expected_version: c.version, message_to_client: msg.trim(), requested_fields: [...fields] }),
    onSuccess: (card) => {
      setMsg('')
      setFields(new Set())
      onDone(card, 'Запрос отправлен клиенту')
    },
    onError: onFail,
  })
  const len = msg.trim().length
  const selectedLabels = allFin ? ['Все финансовые показатели'] : []
  const count = fields.size

  return (
    <Modal open={open} onClose={onClose} width={760}>
      <span className="tag violet">Дозапрос</span>
      <h3 style={{ marginTop: 14 }}>Что уточнить у клиента?</h3>
      <p className="muted">Клиент увидит сообщение, а выбранные поля подсветятся в его форме. Заявка перейдёт в статус «Нужны уточнения».</p>

      <div className="field" style={{ marginTop: 18 }}>
        <label htmlFor="ir-msg">Сообщение клиенту</label>
        <textarea id="ir-msg" className={`textarea ${len > 0 && len < 20 ? 'invalid' : ''}`} maxLength={1000} value={msg} onChange={(e) => setMsg(e.target.value)} placeholder="Например: уточните выручку за август — она заметно ниже остальных месяцев" />
        <span className={len > 0 && len < 20 ? 'error-text' : 'hint'}>{len}/1000 · минимум 20 символов</span>
      </div>

      <div className="ir-section">
        <div className="ir-title">Параметры заявки</div>
        <div className="ir-chips">
          {BASE_FIELDS.map(({ f, label, value }) => (
            <button key={f} type="button" className={`ir-chip ${fields.has(f) ? 'on' : ''}`} aria-pressed={fields.has(f)} onClick={() => toggle(f)}>
              <b>{label}</b>
              <span>{value(c)}</span>
            </button>
          ))}
        </div>
      </div>

      <div className="ir-section">
        <div className="ir-title-row">
          <div className="ir-title">Финансовые показатели</div>
          <button type="button" className={`ir-all ${allFin ? 'on' : ''}`} aria-pressed={allFin} onClick={setAllFin}>
            {allFin ? 'Запрошены целиком' : 'Запросить все целиком'}
          </button>
        </div>
        <div className={`ir-rows ${allFin ? 'dim' : ''}`}>
          {FIN_FIELDS.map((ff) => {
            const st = rowState(ff.key)
            return (
              <div key={ff.key} className="ir-row">
                <div className="ir-row-head">
                  <b>{ff.label}</b>
                  <button type="button" className="link-btn" onClick={() => toggleRow(ff.key)} disabled={allFin}>
                    {st === 'all' ? 'снять все' : 'все месяцы'}
                  </button>
                </div>
                <div className="ir-months">
                  {snapMonths.map((mo) => {
                    const p = path(mo.month, ff.key)
                    const on = allFin || fields.has(p)
                    const v = mo[ff.key]
                    return (
                      <button key={p} type="button" disabled={allFin} className={`ir-month ${on ? 'on' : ''} ${v === null ? 'empty' : ''}`} aria-pressed={on} title={requestedFieldLabel(p)} onClick={() => toggle(p)}>
                        <span>{monthShort(mo.month)}</span>
                        <b className="num">{v === null ? 'нет' : moneyShort(v).replace(' ₽', '')}</b>
                      </button>
                    )
                  })}
                </div>
              </div>
            )
          })}
        </div>
      </div>

      <div className="ir-footer">
        <span className="hint">
          {count === 0 ? 'Поля не выбраны' : allFin && count === 1 ? selectedLabels[0] : `Выбрано полей: ${count}`}
          {count > 0 && (
            <>
              {' · '}
              <button type="button" className="link-btn" onClick={() => setFields(new Set())}>
                очистить
              </button>
            </>
          )}
        </span>
        <div className="row">
          <Button variant="ghost" onClick={onClose}>
            Отмена
          </Button>
          <Button variant="violet" loading={m.isPending} disabled={len < 20 || count === 0} onClick={() => m.mutate()}>
            Отправить запрос
          </Button>
        </div>
      </div>
    </Modal>
  )
}

function DecisionModal({ outcome, c, onClose, onDone, onFail }: { outcome: 'APPROVED' | 'REJECTED' | null; c: BankCard; onClose: () => void; onDone: (c: BankCard, m: string) => void; onFail: (e: unknown) => void }) {
  const [pub, setPub] = useState('')
  const [internal, setInternal] = useState('')
  const [sure, setSure] = useState(false)
  const m = useMutation({
    mutationFn: () => bank.decide(c.id, { expected_version: c.version, outcome: outcome!, public_explanation: pub.trim(), internal_comment: internal.trim() || null }),
    onSuccess: (card) => {
      setPub('')
      setInternal('')
      setSure(false)
      onDone(card, outcome === 'APPROVED' ? 'Заявка одобрена' : 'По заявке отказано')
    },
    onError: onFail,
  })
  const approve = outcome === 'APPROVED'
  const pay = (c.assessment?.calculation_details as Record<string, string> | undefined)?.monthly_payment
  return (
    <Modal open={!!outcome} onClose={onClose}>
      <span className={`tag ${approve ? '' : 'red'}`}>{approve ? 'Одобрение' : 'Отказ'}</span>
      <h3 style={{ marginTop: 14 }}>{approve ? 'Одобрить заявку' : 'Отказать по заявке'}</h3>
      {approve && (
        <div className="decision-terms">
          <div>
            <span>Сумма</span>
            <b className="num">{money(c.requested_amount)}</b>
          </div>
          <div>
            <span>Срок</span>
            <b>{months(c.term_months)}</b>
          </div>
          <div>
            <span>Платёж</span>
            <b className="num">{money(pay)}</b>
          </div>
        </div>
      )}
      <p className="hint" style={{ marginTop: 10 }}>
        Условия берутся из отправленного снимка — сотрудник их не меняет.
      </p>
      {approve && <PricingBreakdown value={c.assessment?.calculation_details.pricing} />}
      <div className="field" style={{ marginTop: 16 }}>
        <label htmlFor="d-pub">Обоснование для клиента</label>
        <textarea id="d-pub" className="textarea" maxLength={1000} value={pub} onChange={(e) => setPub(e.target.value)} placeholder={approve ? 'Нагрузка в допустимых пределах, история платежей без просрочек' : 'Причина, понятная клиенту'} />
        <span className={pub.trim().length > 0 && pub.trim().length < 20 ? 'error-text' : 'hint'}>{pub.trim().length}/1000 · клиент увидит этот текст</span>
      </div>
      <div className="field" style={{ marginTop: 14 }}>
        <label htmlFor="d-int">Внутренний комментарий · необязательно</label>
        <textarea id="d-int" className="textarea" maxLength={2000} value={internal} onChange={(e) => setInternal(e.target.value)} placeholder="Виден только сотрудникам банка" style={{ minHeight: 70 }} />
      </div>
      <div style={{ marginTop: 14 }}>
        <Checkbox checked={sure} onChange={setSure} title="Решение окончательное" desc="После подтверждения заявка завершится, новое решение по ней принять нельзя." />
      </div>
      <div className="modal-actions">
        <Button variant="ghost" onClick={onClose}>
          Отмена
        </Button>
        <Button variant={approve ? 'lime' : 'red'} loading={m.isPending} disabled={pub.trim().length < 20 || !sure} onClick={() => m.mutate()}>
          {approve ? 'Одобрить' : 'Отказать'}
        </Button>
      </div>
    </Modal>
  )
}
