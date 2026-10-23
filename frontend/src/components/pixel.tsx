import { useId, type CSSProperties } from 'react'

/* Pixel motifs from the case visuals: drawn from string maps, pixels pop in one by one. */
const SHAPES = {
  smile: [
    '..XXXXX..',
    '.X.....X.',
    'X..X.X..X',
    'X.......X',
    'X.X...X.X',
    'X..XXX..X',
    '.X.....X.',
    '..XXXXX..',
  ],
  heart: [
    '.XX...XX.',
    'XXXX.XXXX',
    'XXXXXXXXX',
    'XXXXXXXXX',
    '.XXXXXXX.',
    '..XXXXX..',
    '...XXX...',
    '....X....',
  ],
  cross: [
    'XX.....XX',
    '.XX...XX.',
    '..XX.XX..',
    '...XXX...',
    '..XX.XX..',
    '.XX...XX.',
    'XX.....XX',
  ],
  hourglass: [
    'XXXXXXX',
    '.X...X.',
    '..X.X..',
    '...X...',
    '..X.X..',
    '.X.X.X.',
    'XXXXXXX',
  ],
  question: [
    '.XXXXX.',
    'XX...XX',
    '.....XX',
    '...XXX.',
    '...XX..',
    '.......',
    '...XX..',
  ],
  check: [
    '........X',
    '.......XX',
    '......XX.',
    'X....XX..',
    'XX..XX...',
    '.XXXX....',
    '..XX.....',
  ],
  bolt: [
    '....XXX',
    '...XXX.',
    '..XXX..',
    '.XXXXXX',
    '....XX.',
    '...XX..',
    '..X....',
  ],
  doc: [
    'XXXXX..',
    'X...XX.',
    'X...XXX',
    'X.....X',
    'X.XXX.X',
    'X.....X',
    'X.XXX.X',
    'XXXXXXX',
  ],
} as const

export type PixelShape = keyof typeof SHAPES

export function PixelArt({
  shape,
  size = 10,
  color = 'currentColor',
  gap = 2,
  animate = true,
  className,
  style,
}: {
  shape: PixelShape
  size?: number
  color?: string
  gap?: number
  animate?: boolean
  className?: string
  style?: CSSProperties
}) {
  const rows = SHAPES[shape]
  const w = rows[0].length
  const h = rows.length
  const cells: { x: number; y: number; i: number }[] = []
  let i = 0
  rows.forEach((r, y) => [...r].forEach((c, x) => c === 'X' && cells.push({ x, y, i: i++ })))
  const step = size + gap
  return (
    <svg
      className={className}
      style={style}
      width={w * step - gap}
      height={h * step - gap}
      viewBox={`0 0 ${w * step - gap} ${h * step - gap}`}
      aria-hidden="true"
    >
      {cells.map((c) => (
        <rect
          key={`${c.x}-${c.y}`}
          x={c.x * step}
          y={c.y * step}
          width={size}
          height={size}
          rx={size * 0.18}
          fill={color}
          style={
            animate
              ? {
                  transformOrigin: `${c.x * step + size / 2}px ${c.y * step + size / 2}px`,
                  animation: `pop 0.4s var(--ease-out) both`,
                  animationDelay: `${0.15 + c.i * 0.022}s`,
                }
              : undefined
          }
        />
      ))}
    </svg>
  )
}

// Classic pointer outline; corners are softened by a round-joined stroke of the same paint.
const ARROW = 'M14 10 L14 94 L35 75 L50 110 L67 103 L52 68 L82 68 Z'

/** Soft, rounded 3D pointer: smooth extrusion, crisp seam, bevelled glossy face, contact shadow. */
export function Cursor3D({ size = 120, className, style, tint = 'lavender' }: { size?: number; className?: string; style?: CSSProperties; tint?: 'lavender' | 'warm' }) {
  const id = useId().replace(/:/g, '')
  const side = tint === 'warm' ? ['#f1ecf6', '#cfc3dc', '#9b86a8'] : ['#e2ddf6', '#b3aad8', '#7b6fa8']
  const depth = 26
  const u = (k: string) => `url(#${id}${k})`
  return (
    <svg className={className} style={style} width={size} height={size * 1.3} viewBox="0 0 100 130" aria-hidden="true" overflow="visible">
      <defs>
        <linearGradient id={`${id}f`} x1=".1" y1="0" x2=".9" y2="1">
          <stop offset="0" stopColor="#ffffff" />
          <stop offset=".55" stopColor="#f6f5fb" />
          <stop offset="1" stopColor="#dedbec" />
        </linearGradient>
        <linearGradient id={`${id}s`} x1="0" y1="0" x2="1" y2="1">
          <stop offset="0" stopColor={side[0]} />
          <stop offset=".5" stopColor={side[1]} />
          <stop offset="1" stopColor={side[2]} />
        </linearGradient>
        <radialGradient id={`${id}g`} cx=".28" cy=".18" r=".6">
          <stop offset="0" stopColor="#fff" stopOpacity="1" />
          <stop offset=".6" stopColor="#fff" stopOpacity=".25" />
          <stop offset="1" stopColor="#fff" stopOpacity="0" />
        </radialGradient>
        <filter id={`${id}b`} x="-50%" y="-50%" width="200%" height="200%">
          <feGaussianBlur stdDeviation="7" />
        </filter>
        <filter id={`${id}b2`} x="-20%" y="-20%" width="140%" height="140%">
          <feGaussianBlur stdDeviation="1.8" />
        </filter>
        {/* Rounded bevel as two inner shadows: shade along the lower-right edge, light along the upper-left. */}
        <filter id={`${id}v`} x="-20%" y="-20%" width="140%" height="140%">
          <feFlood floodColor={side[2]} floodOpacity=".42" result="dk" />
          <feComposite in="dk" in2="SourceAlpha" operator="out" result="dkOut" />
          <feOffset in="dkOut" dx="-4.5" dy="-6" result="dkOff" />
          <feGaussianBlur in="dkOff" stdDeviation="3.4" result="dkBlur" />
          <feComposite in="dkBlur" in2="SourceAlpha" operator="in" result="dark" />
          <feFlood floodColor="#ffffff" floodOpacity="1" result="lt" />
          <feComposite in="lt" in2="SourceAlpha" operator="out" result="ltOut" />
          <feOffset in="ltOut" dx="3.5" dy="4.5" result="ltOff" />
          <feGaussianBlur in="ltOff" stdDeviation="2.6" result="ltBlur" />
          <feComposite in="ltBlur" in2="SourceAlpha" operator="in" result="light" />
          <feMerge>
            <feMergeNode in="SourceGraphic" />
            <feMergeNode in="dark" />
            <feMergeNode in="light" />
          </feMerge>
        </filter>
        <clipPath id={`${id}c`}>
          <path d={ARROW} stroke="#000" strokeWidth="14" strokeLinejoin="round" />
        </clipPath>
      </defs>
      {/* contact shadow: soft wide blur plus a tighter core near the object */}
      <path d={ARROW} transform="translate(16 24)" fill="#3a0a06" opacity=".22" stroke="#3a0a06" strokeWidth="18" strokeLinejoin="round" filter={u('b')} />
      <path d={ARROW} transform="translate(10 15)" fill="#3a0a06" opacity=".18" stroke="#3a0a06" strokeWidth="14" strokeLinejoin="round" filter={u('b2')} />
      {/* extrusion: many thin layers read as a smooth rounded side */}
      {Array.from({ length: depth }, (_, i) => depth - i).map((i) => (
        <path key={i} d={ARROW} transform={`translate(${i * 0.34} ${i * 0.46})`} fill={u('s')} stroke={u('s')} strokeWidth="14" strokeLinejoin="round" />
      ))}
      {/* seam between side and face */}
      <path d={ARROW} fill="none" stroke={side[2]} strokeOpacity=".25" strokeWidth="15" strokeLinejoin="round" transform="translate(.5 .7)" />
      {/* face */}
      <path d={ARROW} fill={u('f')} stroke={u('f')} strokeWidth="14" strokeLinejoin="round" filter={u('v')} />
      <g clipPath={u('c')}>
        <ellipse cx="28" cy="36" rx="30" ry="42" fill={u('g')} />
        {/* specular glints */}
        <ellipse cx="17" cy="24" rx="2.6" ry="7" fill="#fff" transform="rotate(-8 17 24)" />
      </g>
    </svg>
  )
}

/** @deprecated kept for compatibility; renders the soft 3D pointer. */
export const PixelCursor = ({ size, className, style }: { size?: number; className?: string; style?: CSSProperties }) => <Cursor3D size={size} className={className} style={style} />

/** Decorative 3D keycap. */
export function Keycap({ label, color = 'var(--lime)', fg = '#fff', size = 96, rot = 0, className, style }: { label: React.ReactNode; color?: string; fg?: string; size?: number; rot?: number; className?: string; style?: CSSProperties }) {
  return (
    <div
      className={`keycap ${className ?? ''}`}
      style={{ '--kc': color, '--kfg': fg, '--ks': `${size}px`, '--rot': `${rot}deg`, ...style } as CSSProperties}
      aria-hidden="true"
    >
      <span>{label}</span>
    </div>
  )
}

export function Logo({ onDark = false, compact = false }: { onDark?: boolean; compact?: boolean }) {
  return (
    <span className={`logo ${onDark ? 'on-dark' : ''}`}>
      <span className="logo-mark">
        <svg viewBox="0 0 96 120" width="17" height="22" aria-hidden="true" overflow="visible">
          <path d={ARROW} fill="currentColor" stroke="currentColor" strokeWidth="16" strokeLinejoin="round" />
        </svg>
      </span>
      {!compact && (
        <span className="logo-text">
          <b>Кредитный</b>
          <b>кабинет</b>
        </span>
      )}
    </span>
  )
}
