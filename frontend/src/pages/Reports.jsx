import { useState } from 'react'
import { apiDownload } from '../api/client'
import { useApi } from '../api/useApi'
import DataTable from '../components/DataTable'
import FormField from '../components/FormField'
import { IconDownload } from '../components/Icons'
import StatusChip from '../components/StatusChip'
import TopBar from '../components/TopBar'
import { Alert } from '../components/States'
import { addDays, formatDate, formatDateTime, formatHours, todayISO } from '../utils/format'

export default function Reports() {
  const [draft, setDraft] = useState({ from: addDays(todayISO(), -6), to: todayISO() })
  const [range, setRange] = useState(draft)
  const [downloadError, setDownloadError] = useState(null)
  const [downloading, setDownloading] = useState(false)

  const byWorker = useApi('/reports/hours-by-worker', range)
  const byJob = useApi('/reports/hours-by-job', range)
  const flagged = useApi('/reports/flagged', range)
  const rangeError = byWorker.error?.field === 'from' || byWorker.error?.field === 'to' ? byWorker.error : null

  async function downloadCsv() {
    setDownloadError(null)
    setDownloading(true)
    try {
      await apiDownload('/reports/hours.csv', range, `fieldtrack-hours-${range.from}-to-${range.to}.csv`)
    } catch (err) {
      setDownloadError(err.message)
    } finally {
      setDownloading(false)
    }
  }

  const workerColumns = [
    {
      key: 'full_name',
      header: 'Worker',
      render: (r) => (
        <>
          <div className="cell-title">{r.full_name}</div>
          <div className="cell-sub">{r.trade}</div>
        </>
      ),
    },
    { key: 'entries', header: 'Entries', align: 'right', render: (r) => <span className="num">{r.entries}</span> },
    { key: 'approved_hours', header: 'Approved', align: 'right', render: (r) => <span className="num">{formatHours(r.approved_hours)}</span> },
    { key: 'pending_hours', header: 'Pending', align: 'right', render: (r) => <span className="num">{formatHours(r.pending_hours)}</span> },
    { key: 'total_hours', header: 'Total', align: 'right', render: (r) => <span className="num strong">{formatHours(r.total_hours)}</span> },
    {
      key: 'flagged_entries',
      header: 'Flagged',
      align: 'right',
      render: (r) => (r.flagged_entries ? <StatusChip status={String(r.flagged_entries)} tone="amber" /> : <span className="muted">0</span>),
    },
  ]

  const jobColumns = [
    {
      key: 'title',
      header: 'Job',
      render: (r) => (
        <>
          <div className="cell-title">{r.title}</div>
          <div className="cell-sub">{r.site_name}</div>
        </>
      ),
    },
    { key: 'scheduled_date', header: 'Date', render: (r) => <span className="num">{formatDate(r.scheduled_date)}</span> },
    { key: 'status', header: 'Status', render: (r) => <StatusChip status={r.status} /> },
    { key: 'workers', header: 'Workers', align: 'right', render: (r) => <span className="num">{r.workers}</span> },
    { key: 'entries', header: 'Entries', align: 'right', render: (r) => <span className="num">{r.entries}</span> },
    { key: 'total_hours', header: 'Total', align: 'right', render: (r) => <span className="num strong">{formatHours(r.total_hours)}</span> },
  ]

  const flaggedColumns = [
    { key: 'worker_name', header: 'Worker', render: (e) => <span className="cell-title">{e.worker_name}</span> },
    {
      key: 'job',
      header: 'Job',
      render: (e) => (
        <>
          <div>{e.job_title}</div>
          <div className="cell-sub">{e.site_name}</div>
        </>
      ),
    },
    { key: 'clock_in', header: 'Clock-in', render: (e) => <span className="num">{formatDateTime(e.clock_in)}</span> },
    { key: 'flag_reason', header: 'Reason', render: (e) => <span className="flag-reason" style={{ marginTop: 0 }}>⚑ {e.flag_reason}</span> },
    { key: 'status', header: 'Status', render: (e) => <StatusChip status={e.status} /> },
  ]

  const totalRow = (label, total, span) => (
    <tr>
      <td colSpan={span}>{label}</td>
      <td className="align-right num">{formatHours(total)}</td>
      <td />
    </tr>
  )

  return (
    <>
      <TopBar
        title="Reports"
        subtitle="Hours exclude rejected entries and shifts still in progress"
        actions={
          <button type="button" className="btn btn--primary" onClick={downloadCsv} disabled={downloading}>
            <IconDownload size={16} /> {downloading ? 'Preparing…' : 'Download CSV'}
          </button>
        }
      />
      <div className="page">
        {downloadError && <Alert onClose={() => setDownloadError(null)}>{downloadError}</Alert>}
        <div className="card">
          <form
            className="filters"
            onSubmit={(e) => {
              e.preventDefault()
              setRange({ ...draft })
            }}
          >
            <FormField label="From" htmlFor="r-from" error={rangeError?.field === 'from' ? rangeError.message : undefined}>
              <input id="r-from" type="date" className="input" value={draft.from} onChange={(e) => setDraft({ ...draft, from: e.target.value })} />
            </FormField>
            <FormField label="To" htmlFor="r-to" error={rangeError?.field === 'to' ? rangeError.message : undefined}>
              <input id="r-to" type="date" className="input" value={draft.to} onChange={(e) => setDraft({ ...draft, to: e.target.value })} />
            </FormField>
            <button type="submit" className="btn btn--navy">
              Apply range
            </button>
            <span className="muted small">
              Showing {formatDate(range.from)} – {formatDate(range.to)}
            </span>
          </form>
        </div>

        <div className="card">
          <div className="card__header">
            <div>
              <div className="card__title">Hours by worker</div>
              <div className="card__subtitle">Approved vs pending, with geofence flags</div>
            </div>
          </div>
          <DataTable
            columns={workerColumns}
            rows={byWorker.data?.rows}
            rowKey="user_id"
            loading={byWorker.loading}
            error={rangeError ? null : byWorker.error}
            onRetry={byWorker.reload}
            emptyTitle="No hours in this range"
            footer={byWorker.data?.rows.length ? totalRow('Total', byWorker.data.total_hours, 4) : null}
          />
        </div>

        <div className="card">
          <div className="card__header">
            <div>
              <div className="card__title">Hours by job</div>
              <div className="card__subtitle">Labour hours charged to each job</div>
            </div>
          </div>
          <DataTable
            columns={jobColumns}
            rows={byJob.data?.rows}
            rowKey="job_id"
            loading={byJob.loading}
            error={rangeError ? null : byJob.error}
            onRetry={byJob.reload}
            emptyTitle="No hours in this range"
            footer={
              byJob.data?.rows.length ? (
                <tr>
                  <td colSpan={5}>Total</td>
                  <td className="align-right num">{formatHours(byJob.data.total_hours)}</td>
                </tr>
              ) : null
            }
          />
        </div>

        <div className="card">
          <div className="card__header">
            <div>
              <div className="card__title">Flagged entries</div>
              <div className="card__subtitle">Clock-ins or clock-outs outside the site geofence</div>
            </div>
            {flagged.data && <span className="chip chip--amber">{flagged.data.rows.length}</span>}
          </div>
          <DataTable
            columns={flaggedColumns}
            rows={flagged.data?.rows}
            rowKey="entry_id"
            loading={flagged.loading}
            error={rangeError ? null : flagged.error}
            onRetry={flagged.reload}
            rowClassName={() => 'row-flagged'}
            emptyTitle="No flagged entries"
            emptyMessage="Every clock-in in this range was inside its geofence."
          />
        </div>
      </div>
    </>
  )
}
