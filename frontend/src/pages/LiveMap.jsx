import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import L from 'leaflet'
import { Circle, MapContainer, Marker, Popup, TileLayer, Tooltip, useMapEvents } from 'react-leaflet'
import 'leaflet/dist/leaflet.css'
import '../styles/live-map.css'
import { api } from '../api/client'
import { useApi } from '../api/useApi'
import TopBar from '../components/TopBar'
import { Alert, EmptyState, ErrorState, LoadingState } from '../components/States'

// Positions are SIMULATED on the server (backend/simulation.py) — there is no mobile app
// yet — and refreshed on this interval. Markers glide between polls (see live-map.css).
const POLL_MS = 4000
// How long markers fade when the simulated morning restarts (matches live-map.css).
const FADE_MS = 600
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
      const variant = w.near_traffic ? 'traffic' : WORKER_VARIANTS[w.status]
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
 * Stand-in for the future mobile app's live GPS: polls the simulated positions computed by
 * backend/simulation.py. Simulated (not random) so every demo is repeatable and still shows the
 * real ideas: geofences, traffic delays, and workers arriving on site.
 */
export default function LiveMap() {
  const bounds = useApi('/map/bounds')
  const [live, setLive] = useState(null)
  const [clock, setClock] = useState(null)
  const [error, setError] = useState(null)
  // Markers from the cycle that just ended, fading out while the new cycle fades in.
  const [ghosts, setGhosts] = useState([])
  const [entering, setEntering] = useState(false)
  const prevLive = useRef(null)
  const fadeTimer = useRef(null)
  const mapRef = useRef(null)

  const poll = useCallback(async () => {
    try {
      const [state, sim] = await Promise.all([api('/map/live'), api('/map/sim-clock')])
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
    }
  }, [])

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
    const sites = live.job_sites.length
      ? L.latLngBounds(live.job_sites.map((s) => [s.lat, s.lng])).pad(0.15)
      : valley
    return { start: sites, max: valley.pad(0.25) }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [bounds.data, live === null])

  const workers = live?.workers || []
  const count = (pred) => workers.filter(pred).length
  const legend = [
    { variant: 'onsite', label: 'On site', n: count((w) => w.status === 'On site') },
    { variant: 'transit', label: 'In transit', n: count((w) => w.status === 'In transit' && !w.near_traffic) },
    { variant: 'traffic', label: 'Delayed in traffic', n: count((w) => w.near_traffic) },
    { variant: 'off', label: 'Off duty', n: count((w) => w.status === 'Off duty') },
  ]
  const notStarted = count((w) => w.status === 'Not started')

  let body
  if ((bounds.error || error) && !live) {
    body = <ErrorState message={(bounds.error || error).message} onRetry={() => { bounds.reload(); poll() }} />
  } else if (!live || !view) {
    body = <LoadingState label="Loading map…" />
  } else if (live.job_sites.length === 0) {
    body = <EmptyState title="No job sites yet" message="Add a job site to see it on the map." />
  } else {
    const b = bounds.data
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
          <TileLayer
            url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
            attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
          />
          {b.traffic_hotspots.map((h) => (
            <Circle
              key={h.name}
              center={[h.lat, h.lng]}
              radius={h.radius_m}
              pathOptions={{ color: '#d33a3a', weight: 1, dashArray: '4 4', fillOpacity: 0.06 }}
            >
              <Tooltip>Traffic hotspot: {h.name}</Tooltip>
            </Circle>
          ))}
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
            <Marker key={`site-${s.id}`} position={[s.lat, s.lng]} icon={siteIcon} zIndexOffset={-100}>
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
                      <span className="muted"> · {formatKm(w.distance_remaining_m)} to site</span>
                    )}
                  </div>
                  {w.near_traffic && <div className="map-popup__delay">Delayed near {w.hotspot}</div>}
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
              <span className="chip chip--navy live-map__clock" title={`Simulated ${clock.window_start}–${clock.window_end}, repeating every ${clock.cycle_seconds / 60} real minutes`}>
                Simulated time: {clock.sim_time}
              </span>
              <CycleCountdown resetAt={clock.resetAt} cycleSeconds={clock.cycle_seconds} />
            </span>
          )
        }
      />
      <div className="page">
        {error && live && <Alert tone="warning">Lost connection to the server — retrying. {error.message}</Alert>}
        <div className="card">
          <div className="live-map__legend">
            {legend.map((item) => (
              <span key={item.variant} className="live-map__legend-item">
                <span className={`ft-worker ft-worker--${item.variant}`} /> {item.label}
                {live && <span className="muted"> ({item.n})</span>}
              </span>
            ))}
            <span className="live-map__legend-item">
              <span className="ft-site" /> Job site + geofence
            </span>
            <span className="live-map__legend-item">
              <span className="live-map__hotspot-swatch" /> Traffic hotspot
            </span>
            {live && notStarted > 0 && (
              <span className="muted small">{notStarted} not on the road yet</span>
            )}
          </div>
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
    </>
  )
}
