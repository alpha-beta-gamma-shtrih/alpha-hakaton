import type { FinancialMonth } from '../../api/types'
import { FinTable } from '../../components/FinTable'
import { PixelArt } from '../../components/pixel'
import { ErrorNotice, ProvenanceBadge, SectionTitle, Skeleton, Stat } from '../../components/ui'
import { date, money, moneyShort, monthName, monthShort } from '../../lib/format'
import { LEGAL_FORM } from '../../lib/labels'
import { useCompanies, useCompany } from '../../lib/queries'
import { CompanyFiles } from './CompanyFiles'

/** Inflow vs outflow bars with the operating cash flow line, per month. */
export function CashflowBars({ months, height = 220 }: { months: FinancialMonth[]; height?: number }) {
  const vals = months.flatMap((m) => [Number(m.cash_inflow ?? 0), Number(m.operating_outflow ?? 0)])
  const max = Math.max(1, ...vals) * 1.08
  return (
    <div className="cf">
      <div className="cf-legend">
        <span>
          <i style={{ background: 'var(--ink)' }} /> Поступления
        </span>
        <span>
          <i style={{ background: 'var(--red)' }} /> Операционные выплаты
        </span>
        <span>
          <i style={{ background: 'var(--lime)' }} /> Платежи по долгам
        </span>
      </div>
      <div className="cf-chart" style={{ height }}>
        {months.map((m, i) => {
          const inf = m.cash_inflow === null ? null : Number(m.cash_inflow)
          const out = m.operating_outflow === null ? null : Number(m.operating_outflow)
          const debt = m.existing_debt_payment === null ? null : Number(m.existing_debt_payment)
          return (
            <div className="cf-col" key={m.month} title={`${monthName(m.month)}: поступления ${money(inf)}, выплаты ${money(out)}, долги ${money(debt)}`}>
              <div className="cf-bars">
                <i className={inf === null ? 'missing' : ''} style={{ height: `${((inf ?? max * 0.3) / max) * 100}%`, background: 'var(--ink)', animationDelay: `${i * 0.06}s` }} />
                <i className={out === null ? 'missing' : ''} style={{ height: `${((out ?? max * 0.3) / max) * 100}%`, background: 'var(--red)', animationDelay: `${i * 0.06 + 0.03}s` }} />
                <i className={debt === null ? 'missing' : ''} style={{ height: `${Math.max(2, ((debt ?? max * 0.1) / max) * 100)}%`, background: 'var(--lime)', animationDelay: `${i * 0.06 + 0.05}s` }} />
              </div>
              <span className="cf-m">{monthShort(m.month)}</span>
            </div>
          )
        })}
      </div>
    </div>
  )
}

export function CompanyPage() {
  const companies = useCompanies()
  const company = companies.data?.items[0]
  const d = useCompany(company?.id)
  const fm = d.data?.financial_months ?? []
  const sum = (k: 'cash_inflow' | 'operating_outflow' | 'existing_debt_payment') => fm.reduce((a, m) => a + Number(m[k] ?? 0), 0)
  const avgCf = fm.length ? (sum('cash_inflow') - sum('operating_outflow')) / fm.length : null

  return (
    <div className="page">
      <div className="page-head">
        <div>
          <span className="tag">Профиль компании</span>
          <h1 className="page-title" style={{ marginTop: 16 }}>
            {company?.legal_name ?? <Skeleton h={50} w={420} />}
          </h1>
          <p className="page-sub">{company?.business_description}</p>
        </div>
      </div>
      <ErrorNotice error={companies.error || d.error} />

      <div className="grid grid-4 stagger" style={{ marginBottom: 16 }}>
        <div className="card">
          <Stat k="Средний операционный поток" v={avgCf === null ? '—' : moneyShort(avgCf)} sub="в месяц за 6 месяцев" />
        </div>
        <div className="card">
          <Stat k="Поступления за 6 мес" v={moneyShort(sum('cash_inflow'))} />
        </div>
        <div className="card">
          <Stat k="Выплаты за 6 мес" v={moneyShort(sum('operating_outflow'))} />
        </div>
        <div className="card">
          <Stat k="Платежи по отчёту" v={moneyShort(fm.at(-1)?.existing_debt_payment)} sub="исторические данные за последний месяц" />
        </div>
      </div>

      {d.data?.credit_exposure && <section className="card" style={{ marginBottom: 24 }}>
        <SectionTitle color="violet">Кредиты и одобренные предложения</SectionTitle>
        <div className="grid grid-4" style={{ marginTop: 16 }}>
          <Stat k="Подписанные в сервисе" v={moneyShort(d.data.credit_exposure.signed_payment)} sub={`Договоров: ${d.data.credit_exposure.signed_count} · платёж в месяц`} />
          <Stat k="Резерв по одобрениям" v={moneyShort(d.data.credit_exposure.reserved_payment)} sub={`Предложений: ${d.data.credit_exposure.reserved_count} · ещё не подписаны`} />
          <Stat k="Платежи с учётом сервиса" v={moneyShort(d.data.credit_exposure.current_payment)} sub="по профилю + подписанные в сервисе" />
          <Stat k="С учётом резервов" v={moneyShort(d.data.credit_exposure.committed_payment)} sub="используется как часть проверки новых заявок" />
        </div>
        <p className="hint" style={{ marginTop: 16 }}>При оценке заявки банк дополнительно сверяет исходные платежи с демо-БКИ и берёт большее значение. Резерв освобождается при отказе, а при подписании переходит в действующие демо-платежи. Погашение в MVP не моделируется.</p>
      </section>}

      <div className="grid co-grid">
        <div className="card">
          <SectionTitle n="01">Реквизиты</SectionTitle>
          {company ? (
            <dl className="kv">
              <dt>Наименование</dt>
              <dd>{company.legal_name}</dd>
              <dt>Форма</dt>
              <dd>{LEGAL_FORM[company.legal_form]}</dd>
              <dt>ИНН</dt>
              <dd className="num">{company.inn}</dd>
              <dt>ОГРН</dt>
              <dd className="num">{company.registration_number ?? '—'}</dd>
              <dt>Дата регистрации</dt>
              <dd>{date(company.registered_on)}</dd>
              <dt>ОКВЭД</dt>
              <dd>{company.okved_code}</dd>
              <dt>Регион</dt>
              <dd>{company.region_code}</dd>
            </dl>
          ) : (
            <Skeleton h={200} />
          )}
          <div style={{ marginTop: 18 }}>
            <ProvenanceBadge item={d.data?.provenance.company} />
          </div>
          <div className="co-pixel" aria-hidden="true">
            <PixelArt shape="doc" size={8} color="var(--line)" animate={false} />
          </div>
        </div>
        <div className="card">
          <SectionTitle n="02" color="red" aside={<ProvenanceBadge item={d.data?.provenance.financial_months} />}>
            Денежный поток
          </SectionTitle>
          {d.data ? <CashflowBars months={fm} /> : <Skeleton h={240} />}
          <div style={{ marginTop: 20 }}>
            <FinTable rows={fm} />
          </div>
          <p className="hint" style={{ marginTop: 12 }}>
            Профиль компании в демо не редактируется. Правки финансов внутри заявки меняют только её черновик.
          </p>
        </div>
      </div>
      {company && <CompanyFiles key={company.id} companyId={company.id} />}
    </div>
  )
}
