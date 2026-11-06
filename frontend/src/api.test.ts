import { beforeEach, describe, expect, it, vi } from 'vitest'
import { api } from './api'

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

describe('API client', () => {
  beforeEach(() => {
    sessionStorage.clear()
    vi.stubGlobal('fetch', vi.fn())
  })

  it('marks the browser session after a successful cookie login', async () => {
    vi.mocked(fetch).mockResolvedValueOnce(jsonResponse({
      authenticated: true,
    }))

    await api.login('person@example.com', 'safe-password-123')

    expect(sessionStorage.getItem('applyboard-authenticated')).toBe('1')
    expect(api.isDemo()).toBe(false)
    expect(fetch).toHaveBeenCalledWith('/auth/login', expect.objectContaining({
      method: 'POST',
      body: JSON.stringify({ email: 'person@example.com', password: 'safe-password-123' }),
    }))
  })

  it('marks a demo session and clears that marker on logout', async () => {
    vi.mocked(fetch).mockResolvedValueOnce(jsonResponse({
      authenticated: true,
    }))

    await api.demoLogin()

    expect(api.hasToken()).toBe(true)
    expect(api.isDemo()).toBe(true)

    api.clearToken()

    expect(api.hasToken()).toBe(false)
    expect(api.isDemo()).toBe(false)
  })

  it('sends credentials with protected application requests', async () => {
    sessionStorage.setItem('applyboard-authenticated', '1')
    vi.mocked(fetch).mockResolvedValueOnce(jsonResponse({
      items: [],
      total: 0,
      page: 1,
      page_size: 20,
      pages: 0,
    }))

    await api.applications(new URLSearchParams({ page: '1' }))

    const [, init] = vi.mocked(fetch).mock.calls[0]
    expect(init?.credentials).toBe('include')
    expect(new Headers(init?.headers).has('Authorization')).toBe(false)
  })

  it('shares one refresh request across concurrent protected API calls', async () => {
    const requestCounts = new Map<string, number>()
    vi.mocked(fetch).mockImplementation(async (input) => {
      const path = String(input)
      const count = (requestCounts.get(path) ?? 0) + 1
      requestCounts.set(path, count)

      if (path === '/auth/refresh') return jsonResponse({ authenticated: true })
      if (count === 1) return jsonResponse({
        detail: 'Invalid or missing authentication credentials.',
      }, 401)
      return jsonResponse(path === '/stats/summary' ? {} : [])
    })

    await Promise.all([api.summary(), api.platforms()])

    expect(requestCounts.get('/auth/refresh')).toBe(1)
    expect(requestCounts.get('/stats/summary')).toBe(2)
    expect(requestCounts.get('/stats/platforms')).toBe(2)
  })

  it('reports the refresh failure details when a protected request cannot refresh', async () => {
    sessionStorage.setItem('applyboard-authenticated', '1')
    vi.mocked(fetch)
      .mockResolvedValueOnce(jsonResponse({ detail: 'Invalid or missing authentication credentials.' }, 401))
      .mockResolvedValueOnce(jsonResponse({ detail: 'Refresh session is missing or expired.' }, 401))

    await expect(api.applications(new URLSearchParams({ page_size: '5' })))
      .rejects.toMatchObject({
        name: 'ApiError',
        status: 401,
        message: '/applications?page_size=5 — Invalid or missing authentication credentials. (session refresh failed: HTTP 401 — Refresh session is missing or expired.)',
      })

    expect(sessionStorage.getItem('applyboard-authenticated')).toBeNull()
    expect(fetch).toHaveBeenNthCalledWith(2, '/auth/refresh', expect.objectContaining({
      method: 'POST',
      credentials: 'include',
    }))
  })

  it('reports a network failure while refreshing a protected request', async () => {
    vi.mocked(fetch)
      .mockResolvedValueOnce(jsonResponse({ detail: 'Unauthorized.' }, 401))
      .mockRejectedValueOnce(new Error('Network unavailable'))

    await expect(api.summary()).rejects.toMatchObject({
      name: 'ApiError',
      status: 401,
      message: '/stats/summary — Unauthorized. (session refresh failed: Network error while refreshing the session.)',
    })
  })
  it('returns useful API validation errors', async () => {
    vi.mocked(fetch).mockResolvedValueOnce(jsonResponse({
      detail: 'Company cannot be blank.',
    }, 422))

    await expect(api.createApplication({
      company: '',
      role: 'Engineer',
      platform: 'Company website',
    })).rejects.toMatchObject({
      name: 'ApiError',
      status: 422,
      message: 'Company cannot be blank.',
    })
  })
})
