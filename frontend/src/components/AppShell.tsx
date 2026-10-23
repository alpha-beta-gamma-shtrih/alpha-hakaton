import { NavLink, Outlet, useLocation, useNavigate } from 'react-router-dom'
import { useSession } from '../lib/session'
import { Logo } from './pixel'

const CLIENT_NAV = [
  { to: '/overview', label: 'Обзор' },
  { to: '/applications', label: 'Мои заявки' },
  { to: '/company', label: 'Компания' },
]
const BANK_NAV = [
  { to: '/bank', label: 'Очередь', end: true },
  { to: '/bank/decisions', label: 'Решения' },
]

export function AppShell() {
  const { user, logout } = useSession()
  const nav = useNavigate()
  const loc = useLocation()
  const isBank = user?.role === 'BANK_STAFF'
  const items = isBank ? BANK_NAV : CLIENT_NAV
  const initials = (user?.display_name || user?.email || '?')
    .split(/\s+/)
    .map((w) => w[0])
    .join('')
    .slice(0, 2)
    .toUpperCase()

  return (
    <div className={`shell ${isBank ? 'bank' : 'client'}`}>
      <header className="topbar">
        <div className="topbar-in">
          <NavLink to={isBank ? '/bank' : '/overview'} className="brand" aria-label="На главную">
            <Logo />
            {isBank && <span className="tag violet sm">Банк</span>}
          </NavLink>
          <nav className="mainnav" aria-label="Основная навигация">
            {items.map((it) => (
              <NavLink key={it.to} to={it.to} end={'end' in it ? Boolean(it.end) : false} className={({ isActive }) => (isActive || (it.to === '/applications' && loc.pathname.startsWith('/applications')) || (it.to === '/bank' && loc.pathname.startsWith('/bank/applications')) ? 'on' : '')}>
                {it.label}
              </NavLink>
            ))}
          </nav>
          <div className="who">
            <span className="avatar" aria-hidden="true">
              {initials}
            </span>
            <span className="who-text">
              <b>{user?.display_name}</b>
              <span>{isBank ? 'Сотрудник банка' : user?.email}</span>
            </span>
            <button
              className="icon-btn"
              title="Выйти"
              aria-label="Выйти"
              onClick={async () => {
                await logout()
                nav('/login', { replace: true })
              }}
            >
              <svg width="18" height="18" viewBox="0 0 18 18" aria-hidden="true">
                <path d="M7 3H3v12h4M11 5l4 4-4 4M15 9H7" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="square" />
              </svg>
            </button>
          </div>
        </div>
      </header>
      <main key={loc.pathname} className="rise" style={{ animationDuration: '0.45s' }}>
        <Outlet />
      </main>
    </div>
  )
}
