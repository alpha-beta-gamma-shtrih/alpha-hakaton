import { Link } from 'react-router-dom'
import type { Draft } from '../../api/types'
import { Keycap, PixelArt, PixelCursor } from '../../components/pixel'
import { Arrow, Button, ErrorNotice, Skeleton, StatusChip } from '../../components/ui'
import { money, moneyShort, months, relative } from '../../lib/format'
import { EDITABLE_STATUSES, LEGAL_FORM, PURPOSE, STATUS, STEPS } from '../../lib/labels'
import { useSession } from '../../lib/session'
import { useApplications, useCompanies, useCompany, useProducts, useStartApplication } from '../../lib/queries'
import { CashflowBars } from './Company'

function greeting() {
  const h = new Date().getHours()
  return h < 6 ? 'Доброй ночи' : h < 12 ? 'Доброе утро' : h < 18 ? 'Добрый день' : 'Добрый вечер'
}

export function OverviewPage() {
  const { user } = useSession()
  const companies = useCompanies()
  const products = useProducts()
  const apps = useApplications()
  const start = useStartApplication()
  const company = companies.data?.items[0]
  const product = products.data?.items[0]
  const detail = useCompany(company?.id)

  const list = apps.data?.items ?? []
  const draft = list.find((a) => EDITABLE_STATUSES.includes(a.status))
  const active = list.filter((a) => !EDITABLE_STATUSES.includes(a.status) || a.status === 'NEEDS_INFO')

  return (
    <div className="page">
      <div className="page-head">
        <div>
          <span className="tag white">{company ? `${LEGAL_FORM[company.legal_form]} · ИНН ${company.inn}` : 'Кабинет предпринимателя'}</span>
          <h1 className="page-title" style={{ marginTop: 16 }}>
            {greeting()},<br />
            {user?.display_name}
          </h1>
        </div>
        {draft && (
          <Link to={`/applications/${draft.id}`} className="btn lime lg">
            {draft.status === 'NEEDS_INFO' ? 'Дополнить сведения' : 'Продолжить заявку'} <Arrow />
          </Link>
        )}
      </div>

      <ErrorNotice error={companies.error || products.error || apps.error} />

      <div className="ov-hero">
        <section className="panel red dots ov-offer">
          <span className="tag white">Оборотный кредит · демо</span>
          <h2 className="ov-offer-title">
            Деньги на товар
            <br />и текущие расходы
          </h2>
          {product ? (
            <div className="ov-terms">
              <div>
                <span>Сумма</span>
                <b>
                  {moneyShort(product.min_amount)} — {moneyShort(product.max_amount)}
                </b>
              </div>
              <div>
                <span>Срок</span>
                <b>
                  {months(product.min_term_months)} – {months(product.max_term_months)}
                </b>
              </div>
              <div>
                <span>Ставка</span>
                <b>{product.version === 3 ? 'от ' : ''}{Number(product.annual_rate_percent)}% годовых</b>
              </div>
            </div>
          ) : (
            <Skeleton h={60} />
          )}
          <div className="row wrap" style={{ marginTop: 28 }}>
            <Button
              variant="lime"
              size="lg"
              loading={start.isPending}
              disabled={!company || !product}
              onClick={() => company && product && start.mutate({ companyId: company.id, productId: product.id })}
            >
              Подобрать финансирование <Arrow />
            </Button>
            <span className="ov-note">Предварительный расчёт — до отправки. Решение — после проверок.</span>
          </div>
          <div className="ov-deco" aria-hidden="true">
            <Keycap label="₽" size={110} rot={-8} color="var(--lime)" />
            <PixelCursor size={70} className="ov-cursor" />
          </div>
        </section>

        {draft ? <DraftCard draft={draft} /> : <HowCard />}
      </div>

      <div className="section-head">
        <h2>Мои обращения</h2>
        <Link to="/applications" className="link-btn">
          Все заявки
        </Link>
      </div>
      {apps.isLoading ? (
        <div className="grid grid-3">
          <Skeleton h={190} r={22} />
          <Skeleton h={190} r={22} />
          <Skeleton h={190} r={22} />
        </div>
      ) : active.length === 0 && !draft ? (
        <div className="card empty">
          <PixelArt shape="doc" size={9} color="var(--line-2)" />
          <div>
            <b style={{ color: 'var(--ink)' }}>Заявок пока нет</b>
            <p>Начните с подбора финансирования — черновик сохранится автоматически.</p>
          </div>
        </div>
      ) : (
        <div className="grid grid-3 stagger">
          {(active.length ? active : [draft!]).slice(0, 6).map((a) => (
            <AppCard key={a.id} app={a} />
          ))}
        </div>
      )}

      <div className="section-head">
        <h2>Как проходит заявка</h2>
      </div>
      <div className="grid grid-4 path-cards stagger">
        {[
          { n: '1', t: 'Потребность', d: 'Цель, сумма и срок. Платёж считаем сразу.', c: 'red' },
          { n: '2', t: 'Сведения', d: 'Реквизиты и финансы уже заполнены из профиля компании.', c: 'red' },
          { n: '3', t: 'Проверки', d: 'Юридический статус, кредитная история и правила продукта.', c: 'red' },
          { n: '4', t: 'Решение', d: 'Одобрение, отказ, уточнение или разбор специалистом.', c: 'red' },
        ].map((s) => (
          <div key={s.n} className="card path-card">
            <span className={`big-n ${s.c}`}>{s.n}</span>
            <h3>{s.t}</h3>
            <p className="muted">{s.d}</p>
          </div>
        ))}
      </div>

      {company && (
        <>
          <div className="section-head">
            <h2>Компания</h2>
            <Link to="/company" className="link-btn">
              Профиль
            </Link>
          </div>
          <div className="card ov-company">
            <div>
              <h3 className="card-title" style={{ fontSize: 22 }}>
                {company.legal_name}
              </h3>
              <p className="muted" style={{ marginTop: 6 }}>
                {company.business_description}
              </p>
              <dl className="kv" style={{ marginTop: 18 }}>
                <dt>ИНН</dt>
                <dd className="num">{company.inn}</dd>
                <dt>ОКВЭД</dt>
                <dd>{company.okved_code}</dd>
                <dt>Регион</dt>
                <dd>{company.region_code}</dd>
              </dl>
            </div>
            <div>{detail.data ? <CashflowBars months={detail.data.financial_months} height={170} /> : <Skeleton h={170} />}</div>
          </div>
        </>
      )}
    </div>
  )
}

function DraftCard({ draft }: { draft: Draft }) {
  const idx = Math.max(0, STEPS.findIndex((s) => s.id === draft.ui_step))
  const needsInfo = draft.status === 'NEEDS_INFO'
  return (
    <Link to={`/applications/${draft.id}`} className={`panel ${needsInfo ? 'violet' : 'lime'} dots ov-draft`}>
      <span className={`tag ${needsInfo ? 'white' : 'ink'}`}>{needsInfo ? 'Нужны уточнения' : 'Черновик сохранён'}</span>
      <h3 className="ov-draft-title">{needsInfo ? 'Банк ждёт ваших уточнений' : 'Продолжите с того же места'}</h3>
      <div className="ov-draft-amount display num">{draft.requested_amount ? money(draft.requested_amount) : 'Сумма не указана'}</div>
      <div className="ov-steps">
        {STEPS.map((s, i) => (
          <div key={s.id} className={i < idx ? 'done' : i === idx ? 'cur' : ''}>
            <i />
            <span>{s.title}</span>
          </div>
        ))}
      </div>
      <span className="ov-draft-go">
        Открыть <Arrow />
      </span>
    </Link>
  )
}

function HowCard() {
  return (
    <div className="panel violet dots ov-draft ov-ai">
      <div className="row between">
        <span className="tag white">ИИ-помощник</span>
        <PixelArt shape="smile" size={5} gap={1.5} color="var(--lime)" animate={false} />
      </div>
      <h3 className="ov-draft-title">ИИ объяснит расчёт и сравнит варианты</h3>
      <p className="ov-ai-text">В заявке помощник разберёт платёж и нагрузку, сравнит меньшую сумму и более длинный срок и подскажет следующий шаг.</p>
      <ul className="ov-ai-list">
        <li>Объяснит расчёт простыми словами</li>
        <li>Сравнит три варианта суммы и срока</li>
        <li>Не принимает решение и не меняет заявку</li>
      </ul>
      <span className="ov-ai-foot">Работает на локальной модели с открытыми весами</span>
    </div>
  )
}

export function AppCard({ app }: { app: Draft }) {
  const s = STATUS[app.status]
  return (
    <Link to={`/applications/${app.id}`} className="card hover app-card" style={{ ['--accent' as string]: s.color }}>
      <div className="row between">
        <StatusChip status={app.status} />
        <span className="hint">{relative(app.updated_at)}</span>
      </div>
      <div className="app-card-amount display num">{app.requested_amount ? money(app.requested_amount) : '—'}</div>
      <div className="app-card-meta">
        <span>{months(app.term_months)}</span>
        <span>·</span>
        <span>{app.purpose_code ? PURPOSE[app.purpose_code].label : 'Цель не выбрана'}</span>
      </div>
      {app.decision?.monthly_payment && (app.status === 'APPROVED' || app.status === 'SIGNED') && (
        <div className="app-card-pay">
          Платёж <b className="num">{money(app.decision.monthly_payment)}</b> / мес
        </div>
      )}
      <span className="app-card-go">
        <Arrow />
      </span>
    </Link>
  )
}
