import type { ApiErrorBody } from './types'

export const API_MODE: 'real' | 'mock' = import.meta.env.VITE_API_MODE === 'mock' ? 'mock' : 'real'

export class ApiError extends Error {
  status: number
  code: string
  fieldErrors: { field: string; message: string }[]
  requestId?: string

  constructor(status: number, body: Partial<ApiErrorBody> | null, fallback: string) {
    super(body?.message || fallback)
    this.status = status
    this.code = body?.code || (status === 0 ? 'NETWORK_ERROR' : `HTTP_${status}`)
    this.fieldErrors = body?.field_errors || []
    this.requestId = body?.request_id
  }

  fieldError(field: string): string | undefined {
    return this.fieldErrors.find((f) => f.field === field || f.field.endsWith('.' + field))?.message
  }
}

export interface TransportResponse {
  status: number
  body: unknown
  headers?: Record<string, string>
}

type Method = 'GET' | 'POST' | 'PATCH' | 'DELETE'

async function httpTransport(method: Method, path: string, body: unknown, headers: Record<string, string>): Promise<TransportResponse> {
  let res: Response
  try {
    res = await fetch(path, {
      method,
      credentials: 'same-origin',
      headers: { Accept: 'application/json', ...(body !== undefined ? { 'Content-Type': 'application/json' } : {}), ...headers },
      body: body !== undefined ? JSON.stringify(body) : undefined,
    })
  } catch {
    return { status: 0, body: { code: 'NETWORK_ERROR', message: 'Сервер недоступен. Проверьте, что backend запущен.' } }
  }
  if (res.status === 204) return { status: 204, body: null }
  const text = await res.text()
  let parsed: unknown = null
  try {
    parsed = text ? JSON.parse(text) : null
  } catch {
    parsed = { code: `HTTP_${res.status}`, message: text.slice(0, 200) }
  }
  const h: Record<string, string> = {}
  const ra = res.headers.get('Retry-After')
  if (ra) h['retry-after'] = ra
  return { status: res.status, body: parsed, headers: h }
}

// The demo server is loaded lazily, so the real build never downloads it.
const mockTransport = import.meta.env.VITE_API_MODE === 'mock'
  ? (method: Method, path: string, body: unknown, headers: Record<string, string>) =>
      import('./mock/server').then((m) => m.mockTransport(method, path, body, headers))
  : httpTransport

// Inline env check so the production build drops the demo server entirely.
const transport = import.meta.env.VITE_API_MODE === 'mock' ? mockTransport : httpTransport

// CSRF token lives only in memory (never in storage), per backend contract.
let csrfToken: string | null = null
let csrfPromise: Promise<string> | null = null

export function resetCsrf() {
  csrfToken = null
  csrfPromise = null
}

async function getCsrf(): Promise<string> {
  if (csrfToken) return csrfToken
  if (!csrfPromise) {
    csrfPromise = transport('GET', '/api/auth/csrf', undefined, {}).then((r) => {
      csrfPromise = null
      if (r.status !== 200) throw new ApiError(r.status, r.body as ApiErrorBody, 'Не удалось получить CSRF-токен')
      csrfToken = (r.body as { csrf_token: string }).csrf_token
      return csrfToken
    }, (e) => {
      csrfPromise = null
      throw e
    })
  }
  return csrfPromise
}

type UnauthorizedListener = () => void
const unauthorizedListeners = new Set<UnauthorizedListener>()
export function onUnauthorized(fn: UnauthorizedListener) {
  unauthorizedListeners.add(fn)
  return () => unauthorizedListeners.delete(fn)
}

export interface RequestOptions {
  /** Do not broadcast 401 (used for the initial /me probe and login). */
  silent401?: boolean
}

export async function request<T>(method: Method, path: string, body?: unknown, opts: RequestOptions = {}): Promise<T> {
  const send = async () => {
    const headers: Record<string, string> = {}
    if (method !== 'GET') headers['X-CSRF-Token'] = await getCsrf()
    return transport(method, path, body, headers)
  }
  let res = await send()
  // A stale CSRF token is rejected before the action runs, so one refresh + retry is safe.
  if (res.status === 403 && (res.body as ApiErrorBody | null)?.code === 'CSRF_INVALID') {
    resetCsrf()
    res = await send()
  }
  if (res.status >= 200 && res.status < 300) return res.body as T
  if (res.status === 401 && !opts.silent401) unauthorizedListeners.forEach((fn) => fn())
  const err = new ApiError(res.status, res.body as ApiErrorBody, 'Ошибка запроса')
  if (res.status === 429 && res.headers?.['retry-after']) {
    err.message = `${err.message}. Повторите через ${res.headers['retry-after']} с.`
  }
  throw err
}

export const get = <T>(path: string, opts?: RequestOptions) => request<T>('GET', path, undefined, opts)
export const post = <T>(path: string, body?: unknown, opts?: RequestOptions) => request<T>('POST', path, body ?? {}, opts)
export const patch = <T>(path: string, body: unknown) => request<T>('PATCH', path, body)

export function qs(params: Record<string, string | number | string[] | undefined | null>): string {
  const sp = new URLSearchParams()
  for (const [k, v] of Object.entries(params)) {
    if (v === undefined || v === null || v === '') continue
    if (Array.isArray(v)) v.forEach((x) => sp.append(k, x))
    else sp.append(k, String(v))
  }
  const s = sp.toString()
  return s ? `?${s}` : ''
}

/** Downloads a protected document via fetch so errors can be shown before saving a Blob. */
export async function downloadDocument(url: string, filename: string) {
  if (import.meta.env.VITE_API_MODE === 'mock') {
    const r = await mockTransport('GET', url, undefined, {})
    if (r.status !== 200) throw new ApiError(r.status, r.body as ApiErrorBody, 'Документ недоступен')
    saveBlob(new Blob([String(r.body)], { type: 'text/csv' }), filename)
    return
  }
  const res = await fetch(url, { credentials: 'same-origin' })
  if (!res.ok) {
    let body: ApiErrorBody | null = null
    try {
      body = await res.json()
    } catch {
      /* ignore */
    }
    throw new ApiError(res.status, body, 'Документ недоступен')
  }
  saveBlob(await res.blob(), filename)
}

function saveBlob(blob: Blob, filename: string) {
  const a = document.createElement('a')
  a.href = URL.createObjectURL(blob)
  a.download = filename
  document.body.appendChild(a)
  a.click()
  a.remove()
  setTimeout(() => URL.revokeObjectURL(a.href), 2000)
}
