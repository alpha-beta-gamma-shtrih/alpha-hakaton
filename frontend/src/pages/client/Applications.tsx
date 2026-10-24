import { Fragment, useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { ApiError } from '../../api/client'
import { applications } from '../../api/endpoints'
import { useNavigate } from 'react-router-dom'
import type { Draft } from '../../api/types'
import { PixelArt } from '../../components/pixel'
import { Arrow, Button, ErrorNotice, Skeleton, StatusChip, useToast } from '../../components/ui'
import { dateTime, money, months, shortId } from '../../lib/format'
import { EDITABLE_STATUSES, FINAL_STATUSES, PURPOSE } from '../../lib/labels'
import { useApplications, useCompanies, useProducts, useStartApplication } from '../../lib/queries'

type Filter = 'all' | 'draft' | 'work' | 'final'
const FILTERS: { id: Filter; label: string; test: (a: Draft) => boolean }[] = [
  { id: 'all', label: 'Все', test: () => true },
  { id: 'draft', label: 'Черновики', test: (a) => EDITABLE_STATUSES.includes(a.status) },
  { id: 'work', label: 'В работе', test: (a) => !EDITABLE_STATUSES.includes(a.status) && !FINAL_STATUSES.includes(a.status) },
  { id: 'final', label: 'Завершённые', test: (a) => FINAL_STATUSES.includes(a.status) },
]

export function ApplicationsPage() {
  const apps = useApplications()
  const companies = useCompanies()
  const products = useProducts()
  const start = useStartApplication()
  const nav = useNavigate()
  const [filter, setFilter] = useState<Filter>('all')
  const [confirmId, setConfirmId] = useState<string | null>(null)
  const qc = useQueryClient()
  const toast = useToast()
  const del = useMutation({
    mutationFn: ({ id, version }: { id: string; version: number }) => applications.remove(id, version),
    onSuccess: (_r, { id }) => {
      setConfirmId(null)
      qc.removeQueries({ queryKey: ['application', id] })
      qc.invalidateQueries({ queryKey: ['applications'] })
      toast.push({ tone: 'ok', title: 'Черновик удалён' })
    },
    onError: (e) => {
      qc.invalidateQueries({ queryKey: ['applications'] })
      if (e instanceof ApiError && e.status === 404) {
        toast.push({ tone: 'info', title: 'Черновик уже удалён или недоступен' })
        setConfirmId(null)
        return
      }
      toast.error(e, 'Не удалось удалить')
    },
  })
  const all = apps.data?.items ?? []
  const items = all.filter(FILTERS.find((f) => f.id === filter)!.test)
  const company = companies.data?.items[0]
  const product = products.data?.items[0]

  return (
    <div className="page">
      <div className="page-head">
        <div>
          <span className="tag">Мои заявки</span>
          <h1 className="page-title" style={{ marginTop: 16 }}>
            Обращения
          </h1>
        </div>
        <Button variant="red" loading={start.isPending} disabled={!company || !product} onClick={() => start.mutate({ companyId: company!.id, productId: product!.id })}>
          Новая заявка <Arrow />
        </Button>
      </div>

      <div className="seg" style={{ marginBottom: 18 }}>
        {FILTERS.map((f) => (
          <button key={f.id} className={filter === f.id ? 'on' : ''} onClick={() => setFilter(f.id)}>
            {f.label}
            <span className="count">{all.filter(f.test).length}</span>
          </button>
        ))}
      </div>

      <ErrorNotice error={apps.error} onRetry={() => apps.refetch()} />

      <div className="card flush">
        {apps.isLoading ? (
          <div style={{ padding: 24 }} className="stack">
            <Skeleton h={48} />
            <Skeleton h={48} />
            <Skeleton h={48} />
          </div>
        ) : items.length === 0 ? (
          <div className="empty">
            <PixelArt shape="doc" size={9} color="var(--line-2)" />
            <span>В этом разделе пока пусто</span>
          </div>
        ) : (
          <div className="table-wrap" style={{ padding: '20px 18px 6px' }}>
            <table className="table clickable">
              <thead>
                <tr>
                  <th>Заявка</th>
                  <th>Статус</th>
                  <th className="r">Сумма</th>
                  <th>Срок</th>
                  <th>Цель</th>
                  <th>Обновлена</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {items.map((a) => {
                  const deletable = a.status === 'DRAFT' && !a.latest_revision_no
                  const asking = confirmId === a.id
                  return (
                    <Fragment key={a.id}>
                      <tr className={asking ? 'asking' : ''} onClick={() => nav(`/applications/${a.id}`)} tabIndex={0} onKeyDown={(e) => e.key === 'Enter' && e.target === e.currentTarget && nav(`/applications/${a.id}`)}>
                        <td>
                          <b className="mono">№ {shortId(a.id)}</b>
                          {a.latest_revision_no ? <div className="hint">отправка {a.latest_revision_no}</div> : null}
                        </td>
                        <td>
                          <StatusChip status={a.status} />
                        </td>
                        <td className="r num">
                          <b>{money(a.requested_amount)}</b>
                        </td>
                        <td>{months(a.term_months)}</td>
                        <td>{a.purpose_code ? PURPOSE[a.purpose_code].label : '—'}</td>
                        <td className="hint">{dateTime(a.updated_at)}</td>
                        <td className="r">
                          <span className="row-actions">
                            {deletable ? (
                              <button
                                type="button"
                                className={`row-del ${asking ? 'on' : ''}`}
                                aria-label="Удалить заявку"
                                title="Удалить черновик"
                                aria-expanded={asking}
                                onClick={(e) => {
                                  e.stopPropagation()
                                  setConfirmId(asking ? null : a.id)
                                }}
                              >
                                <TrashIcon />
                              </button>
                            ) : (
                              <span className="row-del-gap" aria-hidden="true" />
                            )}
                            <span className="row-go">
                              <Arrow />
                            </span>
                          </span>
                        </td>
                      </tr>
                      {asking && deletable && (
                        <tr className="confirm-row" onClick={(e) => e.stopPropagation()}>
                          <td colSpan={7}>
                            <div className={`del-confirm ${deletable ? '' : 'info'}`} role="alertdialog" aria-label="Подтверждение удаления">
                              <span className="del-ic">
                                <TrashIcon />
                              </span>
                              <div className="grow">
                                {deletable ? (
                                  <>
                                    <b>Удалить черновик № {shortId(a.id)}?</b>
                                    <span>Черновик исчезнет из кабинета. Восстановление через интерфейс не предусмотрено.</span>
                                  </>
                                ) : (
                                  <>
                                    <b>Эту заявку удалить нельзя</b>
                                    <span>Она уже отправлена в банк. Отправленные данные и решения хранятся в истории рассмотрения.</span>
                                  </>
                                )}
                              </div>
                              <div className="row">
                                <Button size="sm" variant="ghost" onClick={() => setConfirmId(null)}>
                                  {deletable ? 'Отмена' : 'Понятно'}
                                </Button>
                                {deletable && (
                                  <Button size="sm" variant="red" loading={del.isPending && del.variables?.id === a.id} onClick={() => del.mutate({ id: a.id, version: a.version })}>
                                    Удалить
                                  </Button>
                                )}
                              </div>
                            </div>
                          </td>
                        </tr>
                      )}
                    </Fragment>
                  )
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  )
}

function TrashIcon() {
  return (
    <svg width="17" height="17" viewBox="0 0 18 18" aria-hidden="true">
      <path d="M3 5h12M7 5V3.5h4V5M5 5l.7 9.2c.05.7.6 1.3 1.3 1.3h4c.7 0 1.25-.6 1.3-1.3L13 5M7.6 8v4.5M10.4 8v4.5" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  )
}
