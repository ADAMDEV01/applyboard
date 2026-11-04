import type {
  Application,
  ApplicationEvent,
  ApplicationInput,
  ApplicationPage,
  DashboardSummary,
  PlatformMetrics,
  ResponseMetrics,
} from './types'

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL
const TOKEN_KEY = 'job-tracker-access-token'

export class ApiError extends Error {
  readonly status: number

  constructor(
    message: string,
    status: number,
  ) {
    super(message)
    this.name = 'ApiError'
    this.status = status
  }
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const token = sessionStorage.getItem(TOKEN_KEY)
  const headers = new Headers(init.headers)
  if (init.body) headers.set('Content-Type', 'application/json')
  if (token) headers.set('Authorization', `Bearer ${token}`)

  let response: Response
  try {
    response = await fetch(`${API_BASE_URL}${path}`, { ...init, headers })
  } catch {
    throw new ApiError('Could not reach the API. Check the server and try again.', 0)
  }

  if (response.status === 401 && token) {
    sessionStorage.removeItem(TOKEN_KEY)
    window.dispatchEvent(new Event('auth:expired'))
  }
  if (!response.ok) {
    const body = await response.json().catch(() => null) as { detail?: string } | null
    const detail = typeof body?.detail === 'string'
      ? body.detail
      : `Request failed (${response.status}).`
    throw new ApiError(detail, response.status)
  }
  if (response.status === 204) return undefined as T
  return response.json() as Promise<T>
}

export const api = {
  hasToken: () => Boolean(sessionStorage.getItem(TOKEN_KEY)),
  clearToken: () => sessionStorage.removeItem(TOKEN_KEY),
  async demoLogin() {
    const result = await request<{ access_token: string; token_type: string }>('/auth/demo', { method: 'POST' })
    sessionStorage.setItem(TOKEN_KEY, result.access_token)
  },
  async login(email: string, password: string) {
    const result = await request<{ access_token: string; token_type: string }>('/auth/login', {
      method: 'POST',
      body: JSON.stringify({ email, password }),
    })
    sessionStorage.setItem(TOKEN_KEY, result.access_token)
  },
  register: (email: string, password: string) =>
    request<{ id: number; email: string; created_at: string }>('/auth/register', {
      method: 'POST',
      body: JSON.stringify({ email, password }),
    }),
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
