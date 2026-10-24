import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { Link, matchPath, useLocation } from 'react-router-dom'
import { ApiError } from '../../api/client'
import { applications } from '../../api/endpoints'
import type { Draft } from '../../api/types'
import { AiDockShell, useAiDockClaimed } from '../../components/AiDock'
import { PixelArt } from '../../components/pixel'
import { Arrow, Button, StatusChip } from '../../components/ui'
import { money, months, shortId } from '../../lib/format'
import { EDITABLE_STATUSES, STATUS } from '../../lib/labels'
import { useApplications, useCompanies, useProducts, useStartApplication } from '../../lib/queries'
import { AdvisorReportView } from './wizard/Aside'

/** The AI button on every client page. Inside an open form the form's own panel takes over. */
export function GlobalAdvisor() {
  const claimed = useAiDockClaimed()
  const loc = useLocation()
  const [open, setOpen] = useState(false)
  const appId = matchPath('/applications/:id', loc.pathname)?.params.id
  if (claimed) return null
  return (
    <AiDockShell open={open} onOpen={() => setOpen(true)} onClose={() => setOpen(false)} subtitle={appId ? 'разбор этой заявки' : 'подскажет, с чего начать'}>
      <section className="panel violet dots advisor">
        <div className="row between">
          <span className="tag white sm">ИИ-помощник</span>
          <PixelArt shape="smile" size={4} gap={1} color="var(--lime)" animate={false} />
        </div>
        {appId ? <ApplicationHelp id={appId} onNavigate={() => setOpen(false)} /> : <GeneralHelp onNavigate={() => setOpen(false)} />}
      </section>
    </AiDockShell>
  )
}

/** A submitted application: what is happening now and the last saved AI report. */
function ApplicationHelp({ id, onNavigate }: { id: string; onNavigate: () => void }) {
  const app = useQuery({ queryKey: ['application', id], queryFn: () => applications.get(id) })
  const report = useQuery({
    queryKey: ['advisor-last', id],
    queryFn: async () => {
      try {
        return await applications.lastAdvisor(id)
      } catch (e) {
        if (e instanceof ApiError && (e.status === 404 || e.status === 422)) return null
        throw e
      }
    },
    retry: false,
  })
  const a = app.data
  return (
    <>
      <h3 className="advisor-title">Что с заявкой сейчас</h3>
      {a && (
        <div className="gai-status">
          <StatusChip status={a.status} />
          <p>{a.decision?.public_explanation || a.open_information_request?.message_to_client || STATUS[a.status].hint}</p>
          {a.status === 'NEEDS_INFO' && (
            <Link to={`/applications/${a.id}?edit=1`} className="btn lime sm" onClick={onNavigate}>
              Дополнить сведения <Arrow />
            </Link>
          )}
        </div>
      )}
      {report.data ? (
        <AdvisorReportView report={report.data} />
      ) : (
        !report.isLoading && <p className="advisor-sub">Сохранённого разбора по этой заявке нет. Разбор запускается в форме заявки до отправки: кнопки «Объяснить расчёт» и «Сравнить варианты».</p>
      )}
    </>
  )
}

/** Overview, list, company: point to the draft to continue or start a new one. */
function GeneralHelp({ onNavigate }: { onNavigate: () => void }) {
  const apps = useApplications()
  const companies = useCompanies()
  const products = useProducts()
  const start = useStartApplication()
  const list = apps.data?.items ?? []
  const drafts = list.filter((a) => EDITABLE_STATUSES.includes(a.status))
  const recent = list.filter((a) => !EDITABLE_STATUSES.includes(a.status)).slice(0, 3)
  const company = companies.data?.items[0]
  const product = products.data?.items[0]

  return (
    <>
      <h3 className="advisor-title">Объясню расчёт и сравню варианты</h3>
      <p className="advisor-sub">Разбираю заявку на цифрах, которые посчитал банк: платёж, нагрузку, меньшую сумму и более длинный срок. Решение не принимаю и заявку не меняю.</p>

      {drafts.length > 0 ? (
        <div className="gai-block">
          <b>Разобрать черновик</b>
          {drafts.map((d) => (
            <GaiRow key={d.id} app={d} to={`/applications/${d.id}${d.status === 'NEEDS_INFO' ? '?edit=1&ai=1' : '?ai=1'}`} onNavigate={onNavigate} />
          ))}
        </div>
      ) : (
        <div className="gai-block">
          <b>Черновиков нет</b>
          <span className="gai-note">Начните подбор — помощник откроется в форме заявки.</span>
          <Button
            variant="lime"
            size="sm"
            loading={start.isPending}
            disabled={!company || !product}
            onClick={() => {
              onNavigate()
              start.mutate({ companyId: company!.id, productId: product!.id })
            }}
          >
            Подобрать финансирование <Arrow />
          </Button>
        </div>
      )}

      {recent.length > 0 && (
        <div className="gai-block">
          <b>Отправленные заявки</b>
          {recent.map((d) => (
            <GaiRow key={d.id} app={d} to={`/applications/${d.id}`} onNavigate={onNavigate} />
          ))}
        </div>
      )}
      <p className="advisor-notice gai-foot">Для разбора нужно согласие на демо-проверку кредитной истории — оно в шаге «Проверка».</p>
    </>
  )
}

function GaiRow({ app, to, onNavigate }: { app: Draft; to: string; onNavigate: () => void }) {
  return (
    <Link to={to} className="gai-row" onClick={onNavigate}>
      <span className="grow">
        <span className="gai-row-top">
          <b className="mono">№ {shortId(app.id)}</b>
          <StatusChip status={app.status} />
        </span>
        <span className="gai-row-sub">{app.requested_amount ? `${money(app.requested_amount)} · ${months(app.term_months)}` : 'сумма не указана'}</span>
      </span>
      <Arrow />
    </Link>
  )
}
