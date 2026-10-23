import { useQuery, useQueryClient } from '@tanstack/react-query'
import { createContext, useCallback, useContext, useEffect, useRef, type ReactNode } from 'react'
import { ApiError, onUnauthorized } from '../api/client'
import { auth } from '../api/endpoints'
import type { SessionResponse, User } from '../api/types'

interface SessionCtx {
  user: User | null
  session: SessionResponse | null
  loading: boolean
  login: (email: string, password: string) => Promise<SessionResponse>
  logout: () => Promise<void>
  expired: boolean
}

const Ctx = createContext<SessionCtx | null>(null)
const ACTIVITY_THROTTLE_MS = 60_000
// Drop every cached query except the session itself (keeps the ['me'] observer attached).
const dropData = (qc: ReturnType<typeof useQueryClient>) => qc.removeQueries({ predicate: (q) => q.queryKey[0] !== 'me' })

export function SessionProvider({ children }: { children: ReactNode }) {
  const qc = useQueryClient()
  const expiredRef = useRef(false)
  const me = useQuery({
    queryKey: ['me'],
    queryFn: async () => {
      try {
        return await auth.me()
      } catch (e) {
        if (e instanceof ApiError && e.status === 401) return null
        throw e
      }
    },
    staleTime: Infinity,
    retry: false,
  })

  // Any 401 from a protected call means the session ended: drop cached data and show login.
  useEffect(() => {
    const off = onUnauthorized(() => {
      if (!qc.getQueryData(['me'])) return
      expiredRef.current = true
      dropData(qc)
      qc.setQueryData(['me'], null)
    })
    return () => {
      off()
    }
  }, [qc])

  // /auth/activity on real interaction only, at most once a minute (backend contract).
  const lastPing = useRef(Date.now())
  const user = me.data?.user ?? null
  useEffect(() => {
    if (!user) return
    const h = () => {
      if (Date.now() - lastPing.current < ACTIVITY_THROTTLE_MS) return
      lastPing.current = Date.now()
      auth.activity().then((s) => qc.setQueryData(['me'], s), () => {})
    }
    window.addEventListener('pointerdown', h, { passive: true })
    window.addEventListener('keydown', h)
    return () => {
      window.removeEventListener('pointerdown', h)
      window.removeEventListener('keydown', h)
    }
  }, [user, qc])

  const login = useCallback(
    async (email: string, password: string) => {
      const s = await auth.login(email, password)
      expiredRef.current = false
      dropData(qc)
      qc.setQueryData(['me'], s)
      return s
    },
    [qc],
  )
  const logout = useCallback(async () => {
    try {
      await auth.logout()
    } catch {
      /* already expired — show login anyway */
    }
    dropData(qc)
    qc.setQueryData(['me'], null)
  }, [qc])

  return (
    <Ctx.Provider value={{ user, session: me.data ?? null, loading: me.isLoading, login, logout, expired: expiredRef.current }}>
      {children}
    </Ctx.Provider>
  )
}

export function useSession() {
  const c = useContext(Ctx)
  if (!c) throw new Error('SessionProvider missing')
  return c
}
