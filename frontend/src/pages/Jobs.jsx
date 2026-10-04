import { useEffect, useState } from 'react'
import { api } from '../api/client'
import { useApi } from '../api/useApi'
import DataTable from '../components/DataTable'
import FormField from '../components/FormField'
import { IconPlus } from '../components/Icons'
import Modal from '../components/Modal'
import StatusChip from '../components/StatusChip'
import TopBar from '../components/TopBar'
import { Alert, LoadingState } from '../components/States'
import { useAuth } from '../context/AuthContext'
import { errorState, formatDate, todayISO } from '../utils/format'

const STATUSES = ['Scheduled', 'In progress', 'Completed']
const JOB_FIELDS = ['site_id', 'title', 'description', 'scheduled_date', 'crew_size', 'status']

/**
 * Dispatcher's schedule: create jobs and assign crews. Double-booking is enforced by the server
 * (HTTP 409), so the page shows the server's message instead of duplicating the rule here.
 */
export default function Jobs() {
  const { hasRole } = useAuth()
  const canEdit = hasRole('Admin', 'Dispatcher')
  const [filters, setFilters] = useState({ date: '', status: '' })
  const { data, loading, error, reload } = useApi('/jobs', filters)
  const sites = useApi('/sites')
  const [editing, setEditing] = useState(null) // null | 'new' | job
  const [assigning, setAssigning] = useState(null) // job
  const [notice, setNotice] = useState(null)

  const columns = [
    {
      key: 'scheduled_date',
      header: 'Date',
      render: (j) => <span className="num">{formatDate(j.scheduled_date)}</span>,
    },
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
    {
      key: 'actions',
      header: '',
      align: 'right',
      render: (j) =>
        canEdit && (
          <div className="actions">
            {j.status !== 'Completed' && (
              <button type="button" className="btn btn--navy btn--sm" onClick={() => setAssigning(j)}>
                Assign worker
              </button>
            )}
            <button type="button" className="btn btn--secondary btn--sm" onClick={() => setEditing(j)}>
              Edit
            </button>
          </div>
        ),
    },
  ]

  return (
    <>
      <TopBar
        title="Jobs"
        subtitle="Schedule work and dispatch crews"
        actions={
          canEdit && (
            <button type="button" className="btn btn--primary" onClick={() => setEditing('new')}>
              <IconPlus size={16} /> New job
            </button>
          )
        }
      />
      <div className="page">
        {notice && (
          <Alert tone="success" onClose={() => setNotice(null)}>
            {notice}
          </Alert>
        )}
        <div className="card">
          <div className="filters">
            <FormField label="Date" htmlFor="f-date">
              <input
                id="f-date"
                type="date"
                className="input"
                value={filters.date}
                onChange={(e) => setFilters({ ...filters, date: e.target.value })}
              />
            </FormField>
            <FormField label="Status" htmlFor="f-status">
              <select
                id="f-status"
                className="input"
                value={filters.status}
                onChange={(e) => setFilters({ ...filters, status: e.target.value })}
              >
                <option value="">All statuses</option>
                {STATUSES.map((s) => (
                  <option key={s}>{s}</option>
                ))}
              </select>
            </FormField>
            <button type="button" className="btn btn--secondary" onClick={() => setFilters({ date: todayISO(), status: '' })}>
              Today
            </button>
            <button type="button" className="btn btn--ghost" onClick={() => setFilters({ date: '', status: '' })}>
              Clear filters
            </button>
          </div>
          <DataTable
            columns={columns}
            rows={data?.jobs}
            rowKey="job_id"
            loading={loading}
            error={error}
            onRetry={reload}
            emptyTitle="No jobs match these filters"
            emptyMessage={canEdit ? 'Try another date, or create a new job.' : 'Try another date or status.'}
          />
        </div>
      </div>

      {editing && (
        <JobFormModal
          job={editing === 'new' ? null : editing}
          sites={sites.data?.sites || []}
          onClose={() => setEditing(null)}
          onSaved={(job, isNew) => {
            setEditing(null)
            setNotice(isNew ? `Job “${job.title}” created.` : `Job “${job.title}” updated.`)
            reload()
          }}
        />
      )}
      {assigning && (
        <AssignModal
          jobId={assigning.job_id}
          onClose={() => {
            setAssigning(null)
            reload()
          }}
        />
      )}
    </>
  )
}

/**
 * Create or edit a job. created_by is never sent: the server takes it from the login token.
 */
function JobFormModal({ job, sites, onClose, onSaved }) {
  const isNew = !job
  const [form, setForm] = useState({
    site_id: job?.site_id ?? '',
    title: job?.title ?? '',
    description: job?.description ?? '',
    scheduled_date: job?.scheduled_date ?? todayISO(),
    crew_size: job?.crew_size ?? 2,
    status: job?.status ?? 'Scheduled',
  })
  const [errors, setErrors] = useState({})
  const [saving, setSaving] = useState(false)

  const set = (field) => (e) => {
    setForm({ ...form, [field]: e.target.value })
    setErrors({ ...errors, [field]: undefined, _form: undefined })
  }

  async function submit(e) {
    e.preventDefault()
    setSaving(true)
    const body = {
      ...form,
      site_id: form.site_id === '' ? null : Number(form.site_id),
      crew_size: form.crew_size === '' ? null : Number(form.crew_size),
    }
    try {
      const res = isNew
        ? await api('/jobs', { method: 'POST', body })
        : await api(`/jobs/${job.job_id}`, { method: 'PATCH', body })
      onSaved(res.job, isNew)
    } catch (err) {
      setErrors(errorState(err, JOB_FIELDS))
    } finally {
      setSaving(false)
    }
  }

  return (
    <Modal
      open
      title={isNew ? 'New job' : `Edit job #${job.job_id}`}
      onClose={onClose}
      footer={
        <>
          <button type="button" className="btn btn--secondary" onClick={onClose}>
            Cancel
          </button>
          <button type="submit" form="job-form" className="btn btn--primary" disabled={saving}>
            {saving ? 'Saving…' : isNew ? 'Create job' : 'Save changes'}
          </button>
        </>
      }
    >
      <form id="job-form" className="form" onSubmit={submit} noValidate>
        {errors._form && <Alert>{errors._form}</Alert>}
        <div className="form-grid">
          <FormField label="Job site" htmlFor="job-site" error={errors.site_id} required className="span-2">
            <select id="job-site" className="input" value={form.site_id} onChange={set('site_id')}>
              <option value="">Select a site…</option>
              {sites.map((s) => (
                <option key={s.site_id} value={s.site_id}>
                  {s.site_name}
                </option>
              ))}
            </select>
          </FormField>
          <FormField label="Title" htmlFor="job-title" error={errors.title} required className="span-2">
            <input id="job-title" className="input" value={form.title} onChange={set('title')} placeholder="e.g. Level 5 framing" />
          </FormField>
          <FormField label="Description" htmlFor="job-desc" error={errors.description} className="span-2">
            <textarea id="job-desc" className="input" value={form.description} onChange={set('description')} rows={3} />
          </FormField>
          <FormField label="Scheduled date" htmlFor="job-date" error={errors.scheduled_date} required>
            <input id="job-date" type="date" className="input" value={form.scheduled_date} onChange={set('scheduled_date')} />
          </FormField>
          <FormField label="Crew size" htmlFor="job-crew" error={errors.crew_size} required hint="1–50 workers">
            <input id="job-crew" type="number" min="1" max="50" className="input" value={form.crew_size} onChange={set('crew_size')} />
          </FormField>
          <FormField label="Status" htmlFor="job-status" error={errors.status} required>
            <select id="job-status" className="input" value={form.status} onChange={set('status')}>
              {STATUSES.map((s) => (
                <option key={s}>{s}</option>
              ))}
            </select>
          </FormField>
        </div>
      </form>
    </Modal>
  )
}

/**
 * Assign workers to a job. The server enforces the DOUBLE-BOOKING rule: if the chosen worker
 * already has an assignment that day it answers 409 and we show its message under the field.
 */
function AssignModal({ jobId, onClose }) {
  const [job, setJob] = useState(null)
  const [loadError, setLoadError] = useState(null)
  const workers = useApi('/users', { role: 'Worker', active: true })
  const [userId, setUserId] = useState('')
  const [errors, setErrors] = useState({})
  const [success, setSuccess] = useState(null)
  const [saving, setSaving] = useState(false)

  const loadJob = () =>
    api(`/jobs/${jobId}`)
      .then((res) => setJob(res.job))
      .catch((err) => setLoadError(err.message))

  useEffect(() => {
    loadJob()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [jobId])

  const onCrew = new Set(job?.crew.map((c) => c.user_id))
  const available = (workers.data?.users || []).filter((w) => !onCrew.has(w.user_id))

  async function assign(e) {
    e.preventDefault()
    setErrors({})
    setSuccess(null)
    if (!userId) return setErrors({ user_id: 'Choose a worker to assign.' })
    setSaving(true)
    try {
      const res = await api('/assignments', {
        method: 'POST',
        body: { job_id: jobId, user_id: Number(userId) },
      })
      setSuccess(`${res.assignment.full_name} assigned for ${formatDate(res.assignment.work_date)}.`)
      setUserId('')
      await loadJob()
    } catch (err) {
      setErrors(errorState(err, ['user_id']))
    } finally {
      setSaving(false)
    }
  }

  async function remove(assignmentId, name) {
    setErrors({})
    setSuccess(null)
    try {
      await api(`/assignments/${assignmentId}`, { method: 'DELETE' })
      setSuccess(`${name} removed from the crew.`)
      await loadJob()
    } catch (err) {
      setErrors({ _form: err.message })
    }
  }

  return (
    <Modal
      open
      title="Assign worker"
      onClose={onClose}
      footer={
        <button type="button" className="btn btn--secondary" onClick={onClose}>
          Done
        </button>
      }
    >
      {loadError && <Alert>{loadError}</Alert>}
      {!job && !loadError && <LoadingState />}
      {job && (
        <>
          <div className="info-box">
            <strong>{job.title}</strong> · {job.site_name}
            <br />
            {formatDate(job.scheduled_date)} · Crew {job.assigned_count} of {job.crew_size}
          </div>

          {success && <Alert tone="success">{success}</Alert>}
          {errors._form && <Alert>{errors._form}</Alert>}

          <form className="form" onSubmit={assign} noValidate>
            <FormField
              label="Worker"
              htmlFor="assign-worker"
              error={errors.user_id}
              hint="A worker can only be booked on one job per day."
              required
            >
              <select
                id="assign-worker"
                className="input"
                value={userId}
                onChange={(e) => {
                  setUserId(e.target.value)
                  setErrors({})
                }}
                disabled={workers.loading}
              >
                <option value="">{workers.loading ? 'Loading workers…' : 'Select a worker…'}</option>
                {available.map((w) => (
                  <option key={w.user_id} value={w.user_id}>
                    {w.full_name} — {w.trade}
                  </option>
                ))}
              </select>
            </FormField>
            <div>
              <button type="submit" className="btn btn--primary" disabled={saving}>
                {saving ? 'Assigning…' : 'Assign to job'}
              </button>
            </div>
          </form>

          <div>
            <div className="field__label" style={{ marginBottom: 8 }}>
              Current crew
            </div>
            {job.crew.length === 0 ? (
              <div className="muted small">No workers assigned yet.</div>
            ) : (
              <ul className="crew-list">
                {job.crew.map((c) => (
                  <li key={c.assignment_id}>
                    <span>
                      <span className="strong">{c.full_name}</span> <span className="muted small">· {c.trade}</span>
                    </span>
                    <button
                      type="button"
                      className="btn btn--ghost btn--sm"
                      onClick={() => remove(c.assignment_id, c.full_name)}
                    >
                      Remove
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </>
      )}
    </Modal>
  )
}
