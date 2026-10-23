import { useState, type FormEvent } from 'react'
import { Navigate, useLocation, useNavigate } from 'react-router-dom'
import { API_MODE, ApiError } from '../api/client'
import { Cursor3D, Keycap, Logo } from '../components/pixel'
import { Arrow, Button } from '../components/ui'
import { useSession } from '../lib/session'

const DEMO = [
  { email: 'client@example.com', who: 'Клиент · C01', note: 'Устойчивый профиль', tone: 'lime' },
  { email: 'client2@example.com', who: 'Клиент · C02', note: 'Высокая нагрузка', tone: 'cyan' },
  { email: 'bank@example.com', who: 'Сотрудник банка', note: 'Очередь и решения', tone: 'violet' },
]

export function LoginPage() {
  const { user, login } = useSession()
  const nav = useNavigate()
  const loc = useLocation() as { state?: { from?: string; expired?: boolean } }
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState(API_MODE === 'mock' ? 'demo' : '')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<ApiError | null>(null)

  if (user) return <Navigate to={loc.state?.from && loc.state.from !== '/login' ? loc.state.from : '/'} replace />

  const submit = async (e: FormEvent) => {
    e.preventDefault()
    setBusy(true)
    setError(null)
    try {
      const s = await login(email.trim(), password)
      const from = loc.state?.from
      const fits = from && (s.user.role === 'BANK_STAFF' ? from.startsWith('/bank') : !from.startsWith('/bank'))
      nav(fits ? from! : s.user.role === 'BANK_STAFF' ? '/bank' : '/overview', { replace: true })
    } catch (err) {
      setError(err instanceof ApiError ? err : new ApiError(0, null, 'Не удалось войти'))
    } finally {
      setBusy(false)
    }
  }

  const errTitle = error && (error.code === 'NETWORK_ERROR' ? 'Сервер недоступен' : error.status === 401 ? 'Неверный email или пароль' : error.message)
  const errHint =
    error &&
    (error.code === 'NETWORK_ERROR'
      ? 'Проверьте, что backend запущен на :8000.'
      : error.code === 'ORIGIN_FORBIDDEN'
        ? 'Добавьте origin фронтенда в ALLOWED_ORIGINS.'
        : error.status === 429
          ? error.message
          : null)

  return (
    <div className="login">
      <div className="login-bg" aria-hidden="true">
        <div className="hero-word">
          <span>КРЕДИТ</span>
          <span>КАБИНЕТ</span>
        </div>
        <Keycap label="₽" size={150} rot={-10} color="var(--lime)" className="lk lk1" />
        <Keycap label="%" size={96} rot={12} color="var(--cyan)" className="lk lk2" />
        <Keycap label="↑" size={118} rot={8} color="var(--lime)" className="lk lk3" />
        <Keycap label="OK" size={88} rot={-14} color="var(--violet)" className="lk lk4" />
        <Keycap label="₽" size={70} rot={18} color="var(--violet)" className="lk lk5" />
        <Cursor3D size={110} className="lk-cursor" tint="warm" />
      </div>

      <div className="login-grid">
        <section className="login-hero">
          <Logo onDark />
          <div className="login-hero-copy">
            <h1 className="hero-title">
              Умный кредитный кабинет
              <br />
              предпринимателя
            </h1>
            <p className="hero-sub">От потребности в финансировании до решения по заявке — в одном окне. Банк видит ту же заявку и ведёт её дальше.</p>
          </div>
          <div className="hero-facts">
            <div>
              <span className="nb">01</span>
              <p>Подбор суммы и срока с расчётом платежа</p>
            </div>
            <div>
              <span className="nb violet">02</span>
              <p>Проверки ФНС и БКИ — локальные симуляторы</p>
            </div>
            <div>
              <span className="nb ink">03</span>
              <p>Статус и следующий шаг всегда на виду</p>
            </div>
          </div>
        </section>

        <section className="login-side">
          <div className="glass rise">
            <form className="auth-form" onSubmit={submit} noValidate>
                <span className="tag">Вход в кабинет</span>
                <h2>Здравствуйте!</h2>
                <p className="glass-sub">Войдите под демонстрационной учётной записью.</p>

            {loc.state?.expired && !error && (
              <div className="glass-note warn">
                <b>Сессия завершилась.</b> Войдите снова — сохранённые черновики на месте.
              </div>
            )}
            {error && (
              <div className="glass-note error" role="alert">
                <b>{errTitle}</b>
                {errHint && <span> {errHint}</span>}
              </div>
            )}

            <div className="field">
              <label htmlFor="email">Email</label>
              <input id="email" className="glass-input" type="email" autoComplete="username" value={email} onChange={(e) => setEmail(e.target.value)} placeholder="client@example.com" required />
            </div>
            <div className="field">
              <label htmlFor="password">Пароль</label>
              <input id="password" className="glass-input" type="password" autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} required />
              {API_MODE === 'mock' && <span className="glass-hint">В демо-режиме подойдёт любой пароль.</span>}
            </div>
            <Button variant="lime" size="lg" block loading={busy} disabled={!email || !password}>
              Войти <Arrow />
            </Button>

            <div className="demo-accounts">
              <div className="glass-label">Демо-аккаунты</div>
              {DEMO.map((d) => (
                <button type="button" key={d.email} className={`demo-acc ${email === d.email ? 'on' : ''}`} onClick={() => setEmail(d.email)}>
                  <i className={`sw ${d.tone}`} />
                  <span>
                    <b>{d.who}</b>
                    <span>{d.email}</span>
                  </span>
                  <em>{d.note}</em>
                </button>
              ))}
            </div>
            {API_MODE === 'mock' && (
              <button
                type="button"
                className="glass-reset"
                onClick={async () => {
                  const m = await import('../api/mock/server')
                  m.resetDemo()
                  window.location.reload()
                }}
              >
                Сбросить демо-данные
              </button>
            )}
            </form>
          </div>
        </section>
      </div>
    </div>
  )
}
