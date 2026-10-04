import { useMemo, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { api } from '../api/client'
import { useApi } from '../api/useApi'
import DataTable from '../components/DataTable'
import FormField from '../components/FormField'
import { IconPlus } from '../components/Icons'
import Modal from '../components/Modal'
import StatusChip from '../components/StatusChip'
import TopBar from '../components/TopBar'
import { Alert } from '../components/States'
import { useAuth } from '../context/AuthContext'
import {
  errorState,
  formatDate,
  formatDateTime,
  formatHours,
  formatMetres,
  todayISO,
  toLocalInput,
} from '../utils/format'

const METRES_PER_DEGREE_LAT = 111195

/** A point `metres` due north of the site — used by the "simulate GPS" buttons. */
function northOf(site, metres) {
  return {
    lat: (site.latitude + metres / METRES_PER_DEGREE_LAT).toFixed(6),
    lng: site.longitude.toFixed(6),
  }
}

/**
 * Supervisor's time screen: record GPS-stamped entries, review geofence flags, approve or
 * reject. Off-site entries are flagged rather than blocked: GPS drifts and people clock in from
 * the site trailer, so a person decides and the company still pays for time worked.
 */
export default function TimeEntries() {
  const { hasRole } = useAuth()
  const canRecord = hasRole('Admin', 'Supervisor')
  const [searchParams] = useSearchParams()
  const [filters, setFilters] = useState({
    status: searchParams.get('status') || '',
    flagged: searchParams.get('flagged') || '',
    worker: '',
    date: '',
  })
  const { data, loading, error, reload } = useApi('/time-entries', filters)
  const workers = useApi('/users', { role: 'Worker' })
  const sites = useApi('/sites')
  const [recording, setRecording] = useState(false)
  const [clockingOut, setClockingOut] = useState(null)
  const [deciding, setDeciding] = useState(null) // { entry, decision }
  const [banner, setBanner] = useState(null) // { tone, text }

  const siteById = useMemo(() => {
    const map = {}
    ;(sites.data?.sites || []).forEach((s) => (map[s.site_id] = s))
    return map
  }, [sites.data])

  const setFilter = (key) => (e) => setFilters({ ...filters, [key]: e.target.value })

  function showSaved(entry, verb) {
    if (entry.is_flagged) {
      setBanner({
        tone: 'warning',
        text: `Entry #${entry.entry_id} ${verb} and FLAGGED for review — ${entry.flag_reason}.`,
      })
    } else {
      setBanner({
        tone: 'success',
        text: `Entry #${entry.entry_id} ${verb}. Clock-in was ${formatMetres(entry.in_distance_m)} from ${entry.site_name} (inside the ${entry.geofence_radius_m} m geofence).`,
      })
    }
  }

  const columns = [
    {
      key: 'worker',
      header: 'Worker',
      render: (e) => (
        <>
          <div className="cell-title">{e.worker_name}</div>
          <div className="cell-sub">{e.trade}</div>
        </>
      ),
    },
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
    {
      key: 'times',
      header: 'Clock in → out',
      render: (e) => (
        <div className="num">
          {formatDateTime(e.clock_in)}
          <div className="cell-sub">→ {e.clock_out ? formatDateTime(e.clock_out) : 'still clocked in'}</div>
        </div>
      ),
    },
    {
      key: 'hours',
      header: 'Hours',
      align: 'right',
      render: (e) => <span className="num strong">{formatHours(e.hours)}</span>,
    },
    {
      key: 'distance',
      header: 'Distance from site',
      render: (e) => (
        <div className="num small">
          In: {formatMetres(e.in_distance_m)}
          {e.out_distance_m !== null && <> · Out: {formatMetres(e.out_distance_m)}</>}
          <div className="cell-sub">Limit {e.geofence_radius_m} m</div>
        </div>
      ),
    },
    {
      key: 'status',
      header: 'Status',
      render: (e) => (
        <div style={{ maxWidth: 240 }}>
          <div className="row">
            <StatusChip status={e.status} />
            {e.is_flagged && <StatusChip status="Flagged" tone="amber" />}
          </div>
          {e.is_flagged && <span className="flag-reason">⚑ {e.flag_reason}</span>}
          {e.edit_reason && (
            <div className="cell-sub" style={{ marginTop: 4 }}>
              {e.approved_by_name}: “{e.edit_reason}”
            </div>
          )}
        </div>
      ),
    },
    {
      key: 'actions',
      header: '',
      align: 'right',
      render: (e) =>
        canRecord && (
          <div className="actions">
            {!e.clock_out && (
              <button type="button" className="btn btn--navy btn--sm" onClick={() => setClockingOut(e)}>
                Clock out
              </button>
            )}
            {e.clock_out && e.status === 'Pending' && (
              <>
                <button
                  type="button"
                  className="btn btn--success btn--sm"
                  onClick={() => setDeciding({ entry: e, decision: 'Approved' })}
                >
                  Approve
                </button>
                <button
                  type="button"
                  className="btn btn--danger btn--sm"
                  onClick={() => setDeciding({ entry: e, decision: 'Rejected' })}
                >
                  Reject
                </button>
              </>
            )}
          </div>
        ),
    },
  ]

  return (
    <>
      <TopBar
        title="Time Entries"
        subtitle="GPS-verified clock-ins, flagged entries and approvals"
        actions={
          canRecord && (
            <button type="button" className="btn btn--primary" onClick={() => setRecording(true)}>
              <IconPlus size={16} /> Record time entry
            </button>
          )
        }
      />
      <div className="page">
        {banner && (
          <Alert tone={banner.tone} onClose={() => setBanner(null)}>
            {banner.text}
          </Alert>
        )}
        <div className="card">
          <div className="filters">
            <FormField label="Status" htmlFor="te-status">
              <select id="te-status" className="input" value={filters.status} onChange={setFilter('status')}>
                <option value="">All statuses</option>
                <option>Pending</option>
                <option>Approved</option>
                <option>Rejected</option>
              </select>
            </FormField>
            <FormField label="Geofence" htmlFor="te-flagged">
              <select id="te-flagged" className="input" value={filters.flagged} onChange={setFilter('flagged')}>
                <option value="">All entries</option>
                <option value="true">Flagged only</option>
                <option value="false">Not flagged</option>
              </select>
            </FormField>
            <FormField label="Worker" htmlFor="te-worker">
              <select id="te-worker" className="input" value={filters.worker} onChange={setFilter('worker')}>
                <option value="">All workers</option>
                {(workers.data?.users || []).map((w) => (
                  <option key={w.user_id} value={w.user_id}>
                    {w.full_name}
                  </option>
                ))}
              </select>
            </FormField>
            <FormField label="Clock-in date" htmlFor="te-date">
              <input id="te-date" type="date" className="input" value={filters.date} onChange={setFilter('date')} />
            </FormField>
            <button
              type="button"
              className="btn btn--ghost"
              onClick={() => setFilters({ status: '', flagged: '', worker: '', date: '' })}
            >
              Clear filters
            </button>
          </div>
          <DataTable
            columns={columns}
            rows={data?.time_entries}
            rowKey="entry_id"
            loading={loading}
            error={error}
            onRetry={reload}
            rowClassName={(e) => (e.is_flagged ? 'row-flagged' : '')}
            emptyTitle="No time entries match these filters"
            emptyMessage={canRecord ? 'Use “Record time entry” to add one.' : undefined}
          />
        </div>
      </div>

      {recording && (
        <RecordEntryModal
          workers={(workers.data?.users || []).filter((w) => w.is_active)}
          siteById={siteById}
          onClose={() => setRecording(false)}
          onSaved={(entry) => {
            setRecording(false)
            showSaved(entry, 'recorded')
            reload()
          }}
        />
      )}
      {clockingOut && (
        <ClockOutModal
          entry={clockingOut}
          site={siteById[clockingOut.site_id]}
          onClose={() => setClockingOut(null)}
          onSaved={(entry) => {
            setClockingOut(null)
            showSaved(entry, 'clocked out')
            reload()
          }}
        />
      )}
      {deciding && (
        <DecisionModal
          entry={deciding.entry}
          decision={deciding.decision}
          onClose={() => setDeciding(null)}
          onSaved={(entry) => {
            setDeciding(null)
            setBanner({
              tone: entry.status === 'Approved' ? 'success' : 'warning',
              text: `Entry #${entry.entry_id} for ${entry.worker_name} ${entry.status.toLowerCase()}.`,
            })
            reload()
          }}
        />
      )}
    </>
  )
}

/** Buttons that fill a lat/lng pair as if the worker's phone reported that position. */
function GpsHelper({ site, onPick }) {
  if (!site) return null
  return (
    <div className="row small">
      <span className="muted">Simulate phone GPS:</span>
      <button type="button" className="btn btn--secondary btn--sm" onClick={() => onPick(northOf(site, 30))}>
        On site (30 m)
      </button>
      <button type="button" className="btn btn--secondary btn--sm" onClick={() => onPick(northOf(site, 500))}>
        500 m away
      </button>
    </div>
  )
}

const ENTRY_FIELDS = ['user_id', 'job_id', 'clock_in', 'clock_out', 'in_lat', 'in_lng', 'out_lat', 'out_lng']

/**
 * Record a shift. The "Simulate phone GPS" buttons stand in for the mobile app's location
 * reading; the server measures the distance and decides whether to flag the entry.
 */
function RecordEntryModal({ workers, siteById, onClose, onSaved }) {
  const [form, setForm] = useState({
    user_id: '',
    job_id: '',
    clock_in: `${todayISO()}T07:00`,
    clock_out: '',
    in_lat: '',
    in_lng: '',
    out_lat: '',
    out_lng: '',
  })
  const [errors, setErrors] = useState({})
  const [saving, setSaving] = useState(false)

  // Offer the jobs scheduled on the clock-in date (the server still checks the assignment).
  const workDate = form.clock_in.slice(0, 10)
  const jobs = useApi(workDate ? '/jobs' : null, { date: workDate })
  const jobList = jobs.data?.jobs || []
  const job = jobList.find((j) => String(j.job_id) === String(form.job_id))
  const site = job ? siteById[job.site_id] : null

  const update = (changes) => {
    setForm((f) => ({ ...f, ...changes }))
    const cleared = { _form: undefined }
    Object.keys(changes).forEach((k) => (cleared[k] = undefined))
    setErrors((e) => ({ ...e, ...cleared }))
  }
  const set = (field) => (e) => update({ [field]: e.target.value })

  async function submit(e) {
    e.preventDefault()
    setSaving(true)
    const num = (v) => (v === '' ? null : Number(v))
    const body = {
      user_id: num(form.user_id),
      job_id: num(form.job_id),
      clock_in: form.clock_in,
      in_lat: num(form.in_lat),
      in_lng: num(form.in_lng),
    }
    if (form.clock_out) {
      Object.assign(body, { clock_out: form.clock_out, out_lat: num(form.out_lat), out_lng: num(form.out_lng) })
    }
    try {
      const res = await api('/time-entries', { method: 'POST', body })
      onSaved(res.time_entry)
    } catch (err) {
      setErrors(errorState(err, ENTRY_FIELDS))
    } finally {
      setSaving(false)
    }
  }

  return (
    <Modal
      open
      wide
      title="Record time entry"
      onClose={onClose}
      footer={
        <>
          <button type="button" className="btn btn--secondary" onClick={onClose}>
            Cancel
          </button>
          <button type="submit" form="entry-form" className="btn btn--primary" disabled={saving}>
            {saving ? 'Saving…' : 'Save entry'}
          </button>
        </>
      }
    >
      <form id="entry-form" className="form" onSubmit={submit} noValidate>
        {errors._form && <Alert>{errors._form}</Alert>}
        <div className="form-grid">
          <FormField label="Worker" htmlFor="e-worker" error={errors.user_id} required>
            <select id="e-worker" className="input" value={form.user_id} onChange={set('user_id')}>
              <option value="">Select a worker…</option>
              {workers.map((w) => (
                <option key={w.user_id} value={w.user_id}>
                  {w.full_name} — {w.trade}
                </option>
              ))}
            </select>
          </FormField>
          <FormField label="Clock-in" htmlFor="e-in" error={errors.clock_in} required>
            <input id="e-in" type="datetime-local" className="input" value={form.clock_in} onChange={set('clock_in')} />
          </FormField>
          <FormField
            label="Job"
            htmlFor="e-job"
            error={errors.job_id}
            required
            className="span-2"
            hint={workDate ? `Jobs scheduled on ${formatDate(workDate)}` : undefined}
          >
            <select id="e-job" className="input" value={form.job_id} onChange={set('job_id')}>
              <option value="">{jobs.loading ? 'Loading jobs…' : jobList.length ? 'Select a job…' : 'No jobs on this date'}</option>
              {jobList.map((j) => (
                <option key={j.job_id} value={j.job_id}>
                  {j.title} — {j.site_name}
                </option>
              ))}
            </select>
          </FormField>
        </div>

        {site && (
          <div className="info-box">
            <strong>{site.site_name}</strong> is at {site.latitude.toFixed(6)}, {site.longitude.toFixed(6)} with a{' '}
            <strong>{site.geofence_radius_m} m</strong> geofence. Readings farther than that are saved but flagged.
          </div>
        )}

        <div className="form-grid">
          <FormField label="Clock-in latitude" htmlFor="e-inlat" error={errors.in_lat} required>
            <input id="e-inlat" type="number" step="0.000001" className="input" value={form.in_lat} onChange={set('in_lat')} />
          </FormField>
          <FormField label="Clock-in longitude" htmlFor="e-inlng" error={errors.in_lng} required>
            <input id="e-inlng" type="number" step="0.000001" className="input" value={form.in_lng} onChange={set('in_lng')} />
          </FormField>
          <div className="span-2">
            <GpsHelper site={site} onPick={({ lat, lng }) => update({ in_lat: lat, in_lng: lng })} />
          </div>
        </div>

        <div className="form-grid">
          <FormField
            label="Clock-out (optional)"
            htmlFor="e-out"
            error={errors.clock_out}
            className="span-2"
            hint="Leave blank if the worker is still on shift. A shift may end the next day."
          >
            <input id="e-out" type="datetime-local" className="input" value={form.clock_out} onChange={set('clock_out')} />
          </FormField>
          {form.clock_out && (
            <>
              <FormField label="Clock-out latitude" htmlFor="e-outlat" error={errors.out_lat} required>
                <input id="e-outlat" type="number" step="0.000001" className="input" value={form.out_lat} onChange={set('out_lat')} />
              </FormField>
              <FormField label="Clock-out longitude" htmlFor="e-outlng" error={errors.out_lng} required>
                <input id="e-outlng" type="number" step="0.000001" className="input" value={form.out_lng} onChange={set('out_lng')} />
              </FormField>
              <div className="span-2">
                <GpsHelper site={site} onPick={({ lat, lng }) => update({ out_lat: lat, out_lng: lng })} />
              </div>
            </>
          )}
        </div>
      </form>
    </Modal>
  )
}

/**
 * Close an open entry. The clock-out position is checked against the geofence as well.
 */
function ClockOutModal({ entry, site, onClose, onSaved }) {
  const [form, setForm] = useState({ clock_out: toLocalInput(new Date()), out_lat: '', out_lng: '' })
  const [errors, setErrors] = useState({})
  const [saving, setSaving] = useState(false)

  const update = (changes) => {
    setForm((f) => ({ ...f, ...changes }))
    setErrors({})
  }

  async function submit(e) {
    e.preventDefault()
    setSaving(true)
    try {
      const res = await api(`/time-entries/${entry.entry_id}/clock-out`, {
        method: 'PATCH',
        body: {
          clock_out: form.clock_out,
          out_lat: form.out_lat === '' ? null : Number(form.out_lat),
          out_lng: form.out_lng === '' ? null : Number(form.out_lng),
        },
      })
      onSaved(res.time_entry)
    } catch (err) {
      setErrors(errorState(err, ['clock_out', 'out_lat', 'out_lng']))
    } finally {
      setSaving(false)
    }
  }

  return (
    <Modal
      open
      title="Clock out"
      onClose={onClose}
      footer={
        <>
          <button type="button" className="btn btn--secondary" onClick={onClose}>
            Cancel
          </button>
          <button type="submit" form="clockout-form" className="btn btn--primary" disabled={saving}>
            {saving ? 'Saving…' : 'Clock out'}
          </button>
        </>
      }
    >
      <div className="info-box">
        <strong>{entry.worker_name}</strong> · {entry.job_title}
        <br />
        Clocked in {formatDateTime(entry.clock_in)} at {entry.site_name}
      </div>
      <form id="clockout-form" className="form" onSubmit={submit} noValidate>
        {errors._form && <Alert>{errors._form}</Alert>}
        <FormField label="Clock-out time" htmlFor="co-time" error={errors.clock_out} required>
          <input
            id="co-time"
            type="datetime-local"
            className="input"
            value={form.clock_out}
            onChange={(e) => update({ clock_out: e.target.value })}
          />
        </FormField>
        <div className="form-grid">
          <FormField label="Latitude" htmlFor="co-lat" error={errors.out_lat} required>
            <input id="co-lat" type="number" step="0.000001" className="input" value={form.out_lat} onChange={(e) => update({ out_lat: e.target.value })} />
          </FormField>
          <FormField label="Longitude" htmlFor="co-lng" error={errors.out_lng} required>
            <input id="co-lng" type="number" step="0.000001" className="input" value={form.out_lng} onChange={(e) => update({ out_lng: e.target.value })} />
          </FormField>
        </div>
        <GpsHelper site={site} onPick={({ lat, lng }) => update({ out_lat: lat, out_lng: lng })} />
      </form>
    </Modal>
  )
}

/**
 * Approve or reject with a mandatory reason, stored with the supervisor's name as the audit trail.
 */
function DecisionModal({ entry, decision, onClose, onSaved }) {
  const [reason, setReason] = useState('')
  const [errors, setErrors] = useState({})
  const [saving, setSaving] = useState(false)
  const approving = decision === 'Approved'

  async function submit(e) {
    e.preventDefault()
    if (!reason.trim()) return setErrors({ edit_reason: 'A reason is required for the audit trail.' })
    setSaving(true)
    try {
      const res = await api(`/time-entries/${entry.entry_id}/approve`, {
        method: 'PATCH',
        body: { decision, edit_reason: reason },
      })
      onSaved(res.time_entry)
    } catch (err) {
      setErrors(errorState(err, ['edit_reason', 'decision']))
    } finally {
      setSaving(false)
    }
  }

  return (
    <Modal
      open
      title={approving ? 'Approve time entry' : 'Reject time entry'}
      onClose={onClose}
      footer={
        <>
          <button type="button" className="btn btn--secondary" onClick={onClose}>
            Cancel
          </button>
          <button
            type="submit"
            form="decision-form"
            className={`btn ${approving ? 'btn--success' : 'btn--danger'}`}
            disabled={saving}
          >
            {saving ? 'Saving…' : approving ? 'Approve' : 'Reject'}
          </button>
        </>
      }
    >
      <div className="info-box">
        <strong>{entry.worker_name}</strong> · {entry.job_title}
        <br />
        {formatDateTime(entry.clock_in)} → {formatDateTime(entry.clock_out)} · <strong>{formatHours(entry.hours)}</strong>
      </div>
      {entry.is_flagged && <Alert tone="warning">⚑ Flagged: {entry.flag_reason}</Alert>}
      <form id="decision-form" className="form" onSubmit={submit} noValidate>
        {errors._form && <Alert>{errors._form}</Alert>}
        <FormField label="Reason" htmlFor="d-reason" error={errors.edit_reason} required hint="Saved with your name as the audit trail.">
          <textarea
            id="d-reason"
            className="input"
            rows={3}
            value={reason}
            onChange={(e) => {
              setReason(e.target.value)
              setErrors({})
            }}
            placeholder={approving ? 'e.g. Foreman confirmed worker was in the site trailer' : 'e.g. Worker was not on site'}
          />
        </FormField>
      </form>
    </Modal>
  )
}
