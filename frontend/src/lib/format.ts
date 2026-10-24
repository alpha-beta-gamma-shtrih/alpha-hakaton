const rub = new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 0 })
const rub2 = new Intl.NumberFormat('ru-RU', { minimumFractionDigits: 2, maximumFractionDigits: 2 })

/** Money strings from the API ("1000000.00") → "1 000 000 ₽". */
export function money(v: string | number | null | undefined, opts: { kopecks?: boolean; dash?: string } = {}): string {
  if (v === null || v === undefined || v === '') return opts.dash ?? '—'
  const n = typeof v === 'number' ? v : Number(v)
  if (!Number.isFinite(n)) return String(v)
  return `${(opts.kopecks ? rub2 : rub).format(n)} ₽`
}

export function moneyShort(v: string | number | null | undefined): string {
  if (v === null || v === undefined || v === '') return '—'
  const n = Number(v)
  if (Math.abs(n) >= 1_000_000) return `${(n / 1_000_000).toLocaleString('ru-RU', { maximumFractionDigits: 2 })} млн ₽`
  if (Math.abs(n) >= 1_000) return `${(n / 1_000).toLocaleString('ru-RU', { maximumFractionDigits: 0 })} тыс ₽`
  return money(n)
}

export function percent(v: string | number | null | undefined, digits = 1): string {
  if (v === null || v === undefined || v === '') return '—'
  return `${(Number(v) * 100).toLocaleString('ru-RU', { maximumFractionDigits: digits, minimumFractionDigits: digits })}%`
}

export function rate(v: string | null | undefined): string {
  if (!v) return '—'
  return `${Number(v).toLocaleString('ru-RU', { maximumFractionDigits: 2 })}%`
}

export function months(n: number | null | undefined): string {
  if (n === null || n === undefined) return '—'
  const years = Math.floor(n / 12)
  const rest = n % 12
  return [years ? `${years} ${plural(years, 'год', 'года', 'лет')}` : '', rest || !years ? `${rest} ${plural(rest, 'месяц', 'месяца', 'месяцев')}` : ''].filter(Boolean).join(' ')
}

const dtf = new Intl.DateTimeFormat('ru-RU', { day: 'numeric', month: 'long', hour: '2-digit', minute: '2-digit' })
const df = new Intl.DateTimeFormat('ru-RU', { day: 'numeric', month: 'long', year: 'numeric' })
const mf = new Intl.DateTimeFormat('ru-RU', { month: 'long', year: 'numeric' })
const mshort = new Intl.DateTimeFormat('ru-RU', { month: 'short' })

export const dateTime = (v?: string | null) => (v ? dtf.format(new Date(v)) : '—')
export const date = (v?: string | null) => (v ? df.format(new Date(v.length === 10 ? v + 'T00:00:00' : v)) : '—')
export const monthName = (v: string) => {
  const s = mf.format(new Date(v + 'T00:00:00'))
  return s.charAt(0).toUpperCase() + s.slice(1).replace(' г.', '')
}
export const monthShort = (v: string) => mshort.format(new Date(v + 'T00:00:00')).replace('.', '')

export function relative(v?: string | null): string {
  if (!v) return '—'
  const diff = (Date.now() - new Date(v).getTime()) / 1000
  if (diff < 45) return 'только что'
  if (diff < 3600) return `${Math.round(diff / 60)} мин назад`
  if (diff < 86400) return `${Math.round(diff / 3600)} ч назад`
  return dateTime(v)
}

/** User input → API money string with two decimals. null = empty, 'invalid' = cannot be sent. */
export function parseMoney(raw: string): string | null | 'invalid' {
  const clean = raw.replace(/[\s ]/g, '').replace(',', '.')
  if (!clean) return null
  if (!/^\d{1,16}(\.\d{0,2})?$/.test(clean)) return 'invalid'
  const [i, f = ''] = clean.split('.')
  return `${i.replace(/^0+(?=\d)/, '')}.${(f + '00').slice(0, 2)}`
}

/** API money string → editable text ("1000000.00" → "1 000 000"). */
export function moneyToInput(v: string | null | undefined): string {
  if (!v) return ''
  const [i, f] = v.split('.')
  return groupDigits(f && f !== '00' ? `${i},${f}` : i)
}

export function groupDigits(raw: string): string {
  const [i, f] = raw.replace(/\s/g, '').split(/[.,]/)
  const g = (i || '').replace(/\B(?=(\d{3})+(?!\d))/g, ' ')
  return f !== undefined ? `${g},${f}` : g
}

export function shortId(id: string) {
  return id.slice(0, 8).toUpperCase()
}

export function plural(n: number, one: string, few: string, many: string) {
  const m10 = n % 10
  const m100 = n % 100
  return m10 === 1 && m100 !== 11 ? one : m10 >= 2 && m10 <= 4 && (m100 < 12 || m100 > 14) ? few : many
}
