import { money, monthName } from '../lib/format'
import { FIN_FIELDS } from '../lib/labels'

export interface FinRow {
  month: string
  cash_inflow: string | null
  operating_outflow: string | null
  existing_debt_payment: string | null
}

/** One table for monthly financials everywhere: fixed columns, right-aligned figures, optional cash-flow total. */
export function FinTable({ rows, showFlow = true, missingLabel = 'не указано' }: { rows: FinRow[]; showFlow?: boolean; missingLabel?: string }) {
  if (!rows.length) return null
  const cell = (v: string | null) => (v === null ? <span className="ft-missing">{missingLabel}</span> : money(v))
  return (
    <div className="ft-wrap">
      <table className="ft">
        <colgroup>
          <col className="ft-c-month" />
          {FIN_FIELDS.map((f) => (
            <col key={f.key} />
          ))}
          {showFlow && <col />}
        </colgroup>
        <thead>
          <tr>
            <th>Месяц</th>
            {FIN_FIELDS.map((f) => (
              <th key={f.key} className="r" title={f.hint}>
                {f.label}
              </th>
            ))}
            {showFlow && <th className="r">Поток</th>}
          </tr>
        </thead>
        <tbody>
          {rows.map((m) => {
            const flow = m.cash_inflow !== null && m.operating_outflow !== null ? Number(m.cash_inflow) - Number(m.operating_outflow) : null
            return (
              <tr key={m.month}>
                <td className="ft-month">{monthName(m.month)}</td>
                {FIN_FIELDS.map((f) => (
                  <td key={f.key} className="r">
                    {cell(m[f.key])}
                  </td>
                ))}
                {showFlow && <td className={`r ft-flow ${flow !== null && flow <= 0 ? 'neg' : ''}`}>{flow === null ? '—' : money(flow)}</td>}
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}
