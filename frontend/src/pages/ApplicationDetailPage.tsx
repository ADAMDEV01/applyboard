import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link, useParams } from 'react-router-dom'
import { useState } from 'react'
import { api } from '../api'
import { ApplicationForm } from '../components/ApplicationForm'
import { Modal } from '../components/Modal'
import { StatusBadge } from '../components/StatusBadge'
import type { ApplicationInput } from '../types'

export function ApplicationDetailPage() {
  const { applicationId = '' } = useParams()
  const queryClient = useQueryClient()
  const [editing, setEditing] = useState(false)
  const applicationQuery = useQuery({
    queryKey: ['application', applicationId],
    queryFn: () => api.application(applicationId),
  })
  const eventsQuery = useQuery({
    queryKey: ['application-events', applicationId],
    queryFn: () => api.events(applicationId),
  })
  const updateMutation = useMutation({
    mutationFn: (data: ApplicationInput) => api.updateApplication(Number(applicationId), data),
    onSuccess: async () => {
      await queryClient.invalidateQueries()
      setEditing(false)
    },
  })

  const application = applicationQuery.data
  if (applicationQuery.isLoading) return <div className="loading-line">Loading application…</div>
  if (applicationQuery.error || !application) {
    return <div className="page-stack"><Link className="back-link" to="/applications">← Back to applications</Link><div className="error-banner" role="alert">{applicationQuery.error?.message ?? 'Application not found.'}</div></div>
  }

  return (
    <div className="page-stack">
      <Link className="back-link" to="/applications">← All applications</Link>
      {eventsQuery.error && <div className="error-banner" role="alert">{eventsQuery.error.message}</div>}
      <section className="detail-hero panel">
        <div>
          <p className="eyebrow">{application.platform}</p>
          <h1>{application.role}</h1>
          <p className="detail-company">{application.company}</p>
          <StatusBadge status={application.status} />
        </div>
        <div className="detail-actions">
          {application.url && <a className="button button-quiet" href={application.url} target="_blank" rel="noreferrer">View posting ↗</a>}
          {!api.isDemo() && <button className="button button-primary" onClick={() => setEditing(true)} type="button">Edit application</button>}
        </div>
      </section>

      <div className="detail-layout">
        <section className="panel detail-info">
          <div className="panel-heading"><div><h2>Application details</h2><p className="muted">The information you’re tracking</p></div></div>
          <dl className="detail-grid">
            <div><dt>Applied</dt><dd>{new Date(application.applied_at).toLocaleString()}</dd></div>
            <div><dt>Last updated</dt><dd>{new Date(application.last_update_at).toLocaleString()}</dd></div>
            <div><dt>Follow-up</dt><dd>{application.follow_up_at ? new Date(application.follow_up_at).toLocaleString() : 'Not scheduled'}</dd></div>
            <div className="notes-field"><dt>Notes</dt><dd>{application.notes || 'No notes yet.'}</dd></div>
          </dl>
        </section>

        <section className="panel history-panel">
          <div className="panel-heading"><div><h2>Activity history</h2><p className="muted">Status and detail changes</p></div></div>
          {eventsQuery.isLoading ? <p className="muted">Loading history…</p> : eventsQuery.data?.length ? (
            <ol className="timeline">
              {eventsQuery.data.map((event) => (
                <li key={event.id}>
                  <span className={`timeline-marker marker-${event.event_type}`} />
                  <div className="timeline-body">
                    <strong>
                      {event.event_type === 'created'
                        ? 'Application created'
                        : event.event_type === 'status_changed'
                          ? `Status changed to ${event.new_status}`
                          : 'Application details updated'}
                    </strong>
                    {event.event_type === 'status_changed' && event.previous_status && (
                      <p><StatusBadge status={event.previous_status} /> <span className="timeline-arrow">→</span> <StatusBadge status={event.new_status ?? event.previous_status} /></p>
                    )}
                    {event.note && <p className="timeline-note">{event.note}</p>}
                    <time>{new Date(event.created_at).toLocaleString()}</time>
                  </div>
                </li>
              ))}
            </ol>
          ) : <p className="empty-copy">No activity has been recorded.</p>}
        </section>
      </div>

      {editing && (
        <Modal onClose={() => setEditing(false)} title="Edit application">
          <ApplicationForm initial={application} onCancel={() => setEditing(false)} onSubmit={async (data) => { await updateMutation.mutateAsync(data) }} />
        </Modal>
      )}
    </div>
  )
}
