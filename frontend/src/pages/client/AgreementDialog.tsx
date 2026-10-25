import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useId, useRef } from 'react'
import { useNavigate } from 'react-router-dom'
import { applications } from '../../api/endpoints'
import type { Draft } from '../../api/types'
import { Button, ErrorNotice, Modal, Notice, Skeleton, useToast } from '../../components/ui'
import { dateTime, money, months, shortId } from '../../lib/format'
import { PURPOSE } from '../../lib/labels'

export function AgreementDialog({ app, onClose }: { app: Draft; onClose: () => void }) {
  return <AgreementView app={app} applicationId={app.id} onClose={onClose} />
}

export function SignedAgreementDialog({ applicationId, onClose }: { applicationId: string; onClose: () => void }) {
  return <AgreementView applicationId={applicationId} onClose={onClose} />
}

function AgreementView({ app, applicationId, onClose }: { app?: Draft; applicationId: string; onClose: () => void }) {
  const qc = useQueryClient()
  const nav = useNavigate()
  const toast = useToast()
  const titleId = useId()
  const title = useRef<HTMLHeadingElement>(null)
  useEffect(() => { title.current?.focus() }, [])
  const document = useQuery({ queryKey: ['agreement', applicationId, app?.version ?? 'signed'], queryFn: () => applications.agreement(applicationId), retry: false })
  const sign = useMutation({
    mutationFn: () => {
      if (!document.data || !app) throw new Error('Документ недоступен для подписания')
      return applications.signAgreement(app.id, {
        expected_version: app.version,
        decision_id: document.data.content.decision_id,
        content_sha256: document.data.content_sha256,
        accepted: true,
      })
    },
    onSuccess: (updated) => {
      qc.setQueryData(['application', applicationId], updated)
      void qc.invalidateQueries({ queryKey: ['applications'] })
      void qc.invalidateQueries({ queryKey: ['events', applicationId] })
      void qc.invalidateQueries({ queryKey: ['company-agreements'] })
      void qc.invalidateQueries({ queryKey: ['company-documents'] })
      void qc.invalidateQueries({ queryKey: ['company'] })
      void qc.invalidateQueries({ queryKey: ['bank-queue'] })
      void qc.invalidateQueries({ queryKey: ['agreement', applicationId] })
      toast.push({ tone: 'ok', title: 'Демо-документ подписан', message: 'Электронная подпись имитирована. Средства не выдавались.' })
      onClose()
      nav('/applications')
    },
    onError: (error) => {
      toast.error(error, 'Подписание не выполнено')
      void qc.invalidateQueries({ queryKey: ['applications'] })
      void qc.invalidateQueries({ queryKey: ['bank-queue'] })
      void qc.invalidateQueries({ queryKey: ['company'] })
      void qc.invalidateQueries({ queryKey: ['application', applicationId] })
      void qc.invalidateQueries({ queryKey: ['agreement', applicationId] })
    },
  })
  const content = document.data?.content
  const signature = document.data?.signature
  return (
    <Modal open onClose={() => !sign.isPending && onClose()} width={720} labelledBy={titleId}>
      <div className="agreement-dialog">
        <div className="row between">
          <span className="tag violet">Демонстрационный документ</span>
          <Button size="sm" variant="white" disabled={sign.isPending} onClick={onClose}>Закрыть</Button>
        </div>
        <h2 id={titleId} ref={title} tabIndex={-1} className="card-title">Условия кредитного договора</h2>
        <ErrorNotice error={document.error} onRetry={() => document.refetch()} />
        {document.isLoading && <Skeleton h={240} />}
        {content && <>
          <p className="hint">Заявка № {shortId(applicationId)} · условия одобрены {dateTime(content.issued_at)}</p>
          {app?.decision?.offer && !signature && <Notice tone="plain">Вы подписываете предложение банка с изменёнными условиями. Проверьте новые сумму и срок перед подписанием.</Notice>}
          <h3>{content.company_name}</h3>
          <p className="hint">ИНН {content.inn} · {PURPOSE[content.purpose_code].label}</p>
          <dl className="kv agreement-terms">
            <dt>Одобренная сумма</dt><dd className="num">{money(content.approved_amount)}</dd>
            <dt>Срок кредита</dt><dd>{months(content.term_months)}</dd>
            <dt>Годовая ставка</dt><dd>{Number(content.annual_rate_percent)}%</dd>
            <dt>Ежемесячный платёж</dt><dd className="num">{money(content.monthly_payment)}</dd>
            <dt>Расчётная сумма выплат</dt><dd className="num">{money(content.estimated_total_payment)}</dd>
            <dt>Расчётная переплата</dt><dd className="num">{money(content.estimated_overpayment)}</dd>
          </dl>
          <p>Платежи рассчитаны по аннуитетной схеме. Здесь показаны одобренные банком условия отправленной заявки.</p>
          <Notice tone="plain">{content.notice}</Notice>
          {signature && <Notice tone="ok">Подписано в демо-режиме {dateTime(signature.signed_at)}. Участник: {signature.signed_by_display_name}.</Notice>}
          <ErrorNotice error={sign.error} />
          {app && !signature && <div className="agreement-actions">
            <p className="hint">Нажимая «Подписать», вы подтверждаете просмотр этих условий и запускаете эмуляцию электронной подписи.</p>
            <Button variant="lime" size="lg" loading={sign.isPending} disabled={document.isFetching || !!document.error} onClick={() => sign.mutate()}>Подписать</Button>
          </div>}
        </>}
      </div>
    </Modal>
  )
}
