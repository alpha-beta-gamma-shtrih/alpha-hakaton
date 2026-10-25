import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { Link } from 'react-router-dom'
import { downloadDocument } from '../../api/client'
import { catalog } from '../../api/endpoints'
import type { CompanyDocument } from '../../api/types'
import { Button, ErrorNotice, SectionTitle, Skeleton, StatusChip, useToast } from '../../components/ui'
import { dateTime, money, months, rate, shortId } from '../../lib/format'
import { SignedAgreementDialog } from './AgreementDialog'

const PAGE_SIZE = 10

function FilePagination({ total, offset, busy, label, onChange }: { total: number; offset: number; busy: boolean; label: string; onChange: (offset: number) => void }) {
  if (!total && !offset) return null
  return (
    <div className="row between" style={{ marginTop: 18, flexWrap: 'wrap', gap: 12 }}>
      <span className="hint">{Math.min(offset + 1, total)}–{Math.min(offset + PAGE_SIZE, total)} из {total}</span>
      <div className="row" style={{ gap: 8 }}>
        <Button variant="white" size="sm" aria-label={`Предыдущая страница: ${label}`} disabled={busy || !offset} onClick={() => onChange(Math.max(0, offset - PAGE_SIZE))}>Назад</Button>
        <Button variant="white" size="sm" aria-label={`Следующая страница: ${label}`} disabled={busy || offset + PAGE_SIZE >= total} onClick={() => onChange(offset + PAGE_SIZE)}>Далее</Button>
      </div>
    </div>
  )
}

export function CompanyFiles({ companyId }: { companyId: string }) {
  const [agreementOffset, setAgreementOffset] = useState(0)
  const [documentOffset, setDocumentOffset] = useState(0)
  const [selected, setSelected] = useState<string | null>(null)
  const [downloading, setDownloading] = useState<string | null>(null)
  const toast = useToast()
  const agreements = useQuery({ queryKey: ['company-agreements', companyId, agreementOffset], queryFn: () => catalog.companyAgreements(companyId, PAGE_SIZE, agreementOffset) })
  const documents = useQuery({ queryKey: ['company-documents', companyId, documentOffset], queryFn: () => catalog.companyDocuments(companyId, PAGE_SIZE, documentOffset) })

  async function download(document: CompanyDocument) {
    if (downloading) return
    setDownloading(document.id)
    try {
      await downloadDocument(document.download_url, document.original_filename)
    } catch (error) {
      toast.error(error, 'Не удалось скачать документ')
    } finally {
      setDownloading(null)
    }
  }

  return (
    <div className="stack" style={{ marginTop: 16, gap: 16 }}>
      <section className="card" aria-label="Кредитные договоры">
        <SectionTitle n="03" color="red">Кредитные договоры</SectionTitle>
        <p className="hint" style={{ marginBottom: 16 }}>Подписанные демонстрационные условия. Откройте документ, чтобы посмотреть условия и дату подписания.</p>
        <ErrorNotice error={agreements.error} onRetry={() => agreements.refetch()} />
        {agreements.isLoading ? <Skeleton h={140} /> : !agreements.error && (agreements.data?.items.length ? (
          <div className="table-wrap">
            <table className="table">
              <thead><tr><th>Заявка</th><th>Сумма и срок</th><th>Ставка и платёж</th><th>Подписан</th><th /></tr></thead>
              <tbody>{agreements.data.items.map(({ content, signature }) => (
                <tr key={content.application_id}>
                  <td><Link className="mono" to={`/applications/${content.application_id}`}>№ {shortId(content.application_id)}</Link><div style={{ marginTop: 8 }}><StatusChip status="SIGNED" /></div></td>
                  <td><b className="num">{money(content.approved_amount)}</b><div className="hint">{months(content.term_months)}</div></td>
                  <td><b>{rate(content.annual_rate_percent)} годовых</b><div className="hint">{money(content.monthly_payment)} / мес</div></td>
                  <td>{dateTime(signature.signed_at)}<div className="hint">{signature.signed_by_display_name}</div></td>
                  <td className="r"><Button variant="white" size="sm" onClick={() => setSelected(content.application_id)}>Посмотреть документ</Button></td>
                </tr>
              ))}</tbody>
            </table>
          </div>
        ) : <p className="muted">Пока нет подписанных договоров. Они появятся после подписания одобренных условий.</p>)}
        {agreements.data && <FilePagination total={agreements.data.total} offset={agreementOffset} busy={agreements.isFetching} label="кредитные договоры" onChange={setAgreementOffset} />}
      </section>

      <section className="card" aria-label="Документы по заявкам">
        <SectionTitle n="04" color="ink">Документы по заявкам</SectionTitle>
        <p className="hint" style={{ marginBottom: 16 }}>Финансовые отчёты, прикреплённые к заявкам компании. У каждой заявки своя копия документа.</p>
        <ErrorNotice error={documents.error} onRetry={() => documents.refetch()} />
        {documents.isLoading ? <Skeleton h={140} /> : !documents.error && (documents.data?.items.length ? (
          <div className="table-wrap">
            <table className="table">
              <thead><tr><th>Документ</th><th>Заявка</th><th>Статус заявки</th><th>Добавлен</th><th /></tr></thead>
              <tbody>{documents.data.items.map((document) => (
                <tr key={document.id}>
                  <td><b>{document.kind === 'FINANCIAL_STATEMENT' ? 'Финансовый отчёт' : document.kind}</b><div className="hint">{document.original_filename} · {(document.size_bytes / 1024).toFixed(1)} КБ</div></td>
                  <td><Link className="mono" to={`/applications/${document.application_id}`}>№ {shortId(document.application_id)}</Link></td>
                  <td><StatusChip status={document.application_status} /></td>
                  <td className="hint">{dateTime(document.created_at)}</td>
                  <td className="r"><Button variant="white" size="sm" loading={downloading === document.id} disabled={!!downloading} onClick={() => void download(document)}>Скачать</Button></td>
                </tr>
              ))}</tbody>
            </table>
          </div>
        ) : <p className="muted">Документы появятся после создания заявки.</p>)}
        {documents.data && <FilePagination total={documents.data.total} offset={documentOffset} busy={documents.isFetching} label="документы по заявкам" onChange={setDocumentOffset} />}
      </section>
      {selected && <SignedAgreementDialog applicationId={selected} onClose={() => setSelected(null)} />}
    </div>
  )
}
