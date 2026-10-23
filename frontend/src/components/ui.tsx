import { createContext, useCallback, useContext, useEffect, useRef, useState, type ButtonHTMLAttributes, type ReactNode } from 'react'
import { createPortal } from 'react-dom'
import { ApiError } from '../api/client'
import type { ApplicationStatus, ProvenanceItem, Reason, RiskBand } from '../api/types'
import { dateTime, date } from '../lib/format'
import { PROVENANCE, RISK, STATUS } from '../lib/labels'

/* ---------------- Button ---------------- */
type BtnVariant = 'ink' | 'red' | 'lime' | 'blue' | 'violet' | 'white' | 'ghost'
export function Button({
  variant = 'ink',
  size,
  block,
  loading,
  onDark,
  className,
  children,
  disabled,
  ...rest
}: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: BtnVariant; size?: 'sm' | 'lg'; block?: boolean; loading?: boolean; onDark?: boolean }) {
  const cls = ['btn', variant !== 'ink' && variant, size, block && 'block', onDark && 'on-dark', className].filter(Boolean).join(' ')
  return (
    <button className={cls} disabled={disabled || loading} {...rest}>
      {loading && <span className="spin" aria-hidden="true" />}
      {children}
    </button>
  )
}

export function Arrow({ dir = 'right', size = 16 }: { dir?: 'right' | 'left' | 'up' | 'down'; size?: number }) {
  const rot = { right: 0, down: 90, left: 180, up: -90 }[dir]
  return (
    <svg width={size} height={size} viewBox="0 0 16 16" style={{ transform: `rotate(${rot}deg)` }} aria-hidden="true">
      <path d="M2 8h11M9 3.5 13.5 8 9 12.5" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="square" />
    </svg>
  )
}

export function CheckIcon({ size = 14, color = 'currentColor' }: { size?: number; color?: string }) {
  return (
    <svg width={size} height={size} viewBox="0 0 14 14" aria-hidden="true">
      <path d="M2 7.5 5.5 11 12 3.5" fill="none" stroke={color} strokeWidth="2.6" strokeLinecap="square" />
    </svg>
  )
}

/* ---------------- Status, risk, provenance ---------------- */
export function StatusChip({ status, live }: { status: ApplicationStatus; live?: boolean }) {
  const s = STATUS[status]
  const isLive = live ?? (status === 'SUBMITTED' || status === 'CHECKING')
  return (
    <span className={`chip s-${s.tone} ${isLive ? 'live' : ''}`}>
      <i className="dot" />
      {s.label}
    </span>
  )
}

export function RiskMeter({ score, band, compact }: { score: number | null; band: RiskBand; compact?: boolean }) {
  const r = RISK[band]
  const pct = score === null ? 0 : Math.min(100, score)
  return (
    <div className={`risk ${compact ? 'compact' : ''}`} title={r.label}>
      <div className="risk-bars">
        {Array.from({ length: 10 }, (_, i) => (
          <i key={i} style={{ background: score !== null && i < Math.ceil(pct / 10) ? r.color : undefined, animationDelay: `${i * 0.04}s` }} />
        ))}
      </div>
      <span className="risk-val num">{score ?? '—'}</span>
      {!compact && <span className="risk-lbl">{r.label}</span>}
    </div>
  )
}

export function ProvenanceBadge({ item, label }: { item: ProvenanceItem | null | undefined; label?: string }) {
  if (!item) return null
  const p = PROVENANCE[item.source]
  return (
    <span className={`src ${p.mock ? 'mock' : ''}`} title={item.checked_at ? `Проверено ${dateTime(item.checked_at)}` : undefined}>
      {label && <b>{label}:</b>}
      {p.label} · данные на {date(item.as_of_date)}
      {item.checked_at && <> · проверено {dateTime(item.checked_at)}</>}
    </span>
  )
}

export function Reasons({ items }: { items: Reason[] }) {
  if (!items.length) return null
  return (
    <ul className="reasons">
      {items.map((r) => (
        <li key={r.code}>
          <code>{r.code}</code>
          <span>{r.message}</span>
        </li>
      ))}
    </ul>
  )
}

/* ---------------- Notice ---------------- */
export function Notice({ tone = 'info', title, children, icon }: { tone?: 'info' | 'warn' | 'error' | 'ok' | 'plain'; title?: ReactNode; children?: ReactNode; icon?: ReactNode }) {
  const ic = icon ?? { info: 'i', warn: '!', error: '×', ok: '✓', plain: '•' }[tone]
  return (
    <div className={`notice ${tone}`} role={tone === 'error' ? 'alert' : undefined}>
      <span className="ic">{ic}</span>
      <div>
        {title && <div className="t">{title}</div>}
        {children}
      </div>
    </div>
  )
}

export function ErrorNotice({ error, onRetry }: { error: unknown; onRetry?: () => void }) {
  if (!error) return null
  const e = error instanceof ApiError ? error : null
  return (
    <Notice tone="error" title={e?.message ?? 'Что-то пошло не так'}>
      {e?.fieldErrors.length ? (
        <ul style={{ margin: '4px 0 0', paddingLeft: 18 }}>
          {e.fieldErrors.map((f) => (
            <li key={f.field}>{f.message}</li>
          ))}
        </ul>
      ) : null}
      {e?.requestId && <div className="hint" style={{ marginTop: 6 }}>request_id: {e.requestId}</div>}
      {onRetry && (
        <div style={{ marginTop: 10 }}>
          <Button size="sm" variant="white" onClick={onRetry}>
            Повторить
          </Button>
        </div>
      )}
    </Notice>
  )
}

/* ---------------- Checkbox ---------------- */
export function Checkbox({ checked, onChange, title, desc, disabled }: { checked: boolean; onChange: (v: boolean) => void; title: ReactNode; desc?: ReactNode; disabled?: boolean }) {
  return (
    <label className={`check ${checked ? 'on' : ''}`} style={disabled ? { opacity: 0.55, cursor: 'not-allowed' } : undefined}>
      <input type="checkbox" checked={checked} disabled={disabled} onChange={(e) => onChange(e.target.checked)} />
      <span className="box">
        <CheckIcon color="var(--lime)" size={15} />
      </span>
      <span>
        <span className="t">{title}</span>
        {desc && <span className="d" style={{ display: 'block' }}>{desc}</span>}
      </span>
    </label>
  )
}

/* ---------------- Skeleton / spinner ---------------- */
export function Skeleton({ h = 18, w = '100%', r }: { h?: number; w?: number | string; r?: number }) {
  return <div className="skel" style={{ height: h, width: w, borderRadius: r }} />
}

export function PageLoader() {
  return (
    <div className="page">
      <div className="stack-lg" style={{ marginTop: 30 }}>
        <Skeleton h={54} w="45%" />
        <Skeleton h={18} w="30%" />
        <div className="grid grid-3" style={{ marginTop: 16 }}>
          <Skeleton h={180} r={22} />
          <Skeleton h={180} r={22} />
          <Skeleton h={180} r={22} />
        </div>
      </div>
    </div>
  )
}

/* ---------------- Tabs & segmented ---------------- */
export function Tabs<T extends string>({ value, onChange, items }: { value: T; onChange: (v: T) => void; items: { id: T; label: ReactNode }[] }) {
  return (
    <div className="tabs" role="tablist">
      {items.map((it) => (
        <button key={it.id} role="tab" aria-selected={value === it.id} className={value === it.id ? 'on' : ''} onClick={() => onChange(it.id)}>
          {it.label}
        </button>
      ))}
    </div>
  )
}

/* ---------------- Modal ---------------- */
export function Modal({ open, onClose, children, width }: { open: boolean; onClose: () => void; children: ReactNode; width?: number }) {
  useEffect(() => {
    if (!open) return
    const h = (e: KeyboardEvent) => e.key === 'Escape' && onClose()
    window.addEventListener('keydown', h)
    const prev = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    return () => {
      window.removeEventListener('keydown', h)
      document.body.style.overflow = prev
    }
  }, [open, onClose])
  if (!open) return null
  return createPortal(
    <div className="modal-back" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className="modal" role="dialog" aria-modal="true" style={width ? { width: `min(${width}px, 100%)` } : undefined}>
        {children}
      </div>
    </div>,
    document.body,
  )
}

/* ---------------- Toasts ---------------- */
interface Toast {
  id: number
  tone: 'ok' | 'error' | 'info'
  title: string
  message?: string
  requestId?: string
}
const ToastCtx = createContext<{ push: (t: Omit<Toast, 'id'>) => void; error: (e: unknown, title?: string) => void }>({ push: () => {}, error: () => {} })

export function ToastProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<Toast[]>([])
  const seq = useRef(0)
  const push = useCallback((t: Omit<Toast, 'id'>) => {
    const id = ++seq.current
    setItems((x) => [...x.slice(-3), { ...t, id }])
    setTimeout(() => setItems((x) => x.filter((i) => i.id !== id)), t.tone === 'error' ? 7000 : 4200)
  }, [])
  const error = useCallback(
    (e: unknown, title?: string) => {
      const a = e instanceof ApiError ? e : null
      push({ tone: 'error', title: title ?? a?.message ?? 'Ошибка', message: title ? a?.message : a?.fieldErrors.map((f) => f.message).join('; ') || undefined, requestId: a?.requestId })
    },
    [push],
  )
  return (
    <ToastCtx.Provider value={{ push, error }}>
      {children}
      {createPortal(
        <div className="toasts" aria-live="polite">
          {items.map((t) => (
            <div key={t.id} className={`toast ${t.tone}`}>
              <span className="bar" />
              <div>
                <div className="t">{t.title}</div>
                {t.message && <div className="m">{t.message}</div>}
                {t.requestId && <div className="rid">request_id {t.requestId}</div>}
              </div>
            </div>
          ))}
        </div>,
        document.body,
      )}
    </ToastCtx.Provider>
  )
}
export const useToast = () => useContext(ToastCtx)

/* ---------------- Animated number ---------------- */
export function AnimatedNumber({ value, format, duration = 700 }: { value: number | null; format: (n: number) => string; duration?: number }) {
  const [shown, setShown] = useState<number | null>(value)
  const from = useRef<number | null>(value)
  useEffect(() => {
    if (value === null) {
      setShown(null)
      from.current = null
      return
    }
    const start = from.current ?? value * 0.6
    const t0 = performance.now()
    let raf = 0
    const tick = (t: number) => {
      const k = Math.min(1, (t - t0) / duration)
      const e = 1 - Math.pow(1 - k, 4)
      setShown(start + (value - start) * e)
      if (k < 1) raf = requestAnimationFrame(tick)
      else from.current = value
    }
    raf = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(raf)
  }, [value, duration])
  return <>{shown === null ? '—' : format(shown)}</>
}

/* ---------------- Section heading ---------------- */
export function SectionTitle({ n, color, children, aside }: { n?: string; color?: 'red' | 'violet' | 'blue' | 'ink'; children: ReactNode; aside?: ReactNode }) {
  return (
    <div className="card-head">
      <div className="row">
        {n && <span className={`nb ${color ?? ''}`}>{n}</span>}
        <h3 className="card-title">{children}</h3>
      </div>
      {aside}
    </div>
  )
}

export function Stat({ k, v, sub }: { k: ReactNode; v: ReactNode; sub?: ReactNode }) {
  return (
    <div className="stat">
      <div className="k">{k}</div>
      <div className="v">{v}</div>
      {sub && <div className="hint" style={{ marginTop: 4 }}>{sub}</div>}
    </div>
  )
}
