import { useEffect } from 'react'
import { createBrowserRouter, createHashRouter, Navigate, Outlet, RouterProvider, useLocation, useNavigate } from 'react-router-dom'
import { AppShell } from './components/AppShell'
import { useSession } from './lib/session'
import { LoginPage } from './pages/Login'
import { OverviewPage } from './pages/client/Overview'
import { ApplicationsPage } from './pages/client/Applications'
import { ApplicationPage } from './pages/client/Application'
import { CompanyPage } from './pages/client/Company'
import { QueuePage } from './pages/bank/Queue'
import { BankCardPage } from './pages/bank/BankCardPage'
import { PageLoader } from './components/ui'
import type { Role } from './api/types'

function RequireRole({ role }: { role: Role }) {
  const { user, loading } = useSession()
  const loc = useLocation()
  if (loading) return <PageLoader />
  if (!user) return <Navigate to="/login" replace state={{ from: loc.pathname }} />
  if (user.role !== role) return <Navigate to={user.role === 'BANK_STAFF' ? '/bank' : '/overview'} replace />
  return <Outlet />
}

function Home() {
  const { user, loading } = useSession()
  if (loading) return <PageLoader />
  if (!user) return <Navigate to="/login" replace />
  return <Navigate to={user.role === 'BANK_STAFF' ? '/bank' : '/overview'} replace />
}

/** Sends the user to the login screen whenever the session disappears (expired, revoked, logout elsewhere). */
function SessionGuard() {
  const { user, loading } = useSession()
  const nav = useNavigate()
  const loc = useLocation()
  useEffect(() => {
    if (!loading && !user && loc.pathname !== '/login') nav('/login', { replace: true, state: { from: loc.pathname, expired: true } })
  }, [user, loading, loc.pathname, nav])
  return <Outlet />
}

const routes = [
  {
    element: <SessionGuard />,
    children: [
      { path: '/login', element: <LoginPage /> },
      { path: '/', element: <Home /> },
      {
        element: <RequireRole role="CLIENT" />,
        children: [
          {
            element: <AppShell />,
            children: [
              { path: '/overview', element: <OverviewPage /> },
              { path: '/applications', element: <ApplicationsPage /> },
              { path: '/applications/:id', element: <ApplicationPage /> },
              { path: '/company', element: <CompanyPage /> },
            ],
          },
        ],
      },
      {
        element: <RequireRole role="BANK_STAFF" />,
        children: [
          {
            element: <AppShell />,
            children: [
              { path: '/bank', element: <QueuePage mode="active" /> },
              { path: '/bank/decisions', element: <QueuePage mode="final" /> },
              { path: '/bank/applications/:id', element: <BankCardPage /> },
            ],
          },
        ],
      },
      { path: '*', element: <Navigate to="/" replace /> },
    ],
  },
]

const router = import.meta.env.VITE_ROUTER === 'hash' ? createHashRouter(routes) : createBrowserRouter(routes)

export default function App() {
  return <RouterProvider router={router} />
}
