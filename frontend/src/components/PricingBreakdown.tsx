import { rate } from '../lib/format'

type Component = { code: string; label: string; percentage_points: string }
type Pricing = {
  status?: string
  annual_rate_percent?: string
  base_rate_percent?: string
  minimum_rate_percent?: string
  rate_before_discounts?: string
  applied_discount_pp?: string
  requested_discount_pp?: string
  floor_adjustment_pp?: string
  additions?: Component[]
  discounts?: Component[]
  purchase_from_bank_partner?: boolean
}

/** Both cabinets display the same server calculation; no browser pricing rules. */
export function PricingBreakdown({ value }: { value: unknown }) {
  const p = value as Pricing | null | undefined
  if (!p || p.status === 'FIXED') return null
  if (p.status !== 'PERSONALIZED') return <p className="pricing-note">Персональная ставка пока не определена. Платёж ориентировочный, по базовой ставке {rate(p.annual_rate_percent)}.</p>
  const pp = (v?: string) => Number(v ?? 0).toLocaleString('ru-RU', { maximumFractionDigits: 3 })
  return (
    <details className="pricing-breakdown">
      <summary>Из чего сложилась ставка {rate(p.annual_rate_percent)}</summary>
      <dl>
        <dt>Базовая ставка</dt><dd>{rate(p.base_rate_percent)}</dd>
        {p.additions?.map(c => <div className="pricing-row" key={c.code}><dt>{c.label}</dt><dd>+{pp(c.percentage_points)} п. п.</dd></div>)}
        <dt>До скидок</dt><dd>{rate(p.rate_before_discounts)}</dd>
        {p.discounts?.map(c => <div className="pricing-row" key={c.code}><dt>{c.label}</dt><dd>−{pp(c.percentage_points)} п. п.</dd></div>)}
        <dt>Фактически применённая скидка</dt><dd>−{pp(p.applied_discount_pp)} п. п.</dd>
        <dt>Итоговая ставка</dt><dd><strong>{rate(p.annual_rate_percent)}</strong></dd>
      </dl>
      {Number(p.floor_adjustment_pp) > 0 && <p>Снижение ограничено минимальной ставкой {rate(p.minimum_rate_percent)}. Доступные скидки: {pp(p.requested_discount_pp)} п. п.; применено: {pp(p.applied_discount_pp)} п. п.</p>}
      <p>Целевая программа — DEMO, документы не проверяются.{p.purchase_from_bank_partner && ' Покупка у партнёра заявлена клиентом, поставщик не проверен.'}</p>
    </details>
  )
}
