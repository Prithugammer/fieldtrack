import { useEffect, useState } from 'react'
import '../styles/safety.css'
import { api, apiDownload } from '../api/client'

const TABS = [
  { id: 'alerts', label: 'Alerts' },
  { id: 'messages', label: 'Messages' },
  { id: 'audit', label: 'Audit log' },
]

const CHANNELS = {
  worker: 'To worker',
  supervisor: 'To supervisor',
  emergency_services: 'Emergency call (mock)',
}

const time = (iso) => (iso ? new Date(iso).toLocaleTimeString() : '')

function mmss(seconds) {
  const s = Math.max(0, Math.round(seconds ?? 0))
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`
}

function describeMode(config) {
  return `${config.mode} mode · idle ${config.idle_threshold_seconds} s · ${config.num_checkins} check-ins of ${config.checkin_response_window_seconds} s`
}

function AlertCard({ alert, onAction }) {
  const [note, setNote] = useState('')
  const { location: loc, nearest_coworker: near } = alert
  const id = alert.worker_id
  return (
    <li className={`safety-alert safety-alert--${alert.level}`}>
      <div className="safety-alert__head">
        <span
          className={`chip chip--${alert.level === 'critical' ? 'red' : alert.level === 'warning' ? 'amber' : 'navy'}`}
        >
          {alert.stage}
        </span>
        <strong>{alert.worker_name}</strong>
        <span className="muted small safety-alert__elapsed">
          {mmss(alert.elapsed_s)} elapsed
          {alert.window_remaining_s !== null && ` · reply window ${mmss(alert.window_remaining_s)}`}
        </span>
      </div>
      <div className="small">
        Last known location: <strong>{loc.label}</strong>
        {loc.lat !== null && (
          <span className="muted">
            {' '}
            ({loc.lat.toFixed(5)}, {loc.lng.toFixed(5)})
          </span>
        )}
      </div>
      <div className="small muted">
        {alert.trigger === 'sos' ? 'Worker pressed SOS' : 'No movement detected'}
        {alert.incapacitated && ' · accident: worker cannot reply'}
        {alert.started_at && ` · since ${time(alert.started_at)}`}
      </div>
      <div className="small">
        {near ? (
          <>
            Nearest available co-worker:{' '}
            <strong>
              {near.name}
              {near.trade && ` (${near.trade})`}
            </strong>
            , {near.distance_m >= 1000 ? `${(near.distance_m / 1000).toFixed(1)} km` : `${near.distance_m} m`}{' '}
            away
          </>
        ) : (
          <span className="muted">No available co-worker nearby.</span>
        )}
      </div>
      {alert.state === 'EMERGENCY' && onAction && (
        <div className="safety-alert__actions">
          <input
            className="input safety-alert__note"
            type="text"
            maxLength={500}
            placeholder="Note (optional)"
            aria-label={`Resolution note for ${alert.worker_name}`}
            value={note}
            onChange={(e) => setNote(e.target.value)}
          />
          <button
            type="button"
            className="btn btn--danger btn--sm"
            onClick={() => onAction(`workers/${id}/resolve`, { outcome: 'real_incident', note })}
          >
            Resolved – real incident
          </button>
          <button
            type="button"
            className="btn btn--secondary btn--sm"
            onClick={() => onAction(`workers/${id}/resolve`, { outcome: 'false_alarm', note })}
          >
            Resolved – false alarm
          </button>
        </div>
      )}
      {alert.state === 'POST_INCIDENT' && (
        <div className="safety-alert__actions">
          <span className="small muted">
            {alert.resolution?.note ? `Note: ${alert.resolution.note}` : 'Real incident resolved.'}
          </span>
          {onAction && (
            <button
              type="button"
              className="btn btn--secondary btn--sm"
              onClick={() => onAction(`workers/${id}/return-to-duty`)}
            >
              Return to duty
            </button>
          )}
        </div>
      )}
    </li>
  )
}

function Messages({ notifications, workers, onAction }) {
  if (!notifications.length) {
    return (
      <p className="muted small safety-panel__empty">
        No messages yet. Check-ins appear here as they are sent.
      </p>
    )
  }
  // A worker can reply to their newest check-in only while it is still open.
  const waiting = new Set(
    workers.filter((w) => w.safety?.checkin > 0 && !w.safety.incapacitated).map((w) => w.id),
  )
  const newestCheckin = {}
  notifications.forEach((n) => {
    if (n.channel === 'worker' && newestCheckin[n.worker_id] === undefined) newestCheckin[n.worker_id] = n.id
  })
  return (
    <ul className="safety-feed">
      {notifications.map((n) => (
        <li key={n.id} className={`safety-feed__item safety-feed__item--${n.channel}`}>
          <div className="small">
            <span className="muted">{time(n.time)}</span> · <strong>{CHANNELS[n.channel]}</strong> ·{' '}
            {n.worker_name}
          </div>
          <div className="small">{n.text}</div>
          {n.channel === 'worker' &&
            newestCheckin[n.worker_id] === n.id &&
            waiting.has(n.worker_id) &&
            onAction && (
              <button
                type="button"
                className="btn btn--success btn--sm"
                onClick={() => onAction(`workers/${n.worker_id}/respond`)}
              >
                Reply “I’m OK” as {n.worker_name}
              </button>
            )}
        </li>
      ))}
    </ul>
  )
}

function AuditLog() {
  const [entries, setEntries] = useState(null)
  const [error, setError] = useState(null)

  useEffect(() => {
    let live = true
    const load = () =>
      api('/safety/audit')
        .then((rows) => live && (setEntries(rows.slice().reverse()), setError(null)))
        .catch((err) => live && setError(err.message))
    load()
    const id = setInterval(load, 2000)
    return () => {
      live = false
      clearInterval(id)
    }
  }, [])

  return (
    <>
      <div className="safety-panel__toolbar">
        <button
          type="button"
          className="btn btn--secondary btn--sm"
          onClick={() => apiDownload('/safety/audit', { format: 'csv' }, 'safety-audit-log.csv')}
        >
          Export CSV
        </button>
        <button
          type="button"
          className="btn btn--secondary btn--sm"
          onClick={() => apiDownload('/safety/audit', { format: 'json-file' }, 'safety-audit-log.json')}
        >
          Export JSON
        </button>
      </div>
      {error && <p className="small safety-panel__empty">{error}</p>}
      {entries && !entries.length && (
        <p className="muted small safety-panel__empty">No safety events recorded yet.</p>
      )}
      {entries && entries.length > 0 && (
        <div className="table-wrap safety-panel__scroll">
          <table className="table">
            <thead>
              <tr>
                <th>Time</th>
                <th>Worker</th>
                <th>Event</th>
                <th>Details</th>
              </tr>
            </thead>
            <tbody>
              {entries.map((e) => (
                <tr key={e.id}>
                  <td>{time(e.time)}</td>
                  <td>{e.worker_name}</td>
                  <td>{e.event}</td>
                  <td>
                    {e.message}
                    {e.actor && <span className="muted"> — {e.actor}</span>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </>
  )
}

/**
 * Safety / emergency panel: active alerts with the supervisor's resolve buttons, the worker-side
 * message log (where a simulated worker can answer a check-in), and the audit log.
 * `safety` is the "safety" block of the live-map state. `onAction` is null for roles that may only
 * watch (Dispatcher), which hides every control.
 */
export default function SafetyPanel({ safety, workers, onAction }) {
  const [tab, setTab] = useState('alerts')
  const { alerts, notifications, config } = safety
  const critical = alerts.filter((a) => a.level === 'critical').length

  return (
    <section
      className={`card safety-panel${critical ? ' safety-panel--critical' : ''}`}
      aria-label="Safety and emergency"
    >
      <div className="safety-panel__header">
        <div className="safety-panel__title">
          <strong>Safety</strong>
          {alerts.length === 0 ? (
            <span className="chip chip--green">All clear</span>
          ) : (
            <span className={`chip chip--${critical ? 'red' : 'amber'}`} role="status">
              {critical
                ? `${critical} emergency${critical > 1 ? ' alerts' : ''}`
                : `${alerts.length} active alert${alerts.length > 1 ? 's' : ''}`}
            </span>
          )}
          <span className="muted small">{describeMode(config)}</span>
        </div>
        <div className="safety-panel__tabs" role="tablist">
          {TABS.map((t) => (
            <button
              key={t.id}
              type="button"
              role="tab"
              aria-selected={tab === t.id}
              className={`safety-panel__tab${tab === t.id ? ' is-active' : ''}`}
              onClick={() => setTab(t.id)}
            >
              {t.label}
              {t.id === 'alerts' && alerts.length > 0 && ` (${alerts.length})`}
            </button>
          ))}
        </div>
      </div>
      <div className="safety-panel__body">
        {tab === 'alerts' &&
          (alerts.length ? (
            <ul className="safety-alerts">
              {alerts.map((a) => (
                <AlertCard key={a.worker_id} alert={a} onAction={onAction} />
              ))}
            </ul>
          ) : (
            <p className="muted small safety-panel__empty">
              No active alerts. A worker still for {config.idle_threshold_seconds} s while on shift gets a
              safety check-in.
            </p>
          ))}
        {tab === 'messages' && (
          <Messages notifications={notifications} workers={workers} onAction={onAction} />
        )}
        {tab === 'audit' && <AuditLog />}
      </div>
      <p className="muted small safety-panel__privacy">{safety.privacy_note}</p>
    </section>
  )
}
