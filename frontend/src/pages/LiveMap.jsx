import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import L from 'leaflet'
import { Circle, MapContainer, Marker, Polyline, Popup, TileLayer, useMapEvents } from 'react-leaflet'
import 'leaflet/dist/leaflet.css'
import '../styles/live-map.css'
import { api } from '../api/client'
import { useApi } from '../api/useApi'
import SafetyPanel from '../components/SafetyPanel'
import TopBar from '../components/TopBar'
import { Alert, EmptyState, ErrorState, LoadingState } from '../components/States'
import { useAuth } from '../context/AuthContext'
import { useTheme } from '../context/ThemeContext'

// Positions are SIMULATED on the server (backend/simulation.py) — there is no mobile app
// yet — and refreshed on this interval. Markers glide in a straight line between polls (see
// live-map.css), so polls are kept short enough (~100 m of road) that the glide hugs the road.
const POLL_MS = 1000
// How long markers fade when the simulated morning restarts (matches live-map.css).
const FADE_MS = 600
// Base map: Stadia Maps "Alidade Smooth" — English place names, a light and a dark style to
// match the app theme, and {r} asks for sharp @2x tiles on high-density screens. It is free
// without a key on localhost; a hosted deployment needs a free Stadia account for its domain.
const TILES = {
  light: 'https://tiles.stadiamaps.com/tiles/alidade_smooth/{z}/{x}/{y}{r}.png',
  dark: 'https://tiles.stadiamaps.com/tiles/alidade_smooth_dark/{z}/{x}/{y}{r}.png',
}
const TILE_ATTRIBUTION =
  '&copy; <a href="https://stadiamaps.com/">Stadia Maps</a> &copy; <a href="https://openmaptiles.org/">OpenMapTiles</a> &copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
// The selected worker's route: a white line with a thin dark edge, so it reads on both the
// light and the dark base map.
const ROUTE_CASING = { color: '#14213d', weight: 7, opacity: 0.45, lineCap: 'round', lineJoin: 'round' }
const ROUTE_LINE = { color: '#ffffff', weight: 4, opacity: 1, lineCap: 'round', lineJoin: 'round' }
// On-site workers sharing a site fan out on a ring this many pixels around the site.
const FAN_RADIUS_PX = 11

const WORKER_VARIANTS = {
  'On site': 'onsite',
  'In transit': 'transit',
  'Off duty': 'off',
}

// One icon object per look: react-leaflet replaces the marker element whenever the icon
// object changes, which would cut the glide short, so icons are created once and reused.
const iconCache = {}
// Marker look for a worker: safety states win over the normal commute colours.
function workerVariant(w) {
  if (w.status === 'EMERGENCY') return 'emergency'
  if (w.status === 'Post-incident') return 'incident'
  if (w.safety?.checkin > 0) return 'warning'
  if (w.status === 'Stopped') return 'stopped'
  return w.near_traffic ? 'traffic' : WORKER_VARIANTS[w.status]
}

function workerIcon(variant, dx = 0, dy = 0, ghost = false) {
  const key = `${variant}:${dx}:${dy}:${ghost}`
  if (!iconCache[key]) {
    iconCache[key] = L.divIcon({
      className: ghost ? 'ft-ghost' : 'ft-glide',
      html: `<span class="ft-worker ft-worker--${variant}"></span>`,
      iconSize: [18, 18],
      iconAnchor: [9 - dx, 9 - dy],
      popupAnchor: [dx, dy - 10],
    })
  }
  return iconCache[key]
}

const siteIcon = L.divIcon({
  className: 'ft-site-icon',
  html: '<span class="ft-site"></span>',
  iconSize: [16, 16],
  iconAnchor: [8, 8],
  popupAnchor: [0, -8],
})

/**
 * Where to draw each worker. On-site workers who share a site would sit on the same spot,
 * so they are spread evenly on a small ring around the site, in user_id order. The offset
 * is in screen pixels (so they stay apart at every zoom); the API coordinates are unchanged.
 */
function placeWorkers(live) {
  const sites = Object.fromEntries(live.job_sites.map((s) => [s.name, s]))
  const onSite = {}
  live.workers
    .filter((w) => w.status === 'On site')
    .forEach((w) => (onSite[w.site_name] = [...(onSite[w.site_name] || []), w.id]))

  return live.workers
    .filter((w) => w.lat !== null)
    .map((w) => {
      const variant = workerVariant(w)
      const group = w.status === 'On site' ? onSite[w.site_name] : null
      const site = sites[w.site_name]
      if (group && group.length > 1 && site) {
        const ids = [...group].sort((a, b) => a - b)
        const angle = (2 * Math.PI * ids.indexOf(w.id)) / ids.length - Math.PI / 2
        const dx = Math.round(FAN_RADIUS_PX * Math.cos(angle))
        const dy = Math.round(FAN_RADIUS_PX * Math.sin(angle))
        return { w, variant, dx, dy, position: [site.lat, site.lng] }
      }
      return { w, variant, dx: 0, dy: 0, position: [w.lat, w.lng] }
    })
}

/**
 * Leaflet makes every clickable marker a focusable role="button" with no text, so name it for
 * screen readers once it is on the map (the popup it opens holds the details).
 */
function markerName(label) {
  return { add: (e) => e.target.getElement()?.setAttribute('aria-label', label) }
}

/** Turn the glide off while Leaflet zooms, otherwise markers trail behind the map. */
function ZoomGlideGuard() {
  const timer = useRef(null)
  const map = useMapEvents({
    zoomstart() {
      clearTimeout(timer.current)
      map.getContainer().classList.add('ft-no-glide')
    },
    zoomend() {
      timer.current = setTimeout(() => map.getContainer().classList.remove('ft-no-glide'), 50)
    },
  })
  useEffect(() => () => clearTimeout(timer.current), [])
  return null
}

/** "New cycle in 2:13" plus a thin progress bar, ticking every second between polls. */
function CycleCountdown({ resetAt, cycleSeconds }) {
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), 1000)
    return () => clearInterval(id)
  }, [])
  const left = Math.max(0, Math.round((resetAt - now) / 1000))
  const done = Math.min(1, Math.max(0, 1 - left / cycleSeconds))
  return (
    <span className="live-map__cycle" title="The simulated morning replays on a loop">
      <span className="live-map__cycle-bar">
        <span style={{ width: `${done * 100}%` }} />
      </span>
      <span>
        New cycle in {Math.floor(left / 60)}:{String(left % 60).padStart(2, '0')}
      </span>
    </span>
  )
}

function formatKm(m) {
  return m >= 1000 ? `${(m / 1000).toFixed(1)} km` : `${m} m`
}

/**
 * Popup section: the worker's safety state, plus the demo controls that stand in for the worker's
 * phone and for chance (trigger an accident, press SOS, reply "I'm OK", start/end a break).
 */
function SafetyControls({ worker: w, onAction }) {
  const s = w.safety
  if (!s) return null
  const onShift = ['On site', 'In transit'].includes(w.sim_status)
  const flagged = s.state !== 'NORMAL'
  return (
    <>
      {flagged && (
        <div className="map-popup__safety">
          {s.state === 'EMERGENCY' && 'EMERGENCY — awaiting supervisor'}
          {s.state === 'POST_INCIDENT' && 'Post-incident'}
          {s.checkin > 0 && `Safety check-in ${s.checkin} unanswered`}
        </div>
      )}
      {s.on_break && <div className="muted">On break</div>}
      {s.break_zone && <div className="muted">In rest area: {s.break_zone}</div>}
      {onAction && (
        <div className="map-popup__actions">
          {s.checkin > 0 && !s.incapacitated && (
            <button
              type="button"
              className="btn btn--success btn--sm"
              onClick={() => onAction(`workers/${w.id}/respond`)}
            >
              I&apos;m OK
            </button>
          )}
          {(onShift || s.stopped) && s.state !== 'EMERGENCY' && !s.stopped && (
            <button
              type="button"
              className="btn btn--danger btn--sm"
              onClick={() => onAction(`workers/${w.id}/accident`)}
            >
              Trigger accident
            </button>
          )}
          {(onShift || s.stopped) && s.state !== 'EMERGENCY' && (
            <button
              type="button"
              className="btn btn--danger btn--sm"
              onClick={() => onAction(`workers/${w.id}/sos`)}
            >
              SOS
            </button>
          )}
          {onShift && !s.stopped && (
            <button
              type="button"
              className="btn btn--secondary btn--sm"
              onClick={() => onAction(`workers/${w.id}/break`, { on_break: !s.on_break })}
            >
              {s.on_break ? 'End break' : 'Start break'}
            </button>
          )}
        </div>
      )}
    </>
  )
}

/**
 * Stand-in for the future mobile app's live GPS: polls the simulated positions computed by
 * backend/simulation.py. Simulated (not random) so every demo is repeatable and still shows the
 * real ideas: geofences, traffic delays, and workers arriving on site.
 */
export default function LiveMap() {
  const { theme } = useTheme()
  const bounds = useApi('/map/bounds')
  const [live, setLive] = useState(null)
  const [clock, setClock] = useState(null)
  const [error, setError] = useState(null)
  // Markers from the cycle that just ended, fading out while the new cycle fades in.
  const [ghosts, setGhosts] = useState([])
  const [entering, setEntering] = useState(false)
  const prevLive = useRef(null)
  // The worker whose popup is open: their remaining route is fetched with each poll and drawn.
  const [selected, setSelected] = useState(null)
  const selectedRef = useRef(null)
  const fadeTimer = useRef(null)
  const mapRef = useRef(null)
  const [actionError, setActionError] = useState(null)
  // Only Supervisors and Admins may change safety state. Hiding the controls is a convenience;
  // the server enforces the same rule (403).
  const { hasRole } = useAuth()
  const canControl = hasRole('Supervisor', 'Admin')

  // One request at a time: if the server is slow, polls are skipped instead of piling up.
  const inFlight = useRef(false)

  const poll = useCallback(async () => {
    if (inFlight.current) return
    inFlight.current = true
    try {
      const [state, sim] = await Promise.all([
        // Read-only: the server advances safety escalation by itself (backend heartbeat), so this
        // page only observes. Closing it never stops monitoring.
        api('/map/live', { params: { route: selectedRef.current } }),
        api('/map/sim-clock'),
      ])
      const prev = prevLive.current
      if (prev && prev.cycle !== state.cycle) {
        setGhosts(placeWorkers(prev).filter((p) => p.variant !== 'off'))
        setEntering(true)
        clearTimeout(fadeTimer.current)
        fadeTimer.current = setTimeout(() => {
          setGhosts([])
          setEntering(false)
        }, FADE_MS + 100)
      }
      prevLive.current = state
      setLive(state)
      setClock({ ...sim, resetAt: Date.now() + sim.seconds_to_reset * 1000 })
      setError(null)
    } catch (err) {
      setError(err)
    } finally {
      inFlight.current = false
    }
  }, [])

  // A safety control (accident, SOS, "I'm OK", resolve...): POST it, then refresh straight away.
  const safetyAction = useCallback(
    async (path, body) => {
      try {
        await api(`/safety/${path}`, { method: 'POST', body })
        setActionError(null)
        await poll()
      } catch (err) {
        setActionError(err.message)
      }
    },
    [poll],
  )

  // Select a worker (their popup opened) or clear the selection (it closed). Polls straight
  // away so the route appears without waiting for the next tick.
  const select = useCallback(
    (id) => {
      selectedRef.current = id
      setSelected(id)
      if (id !== null) poll()
    },
    [poll],
  )

  useEffect(() => {
    poll()
    const id = setInterval(poll, POLL_MS)
    return () => {
      clearInterval(id)
      clearTimeout(fadeTimer.current)
    }
  }, [poll])

  // Opening view: all job sites with some margin, so geofence circles are big enough to
  // read. Panning is limited to the valley plus 25%, so a fast drag can't fling the map away.
  // Computed once, when the first data arrives; later polls never move the map.
  const view = useMemo(() => {
    if (!bounds.data || !live) return null
    const b = bounds.data
    const valley = L.latLngBounds([b.south, b.west], [b.north, b.east])
    // Sites outside the road network (routable === false) would stretch the view across the globe.
    const shown = live.job_sites.filter((s) => s.routable !== false)
    const sites = shown.length ? L.latLngBounds(shown.map((s) => [s.lat, s.lng])).pad(0.15) : valley
    return { start: sites, max: valley.pad(0.25) }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [bounds.data, live === null])

  const workers = live?.workers || []
  const selectedPath = workers.find((w) => w.id === selected)?.path || null
  const count = (pred) => workers.filter(pred).length
  const legend = [
    { variant: 'onsite', label: 'On site', n: count((w) => w.status === 'On site') },
    {
      variant: 'transit',
      label: 'In transit',
      n: count((w) => w.status === 'In transit' && !w.near_traffic),
    },
    { variant: 'traffic', label: 'Delayed in traffic', n: count((w) => w.near_traffic) },
    { variant: 'off', label: 'Off duty', n: count((w) => w.status === 'Off duty') },
    { variant: 'warning', label: 'Safety check-in', n: count((w) => w.safety?.checkin > 0) },
    { variant: 'emergency', label: 'EMERGENCY', n: count((w) => w.status === 'EMERGENCY') },
  ]
  const notStarted = count((w) => w.status === 'Not started')
  const unroutableSites = (live?.job_sites || []).filter((s) => s.routable === false)
  const routeUnavailable = count((w) => w.status === 'Route unavailable')
  // Is the server really advancing safety escalation? If not, say so instead of showing a calm, stale map.
  const monitoring = live?.safety?.monitoring
  const monitoringOff = Boolean(monitoring) && monitoring.background === false
  const persistenceFailing = monitoring?.persistence?.enabled === true && monitoring.persistence.ok === false
  const monitoringStale = Boolean(monitoring) && (monitoring.age_s === null || monitoring.age_s > 10)

  let body
  if ((bounds.error || error) && !live) {
    body = (
      <ErrorState
        message={(bounds.error || error).message}
        onRetry={() => {
          bounds.reload()
          poll()
        }}
      />
    )
  } else if (!live || !view) {
    body = <LoadingState label="Loading map…" />
  } else if (live.job_sites.length === 0) {
    body = <EmptyState title="No job sites yet" message="Add a job site to see it on the map." />
  } else {
    body = (
      <div className={`live-map${entering ? ' live-map--entering' : ''}`}>
        <MapContainer
          ref={mapRef}
          bounds={view.start}
          maxBounds={view.max}
          maxBoundsViscosity={1}
          minZoom={10}
          // quarter-step zoom so the sites fill the frame instead of the next whole level out
          zoomSnap={0.25}
          zoomDelta={0.5}
          scrollWheelZoom
          className="live-map__canvas"
        >
          <ZoomGlideGuard />
          <TileLayer key={theme} url={TILES[theme]} attribution={TILE_ATTRIBUTION} maxZoom={20} />
          {live.job_sites.map((s) => (
            <Circle
              key={`fence-${s.id}`}
              center={[s.lat, s.lng]}
              radius={s.radius_m}
              pathOptions={{ color: '#ff7a00', weight: 2, fillOpacity: 0.18 }}
              interactive={false}
            />
          ))}
          {live.job_sites.map((s) => (
            <Marker
              key={`site-${s.id}`}
              position={[s.lat, s.lng]}
              icon={siteIcon}
              zIndexOffset={-100}
              eventHandlers={markerName(`Job site: ${s.name}`)}
            >
              <Popup>
                <div className="map-popup">
                  <strong>{s.name}</strong>
                  <div className="muted">{s.address}</div>
                  {s.jobs_today.length ? (
                    s.jobs_today.map((t) => <div key={t}>Today: {t}</div>)
                  ) : (
                    <div className="muted">No jobs scheduled today</div>
                  )}
                  <div className="muted">Geofence {s.radius_m} m</div>
                </div>
              </Popup>
            </Marker>
          ))}
          {selectedPath && (
            <Polyline positions={selectedPath} pathOptions={ROUTE_CASING} interactive={false} />
          )}
          {selectedPath && <Polyline positions={selectedPath} pathOptions={ROUTE_LINE} interactive={false} />}
          {ghosts.map(({ w, variant, dx, dy, position }) => (
            <Marker
              key={`ghost-${w.id}-${prevLive.current?.cycle}`}
              position={position}
              icon={workerIcon(variant, dx, dy, true)}
              interactive={false}
            />
          ))}
          {placeWorkers(live).map(({ w, variant, dx, dy, position }) => (
            // Keyed by cycle (except off-duty workers, who never move): when the simulated
            // morning restarts, markers fade in at their start points instead of gliding
            // across the whole valley.
            <Marker
              key={w.status === 'Off duty' ? `${w.id}` : `${w.id}-${live.cycle}`}
              position={position}
              icon={workerIcon(variant, dx, dy)}
              eventHandlers={{
                ...markerName(`Worker: ${w.name}`),
                popupopen: () => select(w.id),
                popupclose: () => selectedRef.current === w.id && select(null),
              }}
            >
              <Popup>
                <div className="map-popup">
                  <div>
                    <strong>{w.name}</strong> <span className="muted">· {w.trade}</span>
                  </div>
                  <div>{w.job_title ? `${w.job_title} — ${w.site_name}` : 'No job today'}</div>
                  <div>
                    {w.status}
                    {w.status === 'In transit' && w.distance_remaining_m !== null && (
                      <>
                        {' · '}
                        <strong>{formatKm(w.distance_remaining_m)} left</strong>
                        <span className="muted"> to site</span>
                      </>
                    )}
                  </div>
                  {w.near_traffic && <div className="map-popup__delay">Delayed near {w.hotspot}</div>}
                  <SafetyControls worker={w} onAction={canControl ? safetyAction : null} />
                </div>
              </Popup>
            </Marker>
          ))}
        </MapContainer>
        <button
          type="button"
          className="btn btn--secondary btn--sm live-map__reset"
          onClick={() => mapRef.current?.fitBounds(view.start)}
        >
          Reset view
        </button>
      </div>
    )
  }

  return (
    <>
      <TopBar
        title="Live Map"
        subtitle="Simulated worker GPS across the Kathmandu Valley"
        actions={
          clock && (
            <span className="live-map__clock-group">
              <span
                className="chip chip--navy live-map__clock"
                title={`Simulated ${clock.window_start}–${clock.window_end}, repeating every ${clock.cycle_seconds / 60} real minutes`}
              >
                Simulated time: {clock.sim_time}
              </span>
              <CycleCountdown resetAt={clock.resetAt} cycleSeconds={clock.cycle_seconds} />
            </span>
          )
        }
      />
      <div className="page">
        {error && live && (
          <Alert tone="warning">Lost connection to the server — retrying. {error.message}</Alert>
        )}
        {persistenceFailing && (
          <Alert tone="warning">
            The server could not save safety events ({monitoring.persistence.unsaved_events} waiting). They
            are kept in memory and retried every second, but would be lost if the server restarted now.
          </Alert>
        )}
        {monitoringOff && (
          <Alert tone="warning">
            Safety monitoring is not running on the server, so check-ins and emergencies will not escalate.
            Start the backend with <code>python app.py</code> (or <code>wsgi.py</code>) and keep
            SAFETY_TICKER_ENABLED on.
          </Alert>
        )}
        {!monitoringOff && monitoringStale && (
          <Alert tone="warning">
            Safety monitoring has not updated
            {monitoring.age_s === null ? ' yet' : ` for ${Math.round(monitoring.age_s)} s`}. Alerts on this
            screen may be out of date.
          </Alert>
        )}
        {unroutableSites.length > 0 && (
          <Alert tone="warning">
            {unroutableSites.length === 1 ? '1 job site is' : `${unroutableSites.length} job sites are`}{' '}
            outside the supported road network ({unroutableSites.map((s) => s.name).join(', ')}). Workers
            assigned there are not shown on the map ({routeUnavailable} affected).
          </Alert>
        )}
        {actionError && (
          <Alert tone="error" onClose={() => setActionError(null)}>
            {actionError}
          </Alert>
        )}
        {live?.safety && (
          <SafetyPanel safety={live.safety} workers={workers} onAction={canControl ? safetyAction : null} />
        )}
        <div className="card">
          <div className="live-map__legend">
            {legend.map((item) => (
              <span key={item.variant} className="live-map__legend-item">
                {/* every symbol sits in the same fixed-size slot so the labels line up */}
                <span className="live-map__swatch">
                  <span className={`ft-worker ft-worker--${item.variant}`} />
                </span>
                <span>
                  {item.label}
                  {live && <span className="muted live-map__count">{item.n}</span>}
                </span>
              </span>
            ))}
            <span className="live-map__legend-item">
              <span className="live-map__swatch">
                <span className="ft-site" />
              </span>
              <span>Job site + geofence</span>
            </span>
            {live && notStarted > 0 && (
              <span className="muted small live-map__pending">{notStarted} not on the road yet</span>
            )}
          </div>
          <div className="live-map__body">
            {live && workers.every((w) => w.status === 'Off duty') && (
              <div className="muted small live-map__note">
                No workers are assigned today — assign crews on the Jobs page to see them commute.
              </div>
            )}
            {body}
            <div className="muted small live-map__note">
              Stand-in for the mobile app&apos;s live GPS: positions are simulated from the server clock, one
              compressed morning commute every few minutes.
            </div>
          </div>
        </div>
      </div>
    </>
  )
}
