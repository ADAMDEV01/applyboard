import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import { useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../api'
import { ApplicationForm } from '../components/ApplicationForm'
import { ApplicationTable } from '../components/ApplicationTable'
import { Modal } from '../components/Modal'
import type { Application, ApplicationInput } from '../types'

const chartColors = ['#5268d8', '#43a58e', '#e8a447', '#be71bc', '#e26e73', '#8b97aa']

function MetricCard({
  label,
  value,
  detail,
  accent,
}: {
  label: string
  value: string
  detail: string
  accent: string
}) {
  return (
    <article className="metric-card">
      <span className={`metric-icon ${accent}`}>{label.slice(0, 1)}</span>
      <p className="metric-label">{label}</p>
      <strong className="metric-value">{value}</strong>
      <span className="metric-detail">{detail}</span>
    </article>
  )
}

export function DashboardPage() {
  const queryClient = useQueryClient()
  const [editing, setEditing] = useState<Application | 'new' | null>(null)
  const summaryQuery = useQuery({ queryKey: ['stats', 'summary'], queryFn: api.summary })
  const platformQuery = useQuery({ queryKey: ['stats', 'platforms'], queryFn: api.platforms })
  const applicationsQuery = useQuery({
    queryKey: ['applications', 'dashboard'],
    queryFn: () => api.applications(new URLSearchParams({ page_size: '5', sort_by: 'applied_at' })),
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

  const error = summaryQuery.error ?? platformQuery.error ?? applicationsQuery.error ?? deleteMutation.error
  const summary = summaryQuery.data
  const applications = applicationsQuery.data?.items ?? []
  const hasData = summary && summary.total_applications > 0

  return (
    <div className="page-stack">
      <section className="page-heading">
        <div>
          <p className="eyebrow">YOUR SEARCH OVERVIEW</p>
          <h1>Good progress starts with a clear view.</h1>
          <p className="muted">Track the work behind your next opportunity.</p>
        </div>
        {!api.isDemo() && <button className="button button-primary" onClick={() => setEditing('new')} type="button">
          <span aria-hidden="true">＋</span> Add application
        </button>}
      </section>

      {error && <div className="error-banner" role="alert">{error.message}</div>}
      {(summaryQuery.isLoading || platformQuery.isLoading || applicationsQuery.isLoading) && (
        <div className="loading-line" role="status">Loading your dashboard…</div>
      )}

      {summary && (
        <>
          <section className="metric-grid" aria-label="Application summary">
            <MetricCard accent="icon-blue" label="Applications" value={String(summary.total_applications)} detail="Total tracked" />
            <MetricCard accent="icon-green" label="Response rate" value={`${Math.round(summary.response_rate * 100)}%`} detail={`${summary.responded_applications} with a recorded response`} />
            <MetricCard accent="icon-amber" label="First response" value={summary.average_time_to_first_response_days === null ? '—' : `${summary.average_time_to_first_response_days}d`} detail="Average time to respond" />
            <MetricCard accent="icon-purple" label="Follow-ups" value={String(summary.upcoming_followups.length)} detail="Scheduled in the next 30 days" />
          </section>

          {!hasData ? (
            <section className="panel welcome-panel">
              <p className="eyebrow">READY WHEN YOU ARE</p>
              <h2>Turn your job search into a plan.</h2>
              <p className="muted">Add an application to see your progress, response patterns, and upcoming follow-ups here.</p>
              {!api.isDemo() && <button className="button button-primary" onClick={() => setEditing('new')} type="button">Add your first application</button>}
            </section>
          ) : (
            <>
              <section className="chart-grid">
                <article className="panel chart-panel">
                  <div className="panel-heading">
                    <div><h2>Application outcomes</h2><p className="muted">Current status across your search</p></div>
                  </div>
                  <div className="chart-area">
                    <ResponsiveContainer width="100%" height="100%">
                      <PieChart>
                        <Pie data={summary.by_status.filter((item) => item.count > 0)} dataKey="count" nameKey="status" innerRadius={58} outerRadius={92} paddingAngle={4}>
                          {summary.by_status.filter((item) => item.count > 0).map((item, index) => (
                            <Cell key={item.status} fill={chartColors[index % chartColors.length]} />
                          ))}
                        </Pie>
                        <Tooltip formatter={(value, name) => [value, name]} />
                      </PieChart>
                    </ResponsiveContainer>
                    <div className="chart-legend">
                      {summary.by_status.filter((item) => item.count > 0).map((item, index) => (
                        <span key={item.status}><i style={{ background: chartColors[index % chartColors.length] }} />{item.status}<b>{item.count}</b></span>
                      ))}
                    </div>
                  </div>
                </article>
                <article className="panel chart-panel">
                  <div className="panel-heading">
                    <div><h2>Response by platform</h2><p className="muted">Recorded response rate per source</p></div>
                  </div>
                  <div className="chart-area bar-area">
                    {(platformQuery.data?.length ?? 0) > 0 ? (
                      <ResponsiveContainer width="100%" height="100%">
                        <BarChart data={platformQuery.data} margin={{ top: 12, right: 12, left: -16, bottom: 8 }}>
                          <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="#edf0f5" />
                          <XAxis dataKey="platform" axisLine={false} tickLine={false} tick={{ fill: '#768096', fontSize: 12 }} />
                          <YAxis domain={[0, 1]} tickFormatter={(value: number) => `${Math.round(value * 100)}%`} axisLine={false} tickLine={false} tick={{ fill: '#768096', fontSize: 12 }} />
                          <Tooltip formatter={(value) => [`${Math.round(Number(value) * 100)}%`, 'Response rate']} />
                          <Bar dataKey="response_rate" fill="#5268d8" radius={[6, 6, 0, 0]} maxBarSize={42} />
                        </BarChart>
                      </ResponsiveContainer>
                    ) : <p className="chart-empty">Add applications from different platforms to compare response rates.</p>}
                  </div>
                </article>
              </section>

              <section className="two-column-panels">
                <article className="panel followup-panel">
                  <div className="panel-heading">
                    <div><h2>Coming up</h2><p className="muted">Follow-ups scheduled within 30 days</p></div>
                    <span className="count-pill">{summary.upcoming_followups.length}</span>
                  </div>
                  {summary.upcoming_followups.length ? summary.upcoming_followups.map(({ application }) => (
                    <div className="followup-row" key={application.id}>
                      <span className="followup-dot" />
                      <div><Link to={`/applications/${application.id}`}>{application.company}</Link><p>{application.role}</p></div>
                      <time>{application.follow_up_at ? new Date(application.follow_up_at).toLocaleDateString() : ''}</time>
                    </div>
                  )) : <p className="empty-copy">No upcoming follow-ups. Schedule a reminder on an application to keep it moving.</p>}
                </article>
                <article className="panel ghost-panel">
                  <div className="panel-heading">
                    <div><h2>Needs a check-in?</h2><p className="muted">No response after 14 days</p></div>
                    <span className="count-pill count-warm">{summary.may_be_ghosted.length}</span>
                  </div>
                  {summary.may_be_ghosted.length ? summary.may_be_ghosted.map(({ application, days_since_applied }) => (
                    <div className="followup-row" key={application.id}>
                      <span className="followup-dot dot-warm" />
                      <div><Link to={`/applications/${application.id}`}>{application.company}</Link><p>{application.role}</p></div>
                      <time>{days_since_applied} days</time>
                    </div>
                  )) : <p className="empty-copy">Nothing waiting on a response for more than 14 days.</p>}
                  <p className="fine-print">Suggestions only — no application is automatically marked ghosted.</p>
                </article>
              </section>
            </>
          )}

          <section className="panel table-panel">
            <div className="panel-heading">
              <div><h2>Recent applications</h2><p className="muted">Your latest opportunities</p></div>
              <Link className="text-button" to="/applications">View all</Link>
            </div>
            <ApplicationTable
              applications={applications}
              onEdit={setEditing}
              onDelete={(application) => {
                if (window.confirm(`Delete the ${application.role} application at ${application.company}? This cannot be undone.`)) {
                  deleteMutation.mutate(application.id)
                }
              }}
            />
          </section>
        </>
      )}

      {editing && (
        <Modal onClose={() => setEditing(null)} title={editing === 'new' ? 'Add an application' : 'Edit application'}>
          <ApplicationForm
            initial={editing === 'new' ? undefined : editing}
            onCancel={() => setEditing(null)}
            onSubmit={async (data) => { await saveMutation.mutateAsync(data) }}
          />
        </Modal>
      )}
    </div>
  )
}
