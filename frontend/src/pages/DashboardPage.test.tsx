import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { api } from '../api'
import { DashboardPage } from './DashboardPage'

describe('DashboardPage', () => {
  afterEach(() => vi.restoreAllMocks())

  it('shows the empty-state guidance when the account has no applications', async () => {
    vi.spyOn(api, 'summary').mockResolvedValue({
      total_applications: 0,
      responded_applications: 0,
      response_rate: 0,
      average_time_to_first_response_days: null,
      by_status: [],
      upcoming_followups: [],
      may_be_ghosted: [],
    })
    vi.spyOn(api, 'platforms').mockResolvedValue([])
    vi.spyOn(api, 'applications').mockResolvedValue({
      items: [],
      total: 0,
      page: 1,
      page_size: 5,
      pages: 0,
    })

    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    })
    render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter>
          <DashboardPage />
        </MemoryRouter>
      </QueryClientProvider>,
    )

    expect(await screen.findByRole('heading', {
      name: 'Turn your job search into a plan.',
    })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Add your first application' })).toBeInTheDocument()
  })
})
