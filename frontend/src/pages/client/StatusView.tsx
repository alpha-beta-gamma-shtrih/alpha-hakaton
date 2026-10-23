import { useQuery } from '@tanstack/react-query'
import { FinTable } from '../../components/FinTable'
import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { applications } from '../../api/endpoints'
import type { Assessment, CheckSource, Draft, EventItem } from '../../api/types'
import { PixelArt, type PixelShape } from '../../components/pixel'
import { Arrow, Button, Notice, ProvenanceBadge, Reasons, RiskMeter, SectionTitle, Skeleton, StatusChip } from '../../components/ui'
import { dateTime, money, months, percent, shortId } from '../../lib/format'
import { CHECK_SOURCE, CHECK_STATUS, eventLabel, PURPOSE, requestedFieldLabel, STATUS } from '../../lib/labels'
import { useCompanies, useProducts, useStartApplication } from '../../lib/queries'
import { DocumentsCard } from './wizard/steps'

const HERO: Record<string, { panel: string; shape: PixelShape; pix: string; title: string }> = {
  APPROVED: { panel: 'lime', shape: 'smile', pix: 'var(--ink)', title: 'Одобрено' },
  REJECTED: { panel: 'red', shape: 'cross', pix: '#fff', title: 'Отказано' },
  MANUAL_REVIEW: { panel: 'violet', shape: 'hourglass', pix: 'var(--lime)', title: 'Заявку изучает специалист' },
  NEEDS_INFO: { panel: 'ink', shape: 'question', pix: 'var(--amber)', title: 'Нужны уточнения' },
  SUBMITTED: { panel: 'blue', shape: 'bolt', pix: 'var(--lime)', title: 'Проверяем заявку' },
  CHECKING: { panel: 'blue', shape: 'bolt', pix: 'var(--lime)', title: 'Проверяем заявку' },
}

const PIPE = ['Черновик', 'Отправлена', 'Проверки', 'Оценка', 'Решение']
function pipeIndex(s: Draft['status']) {
  return { DRAFT: 0, SUBMITTED: 1, CHECKING: 2, NEEDS_INFO: 3, MANUAL_REVIEW: 3, APPROVED: 4, REJECTED: 4 }[s]
}

export function StatusView({ app, justSubmitted, onEdit }: { app: Draft; justSubmitted: boolean; onEdit: () => void }) {
  const events = useQuery({ queryKey: ['events', app.id, app.version], queryFn: () => applications.events(app.id), placeholderData: (p) => p })
  const rev = useQuery({
    queryKey: ['revision', app.id, app.latest_revision_no],
    queryFn: () => applications.revision(app.id, app.latest_revision_no!),
    enabled: !!app.latest_revision_no,
    staleTime: Infinity,
  })
  const companies = useCompanies()
  const products = useProducts()
  const start = useStartApplication()
  const hero = HERO[app.status] ?? HERO.SUBMITTED
  const d = app.decision
  const a = app.assessment
  const pi = pipeIndex(app.status)

  return (
    <div className="page">
      <div className="wz-head">
        <div>
          <Link to="/applications" className="back">
            <Arrow dir="left" /> Мои заявки
          </Link>
          <h1 className="page-title">Заявка № {shortId(app.id)}</h1>
          <div className="row wrap" style={{ marginTop: 12 }}>
            <StatusChip status={app.status} />
            {app.latest_revision_no && <span className="hint">отправка {app.latest_revision_no}</span>}
            <span className="hint">обновлена {dateTime(app.updated_at)}</span>
          </div>
        </div>
      </div>

      <div className="pipe" aria-label="Этапы заявки">
        {PIPE.map((p, i) => (
          <div key={p} className={`pipe-step ${i < pi ? 'done' : i === pi ? 'cur' : ''} ${i === pi ? `t-${STATUS[app.status].tone}` : ''}`}>
            <i />
            <span>{p}</span>
          </div>
        ))}
      </div>

      <section className={`panel ${hero.panel} dots st-hero ${justSubmitted ? 'just' : ''}`}>
        <div className="st-hero-main">
          <span className={`tag ${hero.panel === 'lime' ? 'ink' : 'white'}`}>{d ? (d.source === 'MANUAL' ? 'Решение специалиста' : 'Автоматическое решение') : STATUS[app.status].label}</span>
          <h2 className="st-title">{hero.title}</h2>
          {d?.outcome === 'APPROVED' ? (
            <>
              <div className="st-amount display num">{money(d.approved_amount)}</div>
              <div className="st-terms">
                <div>
                  <span>Срок</span>
                  <b>{months(d.approved_term_months)}</b>
                </div>
                <div>
                  <span>Ставка</span>
                  <b>{d.annual_rate_percent ? `${Number(d.annual_rate_percent)}%` : '—'}</b>
                </div>
                <div>
                  <span>Платёж</span>
                  <b className="num">{money(d.monthly_payment)}</b>
                </div>
              </div>
              <p className="st-text">{d.public_explanation}</p>
              <p className="st-foot">Демо-версия: подписание документов и выдача средств не выполняются.</p>
            </>
          ) : d?.outcome === 'REJECTED' ? (
            <>
              <p className="st-text">{d.public_explanation}</p>
              <div className="row wrap" style={{ marginTop: 22 }}>
                <Button
                  variant="white"
                  loading={start.isPending}
                  onClick={() => companies.data && products.data && start.mutate({ companyId: app.company_id, productId: app.product_id })}
                >
                  Подобрать другие параметры <Arrow />
                </Button>
              </div>
            </>
          ) : app.status === 'NEEDS_INFO' ? (
            <>
              <p className="st-text">{app.open_information_request?.message_to_client ?? STATUS.NEEDS_INFO.hint}</p>
              {!!app.open_information_request?.requested_fields.length && (
                <div className="row wrap" style={{ gap: 8, marginTop: 14 }}>
                  {app.open_information_request.requested_fields.map((f) => (
                    <span key={f} className="field-pill static">
                      {requestedFieldLabel(f)}
                    </span>
                  ))}
                </div>
              )}
              <div className="row wrap" style={{ marginTop: 22 }}>
                <Button variant="lime" size="lg" onClick={onEdit}>
                  Дополнить сведения <Arrow />
                </Button>
              </div>
            </>
          ) : app.status === 'MANUAL_REVIEW' ? (
            <p className="st-text">Правила не дают однозначного ответа, поэтому заявку смотрит сотрудник банка. Он может запросить уточнения — тогда они появятся здесь. Ничего делать не нужно.</p>
          ) : (
            <p className="st-text">Данные зафиксированы. Идут проверки — страница обновится сама.</p>
          )}
        </div>
        <div className="st-hero-art" aria-hidden="true">
          <PixelArt shape={hero.shape} size={18} gap={4} color={hero.pix} />
        </div>
      </section>

      <div className="st-grid">
        <div className="stack-lg">
          <ChecksCard a={a} animate={justSubmitted} />
          {a && <AssessmentCard a={a} />}
          {rev.data ? (
            <div className="card">
              <SectionTitle n="03" color="violet" aside={<span className="hint">отправка {rev.data.revision_no} · {dateTime(rev.data.created_at)}</span>}>
                Отправленные данные
              </SectionTitle>
              <div className="review-grid">
                <div className="review-item accent">
                  <span>Сумма</span>
                  <b className="num">{money(rev.data.requested_amount)}</b>
                </div>
                <div className="review-item accent">
                  <span>Срок</span>
                  <b>{months(rev.data.term_months)}</b>
                </div>
                <div className="review-item">
                  <span>Цель</span>
                  <b>{PURPOSE[rev.data.purpose_code].label}</b>
                </div>
              </div>
              <SnapshotMonths snapshot={rev.data.financial_snapshot} />
            </div>
          ) : app.latest_revision_no ? (
            <Skeleton h={200} r={22} />
          ) : null}
        </div>
        <div className="stack-lg">
          <div className="card">
            <SectionTitle n="04" color="ink">
              История
            </SectionTitle>
            {events.data ? <Timeline items={events.data.items} /> : <Skeleton h={160} />}
          </div>
          <DocumentsCard docs={rev.data?.document_refs ?? app.documents} title="Документы заявки" n="05" />
        </div>
      </div>
    </div>
  )
}

function ChecksCard({ a, animate }: { a: Assessment | null | undefined; animate: boolean }) {
  const [shown, setShown] = useState(animate ? 0 : 3)
  useEffect(() => {
    if (!animate || !a) return
    setShown(0)
    const t = [1, 2, 3].map((n) => setTimeout(() => setShown(n), n * 550))
    return () => t.forEach(clearTimeout)
  }, [animate, a])
  const order: CheckSource[] = ['DATA_QUALITY', 'FNS', 'BKI']
  return (
    <div className="card">
      <SectionTitle n="01" aside={a && <ProvenanceBadge item={a.provenance.credit_history ?? a.provenance.company} />}>
        Проверки
      </SectionTitle>
      <div className="checks">
        {order.map((src, i) => {
          const c = a?.checks.find((x) => x.source === src)
          const visible = c && i < shown
          const tone = c ? CHECK_STATUS[c.status].tone : 'wait'
          return (
            <div key={src} className={`check-card ${visible ? `t-${tone}` : 't-wait'}`}>
              <span className="check-ic">{visible ? (tone === 'ok' ? '✓' : tone === 'warn' ? '!' : '×') : <i className="dots3" />}</span>
              <div>
                <b>{CHECK_SOURCE[src].label}</b>
                <span>{visible ? CHECK_STATUS[c!.status].label : a ? 'проверяем…' : 'ожидает'}</span>
              </div>
            </div>
          )
        })}
      </div>
      {!a && <p className="hint" style={{ marginTop: 12 }}>Результаты появятся после завершения обработки.</p>}
    </div>
  )
}

function AssessmentCard({ a }: { a: Assessment }) {
  const cd = a.calculation_details as Record<string, unknown>
  const factors = (cd.factors as { factor_id: string; points: number }[] | undefined) ?? []
  return (
    <div className="card">
      <SectionTitle n="02" color="red" aside={<span className="hint">правила {a.rules_version}</span>}>
        Оценка
      </SectionTitle>
      <div className="assess">
        <div>
          <span className="label">Риск-балл</span>
          <RiskMeter score={a.risk_score} band={a.risk_band} />
        </div>
        <div className="assess-stats">
          <div>
            <span>Платёж</span>
            <b className="num">{money(cd.monthly_payment as string)}</b>
          </div>
          <div>
            <span>Нагрузка</span>
            <b className="num">{percent(cd.load_ratio as string)}</b>
          </div>
          <div>
            <span>Поток в месяц</span>
            <b className="num">{money(cd.average_operating_cashflow as string)}</b>
          </div>
        </div>
      </div>
      {factors.length > 0 && (
        <div className="factor-row">
          {factors.map((f) => (
            <span key={f.factor_id} className="factor">
              {f.factor_id} <b>+{f.points}</b>
            </span>
          ))}
        </div>
      )}
      <div style={{ marginTop: 16 }}>
        <Reasons items={a.reasons} />
      </div>
    </div>
  )
}

function SnapshotMonths({ snapshot }: { snapshot: Record<string, unknown> }) {
  const fm = (snapshot.financial_months as { month: string; cash_inflow: string | null; operating_outflow: string | null; existing_debt_payment: string | null }[] | undefined) ?? []
  if (!fm.length) return null
  return (
    <details className="snap">
      <summary>Финансовые показатели из отправки</summary>
      <FinTable rows={fm} showFlow={false} />
    </details>
  )
}

export function Timeline({ items }: { items: (EventItem & { visibility?: string; actor_user_id?: string | null })[] }) {
  const sorted = [...items].sort((a, b) => b.sequence_no - a.sequence_no)
  if (!sorted.length) return <Notice tone="plain">Событий пока нет.</Notice>
  return (
    <ol className="timeline">
      {sorted.map((e) => (
        <li key={e.id}>
          <span className="pin" style={{ color: e.to_status ? STATUS[e.to_status].color : 'var(--muted)', background: e.to_status === 'APPROVED' ? 'var(--ink)' : undefined }}>
            <i />
          </span>
          <div>
            <div className="row wrap" style={{ gap: 8 }}>
              <span className="what">{eventLabel(e.event_type)}</span>
              {e.visibility === 'BANK' && <span className="mini">только банк</span>}
            </div>
            <div className="msg">{e.message}</div>
            <div className="when">{dateTime(e.created_at)}</div>
          </div>
        </li>
      ))}
    </ol>
  )
}
