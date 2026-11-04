import { Link } from 'react-router-dom'
import type { Application, ApplicationStatus } from '../types'

const columns: ApplicationStatus[] = [
  'applied',
  'replied',
  'interview',
  'offer',
  'rejected',
  'ghosted',
]

interface Props {
  applications: Application[]
  onEdit: (application: Application) => void
}

export function ApplicationBoard({ applications, onEdit }: Props) {
  return (
    <div className="kanban-board" aria-label="Applications by status">
      {columns.map((status) => {
        const items = applications.filter((application) => application.status === status)
        return (
          <section className="kanban-column" key={status}>
            <header className="kanban-column-heading">
              <h3>{status}</h3><span>{items.length}</span>
            </header>
            {items.length === 0 && <p className="kanban-empty">No applications</p>}
            {items.map((application) => (
              <article className="kanban-card" key={application.id}>
                <Link to={`/applications/${application.id}`} className="kanban-company">{application.company}</Link>
                <p>{application.role}</p>
                <span>{application.platform}</span>
                <button className="text-button" onClick={() => onEdit(application)} type="button">Edit details</button>
              </article>
            ))}
          </section>
        )
      })}
    </div>
  )
}
