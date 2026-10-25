import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { bank } from '../../api/endpoints'
import type { ApplicationStatus, BankQueueItem } from '../../api/types'
import { PixelArt, PixelCursor } from '../../components/pixel'
import { Arrow, ErrorNotice, RiskMeter, Skeleton, StatusChip } from '../../components/ui'
import { dateTime, money, months, relative, shortId } from '../../lib/format'
import { PURPOSE } from '../../lib/labels'

const ACTIVE_FILTERS: { id: string; label: string; statuses: ApplicationStatus[] }[] = [
  { id: 'all', label: 'Все активные', statuses: ['SUBMITTED', 'CHECKING', 'NEEDS_INFO', 'MANUAL_REVIEW'] },
  { id: 'manual', label: 'Ручной разбор', statuses: ['MANUAL_REVIEW'] },
  { id: 'info', label: 'Ждут клиента', statuses: ['NEEDS_INFO'] },
  { id: 'proc', label: 'В обработке', statuses: ['SUBMITTED', 'CHECKING'] },
]
const FINAL_FILTERS: { id: string; label: string; statuses: ApplicationStatus[] }[] = [
  { id: 'all', label: 'Все решения', statuses: ['APPROVED', 'REJECTED', 'SIGNED'] },
  { id: 'ok', label: 'Одобрено', statuses: ['APPROVED', 'SIGNED'] },
  { id: 'signed', label: 'Подписано', statuses: ['SIGNED'] },
  { id: 'no', label: 'Отказано', statuses: ['REJECTED'] },
]

export function QueuePage({ mode }: { mode: 'active' | 'final' }) {
  const filters = mode === 'active' ? ACTIVE_FILTERS : FINAL_FILTERS
  const [f, setF] = useState(filters[0].id)
  const all = filters[0].statuses
  const q = useQuery({
    queryKey: ['bank-queue', mode],
    queryFn: () => bank.queue(all, undefined, 100),
    refetchInterval: 10_000,
  })
  const nav = useNavigate()
  const items = q.data?.items ?? []
  const cur = filters.find((x) => x.id === f)!
  const shown = items.filter((i) => cur.statuses.includes(i.status))
  const count = (s: ApplicationStatus[]) => items.filter((i) => s.includes(i.status)).length
  const attention = items.filter((i) => i.allowed_actions.length > 0).length

  return (
    <div className="page">
      <section className={`panel ${mode === 'active' ? 'ink' : 'violet'} dots bank-hero`}>
        <div>
          <span className={`tag ${mode === 'active' ? '' : 'white'}`}>{mode === 'active' ? 'Рабочее место' : 'Архив решений'}</span>
          <h1 className="bank-hero-title">{mode === 'active' ? 'Очередь заявок' : 'Решения'}</h1>
          <p className="bank-hero-sub">{mode === 'active' ? 'Сначала — более ранние отправки. Обновляется каждые 10 секунд.' : 'Завершённые заявки: автоматические и ручные решения.'}</p>
        </div>
        <div className="bank-kpis">
          {mode === 'active' ? (
            <>
              <Kpi v={items.length} k="активных" />
              <Kpi v={attention} k="ждут действия" accent />
              <Kpi v={count(['NEEDS_INFO'])} k="ждут клиента" />
            </>
          ) : (
            <>
              <Kpi v={count(['APPROVED', 'SIGNED'])} k="одобрено" accent />
              <Kpi v={count(['REJECTED'])} k="отказано" />
            </>
          )}
        </div>
        <PixelCursor size={64} className="bank-hero-cursor" />
      </section>

      <div className="row wrap between" style={{ margin: '22px 0 16px' }}>
        <div className="seg">
          {filters.map((x) => (
            <button key={x.id} className={f === x.id ? 'on' : ''} onClick={() => setF(x.id)}>
              {x.label}
              <span className="count">{count(x.statuses)}</span>
            </button>
          ))}
        </div>
        {q.dataUpdatedAt > 0 && <span className="hint">обновлено {relative(new Date(q.dataUpdatedAt).toISOString())}</span>}
      </div>

      <ErrorNotice error={q.error} onRetry={() => q.refetch()} />

      {q.isLoading ? (
        <div className="stack">
          {[0, 1, 2].map((i) => (
            <Skeleton key={i} h={86} r={20} />
          ))}
        </div>
      ) : shown.length === 0 ? (
        <div className="card empty">
          <PixelArt shape={mode === 'active' ? 'check' : 'doc'} size={10} color="var(--lime)" />
          <b style={{ color: 'var(--ink)' }}>{mode === 'active' ? 'Очередь пуста' : 'Решений пока нет'}</b>
          <span>{mode === 'active' ? 'Новые отправки появятся здесь автоматически.' : 'Финальные заявки попадут сюда.'}</span>
        </div>
      ) : (
        <div className="q-list stagger">
          {shown.map((it) => (
            <QueueRow key={it.id} it={it} onOpen={() => nav(`/bank/applications/${it.id}`)} />
          ))}
        </div>
      )}
    </div>
  )
}

function Kpi({ v, k, accent }: { v: number; k: string; accent?: boolean }) {
  return (
    <div className={`kpi ${accent ? 'accent' : ''}`}>
      <b className="display num">{v}</b>
      <span>{k}</span>
    </div>
  )
}

function QueueRow({ it, onOpen }: { it: BankQueueItem; onOpen: () => void }) {
  const reason = it.assessment_reasons[0]
  const needsAction = it.allowed_actions.length > 0
  return (
    <button className={`q-row ${needsAction ? 'act' : ''}`} onClick={onOpen}>
      <div className="q-id">
        <b className="mono">№ {shortId(it.id)}</b>
        <span className="hint">{relative(it.submitted_at)}</span>
      </div>
      <div className="q-co">
        <b>{it.company_name}</b>
        <span className="hint">
          ИНН {it.inn} · {it.product_code} v{it.product_version}
          {it.latest_revision_no > 1 && ` · отправка ${it.latest_revision_no}`}
        </span>
      </div>
      <div className="q-amt">
        <b className="num">{money(it.approved_amount ?? it.requested_amount)}</b>
        <span className="hint">
          {it.approved_amount ? 'Одобрено · ' : 'Запрошено · '}{months(it.approved_term_months ?? it.term_months)} · {PURPOSE[it.purpose_code].label.toLowerCase()}
        </span>
      </div>
      <div className="q-risk">
        {it.terms_changed && <span className="hint">Исходная оценка</span>}
        <RiskMeter score={it.risk_score} band={it.risk_band} compact />
      </div>
      <div className="q-st">
        <StatusChip status={it.status} />
        {reason && <span className="q-reason" title={reason.message}>{reason.message}</span>}
      </div>
      <div className="q-go">
        {needsAction && <span className="q-flag">действие</span>}
        <Arrow />
      </div>
      <span className="sr-only">Отправлена {dateTime(it.submitted_at)}</span>
    </button>
  )
}
