import type {
  Application,
  ApplicationEvent,
  ApplicationInput,
  ApplicationPage,
  DashboardSummary,
  PlatformMetrics,
  ResponseMetrics,
} from './types'

// Production requests stay same-origin so HttpOnly auth cookies work reliably.
// Vercel rewrites proxy API paths to the backend; local development can still use VITE_API_BASE_URL.
const API_BASE_URL = import.meta.env.PROD ? '' : (import.meta.env.VITE_API_BASE_URL ?? '')
const AUTH_KEY = 'applyboard-authenticated'
const DEMO_KEY = 'applyboard-demo-session'

// Share one refresh request across concurrent API calls. Dashboard queries can all
// receive 401 together; rotating the same refresh cookie in parallel makes all but
// one request fail and can overwrite the newly issued cookie with a deletion.
let refreshPromise: Promise<boolean> | null = null

async function refreshSession(): Promise<boolean> {
  if (!refreshPromise) {
    refreshPromise = (async () => {
      try {
        const response = await fetch(`${API_BASE_URL}/auth/refresh`, {
          method: 'POST',
          credentials: 'include',
        })
        return response.ok
      } catch {
        return false
      } finally {
        refreshPromise = null
      }
    })()
  }
  return refreshPromise
}

export class ApiError extends Error {
  readonly status: number

  constructor(message: string, status: number) {
    super(message)
    this.name = 'ApiError'
    this.status = status
  }
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers)
  if (init.body) headers.set('Content-Type', 'application/json')

  const requestInit: RequestInit = {
    ...init,
    headers,
    credentials: 'include',
  }

  let response: Response
  try {
    response = await fetch(`${API_BASE_URL}${path}`, requestInit)
  } catch {
    throw new ApiError('Could not reach the API. Check the server and try again.', 0)
  }

  const publicAuthPaths = [
    '/auth/login',
    '/auth/register',
    '/auth/demo',
    '/auth/refresh',
    '/auth/logout',
  ]
  if (response.status === 401 && !publicAuthPaths.includes(path)) {
    const refreshed = await refreshSession()
    if (refreshed) {
      response = await fetch(`${API_BASE_URL}${path}`, requestInit)
    } else {
      sessionStorage.removeItem(AUTH_KEY)
      sessionStorage.removeItem(DEMO_KEY)
      window.dispatchEvent(new Event('auth:expired'))
    }
  }

  if (!response.ok) {
    const body = await response.json().catch(() => null) as { detail?: string } | null
    const detail = typeof body?.detail === 'string'
      ? body.detail
      : `Request failed (${response.status}).`
    throw new ApiError(`${path} — ${detail}`, response.status)
  }
  if (response.status === 204) return undefined as T
  return response.json() as Promise<T>
}

export const api = {
  hasToken: () => sessionStorage.getItem(AUTH_KEY) === '1',
  clearToken: () => {
    sessionStorage.removeItem(AUTH_KEY)
    sessionStorage.removeItem(DEMO_KEY)
  },
  isDemo: () => sessionStorage.getItem(DEMO_KEY) === '1',
  async demoLogin() {
    await request<{ authenticated: boolean }>('/auth/demo', { method: 'POST' })
    sessionStorage.setItem(AUTH_KEY, '1')
    sessionStorage.setItem(DEMO_KEY, '1')
  },
  async login(email: string, password: string) {
    await request<{ authenticated: boolean }>('/auth/login', {
      method: 'POST',
      body: JSON.stringify({ email, password }),
    })
    sessionStorage.setItem(AUTH_KEY, '1')
    sessionStorage.removeItem(DEMO_KEY)
  },
  async logout() {
    try {
      await request<void>('/auth/logout', { method: 'POST' })
    } finally {
      sessionStorage.removeItem(AUTH_KEY)
      sessionStorage.removeItem(DEMO_KEY)
    }
  },
  register: (email: string, password: string) =>
    request<{ id: number; email: string; created_at: string }>('/auth/register', {
      method: 'POST',
      body: JSON.stringify({ email, password }),
    }),
  async me() {
    const user = await request<{ id: number; email: string; created_at: string }>('/auth/me')
    sessionStorage.setItem(AUTH_KEY, '1')
    if (user.email === 'demo@applyboard.dev') sessionStorage.setItem(DEMO_KEY, '1')
    else sessionStorage.removeItem(DEMO_KEY)
    return user
  },
  summary: () => request<DashboardSummary>('/stats/summary'),
  platforms: () => request<PlatformMetrics[]>('/stats/platforms'),
  applications: (params = new URLSearchParams()) =>
    request<ApplicationPage>(`/applications?${params.toString()}`),
  application: (id: string) => request<Application>(`/applications/${id}`),
  createApplication: (data: ApplicationInput) =>
    request<Application>('/applications', { method: 'POST', body: JSON.stringify(data) }),
  updateApplication: (id: number, data: Partial<ApplicationInput>) =>
    request<Application>(`/applications/${id}`, {
      method: 'PATCH',
      body: JSON.stringify(data),
    }),
  deleteApplication: (id: number) =>
    request<void>(`/applications/${id}`, { method: 'DELETE' }),
  events: (id: string) =>
    request<ApplicationEvent[]>(`/applications/${id}/events`),
  responses: () => request<ResponseMetrics>('/stats/responses'),
}
