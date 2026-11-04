import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { ApplicationForm } from './ApplicationForm'

describe('ApplicationForm', () => {
  it('submits normalized application fields', async () => {
    const onSubmit = vi.fn().mockResolvedValue(undefined)
    render(<ApplicationForm onSubmit={onSubmit} onCancel={vi.fn()} />)

    fireEvent.change(screen.getByLabelText('Company'), { target: { value: '  Acme Labs  ' } })
    fireEvent.change(screen.getByLabelText('Job title'), { target: { value: 'Backend Engineer' } })
    fireEvent.change(screen.getByLabelText('Platform'), { target: { value: 'Company website' } })
    fireEvent.click(screen.getByRole('button', { name: 'Add application' }))

    await waitFor(() => {
      expect(onSubmit).toHaveBeenCalledWith(expect.objectContaining({
        company: 'Acme Labs',
        role: 'Backend Engineer',
        platform: 'Company website',
        status: 'applied',
        url: null,
        notes: null,
      }))
    })
  })

  it('shows a server validation error without closing the form', async () => {
    const onSubmit = vi.fn().mockRejectedValue(new Error('Status transition is not allowed.'))
    render(<ApplicationForm onSubmit={onSubmit} onCancel={vi.fn()} />)

    fireEvent.change(screen.getByLabelText('Company'), { target: { value: 'Acme' } })
    fireEvent.change(screen.getByLabelText('Job title'), { target: { value: 'Engineer' } })
    fireEvent.change(screen.getByLabelText('Platform'), { target: { value: 'LinkedIn' } })
    fireEvent.click(screen.getByRole('button', { name: 'Add application' }))

    expect(await screen.findByRole('alert')).toHaveTextContent('Status transition is not allowed.')
  })
})
