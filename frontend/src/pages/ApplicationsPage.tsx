import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useRef, useState } from 'react'
import { api } from '../api'
import { ApplicationBoard } from '../components/ApplicationBoard'
import { ApplicationForm } from '../components/ApplicationForm'
import { ApplicationTable } from '../components/ApplicationTable'
import { Modal } from '../components/Modal'
import type {
  Application,
  ApplicationInput,
  ApplicationSort,
  ApplicationStatus,
} from '../types'

const statuses: ApplicationStatus[] = ['applied', 'replied', 'interview', 'offer', 'rejected', 'ghosted']
const sortOptions: { value: ApplicationSort; label: string }[] = [
  { value: 'applied_at', label: 'Application date' },
  { value: 'company', label: 'Company' },
  { value: 'last_update_at', label: 'Last updated' },
]

function parseCsv(source: string): Record<string, string>[] {
  const rows: string[][] = []
  let row: string[] = []
  let field = ''
  let quoted = false
  for (let i = 0; i < source.length; i += 1) {
    const char = source[i]
    if (char === '"' && quoted && source[i + 1] === '"') {
      field += '"'
      i += 1
    } else if (char === '"') {
      quoted = !quoted
    } else if (char === ',' && !quoted) {
      row.push(field)
      field = ''
    } else if ((char === '\n' || char === '\r') && !quoted) {
      if (char === '\r' && source[i + 1] === '\n') i += 1
      row.push(field)
      if (row.some((value) => value.trim())) rows.push(row)
      row = []
      field = ''
    } else {
      field += char
    }
  }
  row.push(field)
  if (row.some((value) => value.trim())) rows.push(row)
  if (rows.length < 2) throw new Error('The CSV file must contain a header and at least one application.')
  const headers = rows[0].map((header) => header.trim().toLowerCase())
  for (const required of ['company', 'role', 'platform']) {
    if (!headers.includes(required)) throw new Error(`CSV is missing the required "${required}" column.`)
  }
  return rows.slice(1).map((values) =>
    Object.fromEntries(headers.map((header, index) => [header, (values[index] ?? '').trim()])),
  )
}

function csvCell(value: unknown): string {
  const text = value == null ? '' : String(value)
  return /[",\r\n]/.test(text) ? `"${text.replaceAll('"', '""')}"` : text
}

export function ApplicationsPage() {
  const queryClient = useQueryClient()
  const fileInput = useRef<HTMLInputElement>(null)
  const [search, setSearch] = useState('')
  const [status, setStatus] = useState('')
  const [platform, setPlatform] = useState('')
  const [sortBy, setSortBy] = useState<ApplicationSort>('applied_at')
  const [order, setOrder] = useState<'asc' | 'desc'>('desc')
  const [page, setPage] = useState(1)
  const [view, setView] = useState<'list' | 'board'>('list')
  const [editing, setEditing] = useState<Application | 'new' | null>(null)
  const [importMessage, setImportMessage] = useState('')

  const params = new URLSearchParams({
    page: String(page),
    page_size: '100',
    sort_by: sortBy,
    order,
  })
  if (search.trim()) params.set('search', search.trim())
  if (status) params.set('status', status)
  if (platform.trim()) params.set('platform', platform.trim())

  const query = useQuery({
    queryKey: ['applications', params.toString()],
    queryFn: () => api.applications(params),
  })
  const saveMutation = useMutation({
    mutationFn: (data: ApplicationInput) =>
      editing && editing !== 'new'
        ? api.updateApplication(editing.id, data)
        : api.createApplication(data),
    onSuccess: async () => {
      await queryClient.invalidateQueries()
      setEditing(null)
    },
  })
  const deleteMutation = useMutation({
    mutationFn: api.deleteApplication,
    onSuccess: () => queryClient.invalidateQueries(),
  })

  const applications = query.data?.items ?? []

  function exportCsv() {
    const columns = ['company', 'role', 'platform', 'url', 'status', 'applied_at', 'follow_up_at', 'notes']
    const lines = [
      columns.join(','),
      ...applications.map((application) =>
        columns.map((column) => csvCell(application[column as keyof Application])).join(','),
      ),
    ]
    const url = URL.createObjectURL(new Blob([lines.join('\r\n')], { type: 'text/csv;charset=utf-8' }))
    const anchor = document.createElement('a')
    anchor.href = url
    anchor.download = 'applyboard-applications.csv'
    anchor.click()
    URL.revokeObjectURL(url)
  }

  async function importCsv(file?: File) {
    if (!file) return
    setImportMessage('')
    try {
      const rows = parseCsv(await file.text())
      let imported = 0
      for (const row of rows) {
        const data: ApplicationInput = {
          company: row.company,
          role: row.role,
          platform: row.platform,
          ...(row.url ? { url: row.url } : {}),
          ...(row.status ? { status: row.status as ApplicationStatus } : {}),
          ...(row.applied_at ? { applied_at: row.applied_at } : {}),
          ...(row.follow_up_at ? { follow_up_at: row.follow_up_at } : {}),
          ...(row.notes ? { notes: row.notes } : {}),
        }
        await api.createApplication(data)
        imported += 1
      }
      setImportMessage(`Imported ${imported} application${imported === 1 ? '' : 's'}.`)
      await queryClient.invalidateQueries()
    } catch (error) {
      setImportMessage(error instanceof Error ? error.message : 'CSV import failed.')
    } finally {
      if (fileInput.current) fileInput.current.value = ''
    }
  }

  return (
    <div className="page-stack">
      <section className="page-heading compact-heading">
        <div><p className="eyebrow">OPPORTUNITY PIPELINE</p><h1>Applications</h1><p className="muted">Keep every role and next step in one place.</p></div>
        <div className="applications-actions">
          <button className="button button-quiet" onClick={() => fileInput.current?.click()} type="button">Import CSV</button>
          <input ref={fileInput} accept=".csv,text/csv" className="visually-hidden" onChange={(event) => void importCsv(event.target.files?.[0])} type="file" />
          <button className="button button-quiet" disabled={!applications.length} onClick={exportCsv} type="button">Export CSV</button>
          <button className="button button-primary" onClick={() => setEditing('new')} type="button">＋ Add application</button>
        </div>
      </section>
      {importMessage && <p className="muted" role="status">{importMessage}</p>}
      <section className="panel table-panel">
        <div className="filter-bar">
          <label className="search-field"><span aria-hidden="true">⌕</span><input aria-label="Search company or role" placeholder="Search company or role" value={search} onChange={(event) => { setSearch(event.target.value); setPage(1) }} /></label>
          <label className="filter-control"><span>Status</span><select value={status} onChange={(event) => { setStatus(event.target.value); setPage(1) }}><option value="">All statuses</option>{statuses.map((item) => <option key={item}>{item}</option>)}</select></label>
          <label className="filter-control"><span>Platform</span><input placeholder="Any platform" value={platform} onChange={(event) => { setPlatform(event.target.value); setPage(1) }} /></label>
          <label className="filter-control"><span>Sort by</span><select value={sortBy} onChange={(event) => setSortBy(event.target.value as ApplicationSort)}>{sortOptions.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}</select></label>
          <button className="button button-quiet sort-order" onClick={() => setOrder(order === 'asc' ? 'desc' : 'asc')} type="button" aria-label={`Sort ${order === 'asc' ? 'descending' : 'ascending'}`}>{order === 'asc' ? '↑ Asc' : '↓ Desc'}</button>
        </div>
        <div className="view-switch" aria-label="Application view">
          <button aria-pressed={view === 'list'} className={view === 'list' ? 'button button-primary' : 'button button-quiet'} onClick={() => setView('list')} type="button">List</button>
          <button aria-pressed={view === 'board'} className={view === 'board' ? 'button button-primary' : 'button button-quiet'} onClick={() => setView('board')} type="button">Kanban</button>
        </div>
        {query.error && <div className="error-banner" role="alert">{query.error.message}</div>}
        {deleteMutation.error && <div className="error-banner" role="alert">{deleteMutation.error.message}</div>}
        {query.isLoading ? <div className="loading-line">Loading applications…</div> : view === 'board' ? (
          <ApplicationBoard applications={applications} onEdit={setEditing} />
        ) : (
          <ApplicationTable
            applications={applications}
            onEdit={setEditing}
            onDelete={(application) => {
              if (window.confirm(`Delete the ${application.role} application at ${application.company}? This cannot be undone.`)) {
                deleteMutation.mutate(application.id)
              }
            }}
          />
        )}
        {query.data && query.data.pages > 1 && (
          <div className="pagination">
            <span>Page {query.data.page} of {query.data.pages} · {query.data.total} applications (current page exported)</span>
            <div>
              <button className="button button-quiet" disabled={page <= 1} onClick={() => setPage(page - 1)} type="button">Previous</button>
              <button className="button button-quiet" disabled={page >= query.data.pages} onClick={() => setPage(page + 1)} type="button">Next</button>
            </div>
          </div>
        )}
      </section>
      {editing && (
        <Modal onClose={() => setEditing(null)} title={editing === 'new' ? 'Add an application' : 'Edit application'}>
          <ApplicationForm initial={editing === 'new' ? undefined : editing} onCancel={() => setEditing(null)} onSubmit={async (data) => { await saveMutation.mutateAsync(data) }} />
        </Modal>
      )}
    </div>
  )
}
