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

  it('stores the access token after a successful login', async () => {
    vi.mocked(fetch).mockResolvedValueOnce(jsonResponse({
      access_token: 'access-token',
      token_type: 'bearer',
    }))

    await api.login('person@example.com', 'safe-password-123')

    expect(sessionStorage.getItem('job-tracker-access-token')).toBe('access-token')
    expect(api.isDemo()).toBe(false)
    expect(fetch).toHaveBeenCalledWith('/auth/login', expect.objectContaining({
      method: 'POST',
      body: JSON.stringify({ email: 'person@example.com', password: 'safe-password-123' }),
    }))
  })

  it('marks a demo session and clears that marker on logout', async () => {
    vi.mocked(fetch).mockResolvedValueOnce(jsonResponse({
      access_token: 'demo-token',
      token_type: 'bearer',
    }))

    await api.demoLogin()

    expect(api.hasToken()).toBe(true)
    expect(api.isDemo()).toBe(true)

    api.clearToken()

    expect(api.hasToken()).toBe(false)
    expect(api.isDemo()).toBe(false)
  })

  it('attaches the bearer token to protected application requests', async () => {
    sessionStorage.setItem('job-tracker-access-token', 'existing-token')
    vi.mocked(fetch).mockResolvedValueOnce(jsonResponse({
      items: [],
      total: 0,
      page: 1,
      page_size: 20,
      pages: 0,
    }))

    await api.applications(new URLSearchParams({ page: '1' }))

    const [, init] = vi.mocked(fetch).mock.calls[0]
    expect(new Headers(init?.headers).get('Authorization')).toBe('Bearer existing-token')
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
