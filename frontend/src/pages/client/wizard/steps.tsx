import { useEffect, useState, type CSSProperties } from 'react'
import { downloadDocument } from '../../../api/client'
import type { Candidate, CompanyDetail, Draft, Product, Purpose } from '../../../api/types'
import { PixelArt, type PixelShape } from '../../../components/pixel'
import { Checkbox, Notice, ProvenanceBadge, SectionTitle, Skeleton, useToast } from '../../../components/ui'
import { date, groupDigits, money, moneyShort, moneyToInput, monthName, months as monthsLabel, parseMoney } from '../../../lib/format'
import { FIN_FIELDS, LEGAL_FORM, PURPOSE, type FinKey } from '../../../lib/labels'
import { CashflowBars } from '../Company'
import { FinTable } from '../../../components/FinTable'
import type { FormState, MonthRow, useDraftEditor } from './useDraftEditor'

type Editor = ReturnType<typeof useDraftEditor>

const PURPOSE_ICON: Record<Purpose, { shape: PixelShape; color: string }> = {
  INVENTORY: { shape: 'doc', color: 'var(--red)' },
  OPERATING_EXPENSES: { shape: 'bolt', color: 'var(--blue)' },
  SEASONAL_PURCHASE: { shape: 'hourglass', color: 'var(--violet)' },
  EQUIPMENT: { shape: 'bolt', color: 'var(--violet)' },
  OTHER: { shape: 'question', color: 'var(--blue)' },
}

function MoneyField({ value, onChange, invalid, label, id, big, placeholder, onEnter }: { value: string; onChange: (v: string) => void; invalid?: string; label?: string; id: string; big?: boolean; placeholder?: string; onEnter?: () => void }) {
  return (
    <div className="field">
      {label && <label htmlFor={id}>{label}</label>}
      <div className={big ? 'money-input' : 'money-sm'}>
        <input
          id={id}
          className={`input num ${invalid ? 'invalid' : ''}`}
          inputMode="decimal"
          autoComplete="off"
          value={value}
          placeholder={placeholder ?? '0'}
          aria-invalid={!!invalid}
          onChange={(e) => {
            const raw = e.target.value.replace(/[^\d.,\s]/g, '')
            onChange(/[.,]/.test(raw) ? raw.replace(/\s/g, '') : groupDigits(raw))
          }}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && onEnter) {
              const p = parseMoney(e.currentTarget.value)
              if (p && p !== 'invalid') onChange(moneyToInput(p))
              onEnter()
            }
          }}
          onBlur={(e) => {
            const p = parseMoney(e.target.value)
            if (p && p !== 'invalid') onChange(moneyToInput(p))
          }}
        />
        <span className="cur">₽</span>
      </div>
      {invalid && <span className="error-text">{invalid}</span>}
    </div>
  )
}

/* ---------------- NEED ---------------- */
export function StepNeed({ ed, product, highlight }: { ed: Editor; product?: Product; highlight: Set<string> }) {
  const { form, update, fieldErrors } = ed
  const min = Number(product?.min_amount ?? 100000)
  const max = Number(product?.max_amount ?? 5000000)
  const tmin = product?.min_term_months ?? 6
  const tmax = product?.max_term_months ?? 60
  const amt = parseMoney(form.amount)
  const amtNum = amt && amt !== 'invalid' ? Number(amt) : null
  const outOfRange = amtNum !== null && (amtNum < min || amtNum > max)
  const sliderVal = Math.min(max, Math.max(min, amtNum ?? min))
  const pct = ((sliderVal - min) / (max - min)) * 100
  const term = form.term ?? tmin
  const tpct = ((Math.min(tmax, Math.max(tmin, term)) - tmin) / (tmax - tmin)) * 100
  const allowed = product?.allowed_purposes ?? (Object.keys(PURPOSE) as Purpose[])
  // Term can be typed: keep the raw text locally, push only whole numbers in range.
  const [termText, setTermText] = useState(form.term ? String(form.term) : '')
  useEffect(() => {
    if (form.term !== null && String(form.term) !== termText) setTermText(String(form.term))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [form.term])
  const termNum = termText ? Number(termText) : null
  const termError = termText && (termNum! < tmin || termNum! > tmax) ? `От ${tmin} до ${tmax} месяцев` : undefined
  const onTermText = (raw: string) => {
    const v = raw.replace(/\D/g, '').slice(0, 3)
    setTermText(v)
    const n = Number(v)
    update({ term: v && n >= tmin && n <= tmax ? n : null }, ['term'])
  }

  return (
    <div className="stack-lg">
      <div className="card">
        <SectionTitle n="01">На что нужны деньги?</SectionTitle>
        <div data-anchor="purpose" className={`purpose-grid ${highlight.has('purpose_code') ? 'hl' : ''}`} role="radiogroup" aria-label="Цель финансирования">
          {allowed.map((p) => {
            const on = form.purpose === p
            return (
              <button key={p} type="button" role="radio" aria-checked={on} className={`purpose ${on ? 'on' : ''}`} onClick={() => update({ purpose: p, partnerPurchase: ['INVENTORY', 'SEASONAL_PURCHASE', 'EQUIPMENT'].includes(p) ? form.partnerPurchase : false }, ['purpose', ...(product?.version === 3 ? ['partner' as const] : [])], true)}>
                <span className="purpose-ic">
                  <PixelArt shape={PURPOSE_ICON[p].shape} size={4.6} gap={1.2} color={on ? 'var(--ink)' : PURPOSE_ICON[p].color} animate={false} />
                </span>
                <b>{PURPOSE[p].label}</b>
                <span>{PURPOSE[p].desc}</span>
                <i className="purpose-check" aria-hidden="true" />
              </button>
            )
          })}
        </div>
        {fieldErrors.purpose_code && <p className="error-text" style={{ marginTop: 10 }}>{fieldErrors.purpose_code}</p>}
        {product?.version === 3 && form.purpose && ['INVENTORY', 'SEASONAL_PURCHASE', 'EQUIPMENT'].includes(form.purpose) && <div data-anchor="draft_data.purchase_from_bank_partner" style={{ marginTop: 18 }}><Checkbox checked={form.partnerPurchase} onChange={v => update({ partnerPurchase: v }, ['partner'], true)} title="Планируется покупка у партнёра банка" desc="Скидка 0,5 п. п. · DEMO: поставщик и документы не проверяются." /></div>}
        {fieldErrors['draft_data.purchase_from_bank_partner'] && <p className="error-text">{fieldErrors['draft_data.purchase_from_bank_partner']}</p>}
        <div className="field" data-anchor="details" style={{ marginTop: 18 }}>
          <label htmlFor="details">Пара слов о задаче · необязательно</label>
          <textarea
            id="details"
            className={`textarea ${highlight.has('purpose_details') ? 'hl-field' : ''}`}
            maxLength={1000}
            value={form.details}
            placeholder="Например: закупка партии товара к ноябрьскому спросу"
            onChange={(e) => update({ details: e.target.value }, ['details'])}
          />
          <span className="hint">{form.details.length}/1000</span>
        </div>
      </div>

      <div className="card">
        <SectionTitle n="02" color="red">
          Сумма и срок
        </SectionTitle>
        <div className={`grid grid-2 ${highlight.has('requested_amount') || highlight.has('term_months') ? 'hl' : ''}`} style={{ gap: 28 }}>
          <div className="stack" data-anchor="amount">
            <MoneyField id="amount" big label="Сумма" value={form.amount} placeholder="1 000 000" invalid={fieldErrors.requested_amount || (outOfRange ? `От ${money(min)} до ${money(max)}` : undefined)} onChange={(v) => update({ amount: v }, ['amount'])} />
            <input
              type="range"
              className="range"
              aria-label="Сумма, ползунок"
              min={min}
              max={max}
              step={50000}
              value={sliderVal}
              style={{ '--pct': `${pct}%` } as CSSProperties}
              onChange={(e) => update({ amount: groupDigits(e.target.value) }, ['amount'])}
            />
            <div className="range-scale">
              <span>{moneyShort(min)}</span>
              <span>{moneyShort(max)}</span>
            </div>
            <div className="quick">
              {[500000, 1000000, 2000000, 3000000].filter((v) => v >= min && v <= max).map((v) => (
                <button key={v} type="button" className={amtNum === v ? 'on' : ''} onClick={() => update({ amount: groupDigits(String(v)) }, ['amount'], true)}>
                  {moneyShort(v)}
                </button>
              ))}
            </div>
          </div>
          <div className="stack" data-anchor="term">
            <div className="field">
              <label htmlFor="term">Срок, в месяцах</label>
              <div className="term-input">
                <input
                  id="term"
                  className={`input num ${termError ? 'invalid' : ''}`}
                  inputMode="numeric"
                  autoComplete="off"
                  value={termText}
                  placeholder="12"
                  aria-invalid={!!termError}
                  onChange={(e) => onTermText(e.target.value)}
                />
                <span className="unit">мес.</span>
              </div>
              {termError && <span className="error-text">{termError}</span>}
              {form.term !== null && <span className="hint">{monthsLabel(form.term)}</span>}
            </div>
            <input
              type="range"
              className="range"
              aria-label="Срок в месяцах, ползунок"
              min={tmin}
              max={tmax}
              step={1}
              value={term}
              style={{ '--pct': `${tpct}%` } as CSSProperties}
              onChange={(e) => update({ term: Number(e.target.value) }, ['term'])}
            />
            <div className="range-scale">
              <span>{monthsLabel(tmin)}</span>
              <span>{monthsLabel(tmax)}</span>
            </div>
            <div className="quick">
              {[6, 12, 24, 36, 48, 60].filter((v) => v >= tmin && v <= tmax).map((v) => (
                <button key={v} type="button" className={form.term === v ? 'on' : ''} onClick={() => update({ term: v }, ['term'], true)}>
                  {monthsLabel(v)}
                </button>
              ))}
            </div>
            {fieldErrors.term_months && <span className="error-text">{fieldErrors.term_months}</span>}
          </div>
        </div>
        {product && (
          <p className="hint" style={{ marginTop: 18 }}>
            {product.name}. {product.version === 3 ? 'Персональная ставка от' : 'Ставка'} {Number(product.annual_rate_percent)}% годовых, аннуитетный платёж. {product.description}
          </p>
        )}
      </div>
    </div>
  )
}

/* ---------------- COMPANY ---------------- */
export function StepCompany({ company, draft }: { company?: CompanyDetail; draft: Draft }) {
  return (
    <div className="stack-lg">
      <div className="card">
        <SectionTitle n="03" color="violet" aside={<ProvenanceBadge item={draft.provenance.company} />}>
          Сведения о компании
        </SectionTitle>
        {!company ? (
          <Skeleton h={220} />
        ) : (
          <div className="company-sheet">
            <div className="company-name">
              <span className="tag sm ink">{LEGAL_FORM[company.legal_form]}</span>
              <h3>{company.legal_name}</h3>
              <p className="muted">{company.business_description}</p>
            </div>
            <div className="company-facts">
              {[
                ['ИНН', company.inn],
                ['ОГРН', company.registration_number ?? '—'],
                ['Регистрация', date(company.registered_on)],
                ['ОКВЭД', company.okved_code],
                ['Регион', company.region_code],
                ['Возраст бизнеса', ageText(company.registered_on, draft.calculation_date)],
              ].map(([k, v]) => (
                <div key={k}>
                  <span>{k}</span>
                  <b className="num">{v}</b>
                </div>
              ))}
            </div>
          </div>
        )}
        <Notice tone="plain" icon="i">
          Реквизиты подтягиваются из профиля и в демо не редактируются. При отправке их дополнительно сверит юридический демо-симулятор.
        </Notice>
      </div>
      <DocumentsCard docs={draft.documents} />
    </div>
  )
}

function ageText(from: string, to: string) {
  const a = new Date(from)
  const b = new Date(to)
  const m = (b.getFullYear() - a.getFullYear()) * 12 + b.getMonth() - a.getMonth()
  const y = Math.floor(m / 12)
  return y >= 1 ? `${y} ${y === 1 ? 'год' : y < 5 ? 'года' : 'лет'}${m % 12 ? ` ${m % 12} мес` : ''}` : `${m} мес`
}

export function DocumentsCard({ docs, title = 'Подготовленные документы', n = '04' }: { docs: Draft['documents']; title?: string; n?: string }) {
  const toast = useToast()
  const [busy, setBusy] = useState<string | null>(null)
  return (
    <div className="card">
      <SectionTitle n={n} color="ink">
        {title}
      </SectionTitle>
      {docs.length === 0 ? (
        <p className="muted">Документов нет.</p>
      ) : (
        <div className="docs">
          {docs.map((d) => (
            <div key={d.id} className="doc">
              <span className="doc-ic">
                <PixelArt shape="doc" size={4} gap={1} color="var(--ink)" animate={false} />
              </span>
              <div className="grow">
                <b>{d.original_filename}</b>
                <div className="hint">
                  {d.kind === 'FINANCIAL_STATEMENT' ? 'Финансовые показатели' : d.kind} · {(d.size_bytes / 1024).toFixed(1)} КБ · {d.source === 'DEMO' ? 'синтетический' : 'загружен'} · SHA-256 {d.content_sha256.slice(0, 10)}…
                </div>
              </div>
              {/* A link, not a button: it must keep working inside a confirmed (disabled) step. */}
              <a
                href={d.download_url}
                role="button"
                className="btn sm white"
                aria-busy={busy === d.id}
                onClick={async (e) => {
                  e.preventDefault()
                  if (busy) return
                  setBusy(d.id)
                  try {
                    await downloadDocument(d.download_url, d.original_filename)
                  } catch (err) {
                    toast.error(err, 'Не удалось скачать документ')
                  } finally {
                    setBusy(null)
                  }
                }}
              >
                {busy === d.id && <span className="spin" aria-hidden="true" />}
                Скачать
              </a>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

/* ---------------- FINANCES ---------------- */
export function StepFinances({ ed, highlight }: { ed: Editor; highlight: Set<string> }) {
  const { form, update, fieldErrors, server } = ed
  // The table is read-only; only cells the bank asked to clarify become editable.
  const editable = (path: string) => highlight.has(path) || highlight.has('draft_data.financial_months')
  const anyEditable = form.months.some((m) => FIN_FIELDS.some((f) => editable(`draft_data.financial_months.${m.month}.${f.key}`)))
  const set = (i: number, k: FinKey, v: string) => {
    const months = form.months.map((m, j) => (j === i ? { ...m, [k]: v } : m))
    update({ months }, ['months'])
  }
  const rows = form.months.map((m) => ({
    month: m.month,
    cash_inflow: num(m.cash_inflow),
    operating_outflow: num(m.operating_outflow),
    existing_debt_payment: num(m.existing_debt_payment),
  }))
  const avg = avgCashflow(form.months)
  const debt = rows.at(-1)?.existing_debt_payment ?? null

  return (
    <div className="stack-lg">
      <div className="card">
        <SectionTitle n="05" color="red" aside={<ProvenanceBadge item={server.provenance.financial_months} />}>
          Финансы за шесть месяцев
        </SectionTitle>
        <CashflowBars months={rows} height={180} />
        <div className="fin-summary">
          <div>
            <span>Средний операционный поток</span>
            <b className="num">{avg === null ? '—' : money(avg)}</b>
          </div>
          <div>
            <span>Платежи по долгам в месяц</span>
            <b className="num">{money(debt)}</b>
          </div>
        </div>
      </div>

      <div className="card" data-anchor="months">
        {anyEditable ? (
          <>
            <Notice tone="info" title="Банк попросил уточнить отмеченные значения">
              Исправьте выделенные ячейки — остальные показатели остаются как в профиле.
            </Notice>
            <div className="fin-card" style={{ padding: 0, marginTop: 16 }}>
              <div className="fin-head">
                <span>Месяц</span>
                {FIN_FIELDS.map((f) => (
                  <span key={f.key}>{f.label}</span>
                ))}
                <span>Поток</span>
              </div>
              {form.months.map((m, i) => {
                const r = rows[i]
                const cf = r.cash_inflow !== null && r.operating_outflow !== null ? Number(r.cash_inflow) - Number(r.operating_outflow) : null
                return (
                  <div className="fin-row" key={m.month}>
                    <span className="fin-month">{monthName(m.month)}</span>
                    {FIN_FIELDS.map((f) => {
                      const path = `draft_data.financial_months.${m.month}.${f.key}`
                      const err = fieldErrors[path]
                      if (!editable(path)) return <span key={f.key} className="fin-static num">{money(r[f.key])}</span>
                      return (
                        <div key={f.key} data-anchor={path} className="fin-cell hl-field">
                          <input
                            className={`input num ${err ? 'invalid' : ''} ${!m[f.key] ? 'empty' : ''}`}
                            inputMode="decimal"
                            aria-label={`${f.label}, ${monthName(m.month)}`}
                            value={m[f.key]}
                            placeholder="не указано"
                            onChange={(e) => {
                              const raw = e.target.value.replace(/[^\d.,\s]/g, '')
                              set(i, f.key, /[.,]/.test(raw) ? raw.replace(/\s/g, '') : groupDigits(raw))
                            }}
                          />
                          {err && <span className="error-text">{err}</span>}
                        </div>
                      )
                    })}
                    <span className={`fin-cf num ${cf !== null && cf <= 0 ? 'neg' : ''}`}>{cf === null ? '—' : moneyShort(cf)}</span>
                  </div>
                )
              })}
            </div>
          </>
        ) : (
          <FinTable rows={rows} />
        )}
        <p className="hint" style={{ marginTop: 14 }}>
          Показатели взяты из профиля компании и в заявке не редактируются. Если банку понадобятся уточнения, он запросит конкретные значения — они станут доступны для исправления.
        </p>
      </div>
    </div>
  )
}

const num = (v: string) => {
  const p = parseMoney(v)
  return p && p !== 'invalid' ? p : null
}

export function avgCashflow(rows: MonthRow[]) {
  const vals = rows.map((m) => (num(m.cash_inflow) !== null && num(m.operating_outflow) !== null ? Number(num(m.cash_inflow)) - Number(num(m.operating_outflow)) : null))
  if (vals.some((v) => v === null) || !vals.length) return null
  return (vals as number[]).reduce((a, b) => a + b, 0) / vals.length
}

/* ---------------- REVIEW ---------------- */
export function StepReview({ ed, company, product, ready, highlight, candidate }: { ed: Editor; company?: CompanyDetail; product?: Product; candidate?: Candidate; ready: ReturnType<typeof import('./useDraftEditor').readiness>; highlight: Set<string> }) {
  const { form, update, fieldErrors, server } = ed
  const needsInfo = server.status === 'NEEDS_INFO'
  return (
    <div className="stack-lg">
      <div className="card">
        <SectionTitle n="06">Проверьте заявку</SectionTitle>
        <div className="review-grid">
          <ReviewItem k="Цель" v={form.purpose ? PURPOSE[form.purpose].label : '—'} />
          <ReviewItem k="Сумма" v={ready.amountNum !== null ? money(ready.amountNum) : '—'} accent />
          <ReviewItem k="Срок" v={monthsLabel(form.term)} accent />
          <ReviewItem k={candidate?.pricing?.status === 'PERSONALIZED' ? 'Предварительная ставка' : product?.version === 3 ? 'Базовая ставка' : 'Ставка'} v={candidate ? `${Number(candidate.annual_rate_percent)}% годовых` : product ? `${product.version === 3 ? 'от ' : ''}${Number(product.annual_rate_percent)}% годовых` : '—'} />
          {product?.version === 3 && <ReviewItem k="Партнёрская покупка · DEMO" v={form.partnerPurchase ? 'Заявлено клиентом' : 'Не заявлена'} />}
          <ReviewItem k="Компания" v={company?.legal_name ?? '—'} />
          <ReviewItem k="Средний поток" v={avgCashflow(form.months) === null ? 'неполные данные' : money(avgCashflow(form.months))} />
        </div>
        {form.details && <p className="review-note">«{form.details}»</p>}
      </div>

      {needsInfo && (
        <div className="card">
          <SectionTitle n="!" color="violet">
            Ответ на запрос банка
          </SectionTitle>
          <textarea
            data-anchor="info"
            className={`textarea ${highlight.has('draft_data.info_response') ? 'hl-field' : ''}`}
            maxLength={1000}
            value={form.infoResponse}
            placeholder="Коротко поясните, что изменили или почему данные такие"
            onChange={(e) => update({ infoResponse: e.target.value }, ['info'])}
          />
          <span className="hint">{form.infoResponse.length}/1000 · Ответ дополняет исправленные поля, но не заменяет их.</span>
        </div>
      )}

      <div className="card">
        <SectionTitle n="07" color="red">
          Подтверждения
        </SectionTitle>
        <div className="stack">
          <div data-anchor="confirm">
          <Checkbox
            checked={form.dataConfirmed}
            onChange={(v) => update({ dataConfirmed: v }, ['confirmations'], true)}
            title="Подтверждаю, что сведения в заявке верны"
            desc="Подтверждение данных, не электронная подпись."
          />
          </div>
          {fieldErrors['draft_data.confirmations.data_confirmed'] && <span className="error-text">{fieldErrors['draft_data.confirmations.data_confirmed']}</span>}
          <div data-anchor="bki">
          <Checkbox
            checked={form.bkiAllowed}
            onChange={(v) => update({ bkiAllowed: v }, ['confirmations'], true)}
            title="Подтверждаю запуск демонстрационной проверки кредитной истории"
            desc="Используются только синтетические данные. Без этого согласия не запускаются БКИ-симулятор, предварительная оценка и AI-разбор."
          />
          </div>
          {fieldErrors['draft_data.confirmations.credit_history_check_allowed'] && <span className="error-text">{fieldErrors['draft_data.confirmations.credit_history_check_allowed']}</span>}
        </div>
      </div>

      {!ready.items.find((i) => i.id === 'months')!.ok && (
        <Notice tone="warn" title="Финансы заполнены не полностью">
          Заявку можно отправить. Банк запросит недостающие показатели; после дозапроса они станут доступны для заполнения на шаге «Финансы».
        </Notice>
      )}
      <DocumentsCard docs={server.documents} title="Документы к отправке" n="08" />
    </div>
  )
}

function ReviewItem({ k, v, accent }: { k: string; v: string; accent?: boolean }) {
  return (
    <div className={`review-item ${accent ? 'accent' : ''}`}>
      <span>{k}</span>
      <b className="num">{v}</b>
    </div>
  )
}

export type { FormState }
