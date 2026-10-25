import type { OfferTerms } from '../api/types'
import { money, months, percent } from '../lib/format'
import { PricingBreakdown } from './PricingBreakdown'

export function OfferComparison({ terms }: { terms: OfferTerms }) {
  return <div className="offer-comparison">
    <h3 className="card-title">Сравнение условий</h3>
    <div className="table-wrap">
      <table className="table">
        <thead><tr><th>Условия</th><th>Запрос клиента</th><th>Предложение банка</th></tr></thead>
        <tbody>
          <tr><td>Сумма</td><td>{money(terms.original_amount)}</td><td>{money(terms.amount)}</td></tr>
          <tr><td>Срок</td><td>{months(terms.original_term_months)}</td><td>{months(terms.term_months)}</td></tr>
          <tr><td>Ставка</td><td>{Number(terms.original_annual_rate_percent)}%</td><td>{Number(terms.annual_rate_percent)}%</td></tr>
          <tr><td>Платёж в месяц</td><td>{money(terms.original_monthly_payment)}</td><td>{money(terms.monthly_payment)}</td></tr>
        </tbody>
      </table>
    </div>
    <p className="hint">Предложение банка: расчётная сумма выплат {money(terms.estimated_total_payment)}, переплата {money(terms.estimated_overpayment)}, долговая нагрузка {percent(terms.load_ratio)}.</p>
    <PricingBreakdown value={terms.pricing} />
  </div>
}
