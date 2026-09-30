import { Link } from 'react-router-dom'
import { useApi } from '../api/useApi'
import DataTable from '../components/DataTable'
import { IconAlert, IconFlag, IconMoon, IconUser, IconUsers } from '../components/Icons'
import KpiCard from '../components/KpiCard'
import StatusChip from '../components/StatusChip'
import TopBar from '../components/TopBar'
import { EmptyState, ErrorState, LoadingState } from '../components/States'
import { formatDate } from '../utils/format'

const ATTENTION = {
  flagged_entry: { icon: IconFlag, tone: 'amber', link: '/time-entries?flagged=true', cta: 'Review' },
  understaffed_job: { icon: IconUsers, tone: 'orange', link: '/jobs', cta: 'Assign crew' },
  open_overnight: { icon: IconMoon, tone: 'red', link: '/time-entries', cta: 'Clock out' },
}

export default function Dashboard() {
  const { data, loading, error, reload } = useApi('/dashboard')

  const jobColumns = [
    {
      key: 'title',
      header: 'Job',
      render: (j) => (
        <>
          <div className="cell-title">{j.title}</div>
          <div className="cell-sub">{j.site_name}</div>
        </>
      ),
    },
    {
      key: 'crew',
      header: 'Crew',
      render: (j) => (
        <>
          <div className="num strong">
            {j.assigned_count} / {j.crew_size}
          </div>
          <div className="cell-sub">{j.crew.map((c) => c.full_name).join(', ') || 'No one assigned'}</div>
        </>
      ),
    },
    { key: 'status', header: 'Status', render: (j) => <StatusChip status={j.status} /> },
  ]

  return (
    <>
      <TopBar
        title="Dashboard"
        subtitle={data ? `Today · ${formatDate(data.date)}` : 'Today'}
        actions={
          <button type="button" className="btn btn--secondary btn--sm" onClick={reload}>
            Refresh
          </button>
        }
      />
      <div className="page">
        {loading && !data && <LoadingState label="Loading today’s operations…" />}
        {error && <ErrorState message={error.message} onRetry={reload} />}

        {data && (
          <>
            <div className="kpi-grid">
              <KpiCard label="Active jobs" value={data.kpis.active_jobs} hint="Scheduled today, not completed" tone="navy" />
              <KpiCard label="Workers clocked in" value={data.kpis.workers_clocked_in} hint="Open time entries right now" tone="orange" />
              <KpiCard label="Hours logged today" value={data.kpis.hours_today.toFixed(1)} hint="Includes shifts in progress" tone="green" />
              <KpiCard label="Flagged entries" value={data.kpis.flagged_entries} hint="Outside geofence, awaiting review" tone="amber" />
            </div>

            <div className="grid-2">
              <div className="card">
                <div className="card__header">
                  <div>
                    <div className="card__title">Jobs today</div>
                    <div className="card__subtitle">{data.jobs_today.length} job(s) scheduled</div>
                  </div>
                  <Link to="/jobs" className="btn btn--ghost btn--sm">
                    All jobs
                  </Link>
                </div>
                <DataTable
                  columns={jobColumns}
                  rows={data.jobs_today}
                  rowKey="job_id"
                  emptyTitle="No jobs scheduled today"
                  emptyMessage="Create a job from the Jobs page."
                />
              </div>

              <div className="stack">
                <div className="card">
                  <div className="card__header">
                    <div className="card__title">Needs attention</div>
                    <span className="chip chip--amber">{data.needs_attention.length}</span>
                  </div>
                  {data.needs_attention.length === 0 ? (
                    <EmptyState title="All clear" message="No flagged entries or short crews." />
                  ) : (
                    <ul className="list">
                      {data.needs_attention.map((item) => {
                        const meta = ATTENTION[item.type] || { icon: IconAlert, tone: 'navy' }
                        const Icon = meta.icon
                        return (
                          <li className="list__item" key={`${item.type}-${item.ref_id}`}>
                            <span className={`list__icon list__icon--${meta.tone}`}>
                              <Icon size={16} />
                            </span>
                            <div>
                              <div>{item.message}</div>
                              {meta.link && (
                                <Link className="list__link" to={meta.link}>
                                  {meta.cta} →
                                </Link>
                              )}
                            </div>
                          </li>
                        )
                      })}
                    </ul>
                  )}
                </div>

                <div className="card">
                  <div className="card__header">
                    <div className="card__title">Unassigned workers</div>
                    <span className="chip chip--navy">{data.unassigned_workers.length}</span>
                  </div>
                  {data.unassigned_workers.length === 0 ? (
                    <EmptyState title="Everyone is assigned" message="Every active worker has a job today." />
                  ) : (
                    <ul className="list">
                      {data.unassigned_workers.map((w) => (
                        <li className="list__item" key={w.user_id}>
                          <span className="list__icon list__icon--navy">
                            <IconUser size={16} />
                          </span>
                          <div>
                            <div className="strong">{w.full_name}</div>
                            <div className="cell-sub">{w.trade}</div>
                          </div>
                        </li>
                      ))}
                    </ul>
                  )}
                </div>
              </div>
            </div>
          </>
        )}
      </div>
    </>
  )
}
