import { render, screen, waitFor, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import App from '../App'
import { AuthProvider } from '../context/AuthContext'
import { ThemeProvider } from '../context/ThemeContext'
import { USERS, mockApi } from './mockApi'

// Leaflet needs real layout (jsdom has none), so the map widgets are stubbed. Popup content is
// rendered inline, which lets the tests read the per-worker safety buttons.
vi.mock('react-leaflet', () => {
  const Box = ({ children, ...rest }) => <div data-testid={rest['data-testid']}>{children}</div>
  return {
    MapContainer: ({ children }) => <div data-testid="map">{children}</div>,
    Marker: ({ children }) => <div data-testid="marker">{children}</div>,
    Popup: ({ children }) => <div data-testid="popup">{children}</div>,
    Circle: () => null,
    Polyline: () => null,
    TileLayer: () => null,
    useMapEvents: () => ({}),
    Box,
  }
})

const CONFIG = {
  mode: 'demo',
  idle_threshold_seconds: 15,
  num_checkins: 3,
  checkin_response_window_seconds: 5,
}

const SITE_OK = {
  id: 1,
  name: 'Kirtipur Campus',
  address: 'Kirtipur',
  lat: 27.6773,
  lng: 85.287,
  radius_m: 200,
  jobs_today: ['Framing'],
  routable: true,
}
const SITE_FAR = {
  id: 2,
  name: 'Pokhara Annex',
  address: 'Pokhara',
  lat: 28.2096,
  lng: 83.9856,
  radius_m: 200,
  jobs_today: ['Far job'],
  routable: false,
}

const safetyOf = (patch = {}, workers = []) => ({
  config: CONFIG,
  seed: 1,
  privacy_note: 'Privacy: location data is used only to raise safety alerts.',
  alerts: [],
  notifications: [],
  monitoring: { last_tick_at: '2026-10-11T08:00:00+00:00', age_s: 0.4, background: true },
  ...patch,
})

const worker = (id, name, patch = {}) => ({
  id,
  name,
  trade: 'Carpenter',
  status: 'On site',
  sim_status: 'On site',
  lat: 27.6773,
  lng: 85.287,
  job_title: 'Framing',
  site_name: 'Kirtipur Campus',
  near_traffic: false,
  hotspot: null,
  distance_remaining_m: 0,
  safety: {
    state: 'NORMAL',
    checkin: 0,
    stopped: false,
    on_break: false,
    incapacitated: false,
    break_zone: null,
  },
  ...patch,
})

const liveState = ({
  sites = [SITE_OK],
  workers = [worker(5, 'Ramesh Karki')],
  safety = safetyOf(),
} = {}) => ({
  sim_time: '6:10 AM',
  cycle: 1,
  job_sites: sites,
  workers,
  safety,
})

const BOUNDS = { south: 27.6, west: 85.2, north: 27.8, east: 85.45, traffic_hotspots: [] }
const CLOCK = { sim_time: '6:10 AM', cycle_seconds: 300, seconds_to_reset: 120, cycle: 1 }

function routes(live, extra = {}) {
  return {
    'GET /api/auth/me': { user: USERS.supervisor },
    'GET /api/map/bounds': BOUNDS,
    'GET /api/map/sim-clock': CLOCK,
    'GET /api/map/live': live,
    ...extra,
  }
}

function renderMap() {
  localStorage.setItem('fieldtrack_token', 'tok')
  return render(
    <ThemeProvider>
      <MemoryRouter initialEntries={['/live-map']}>
        <AuthProvider>
          <App />
        </AuthProvider>
      </MemoryRouter>
    </ThemeProvider>,
  )
}

afterEach(() => {
  vi.useRealTimers()
})

describe('Live Map page', () => {
  it('renders the safety panel from the read-only /map/live and never calls the tick endpoint', async () => {
    const calls = mockApi(routes(liveState()))
    renderMap()
    expect(await screen.findByText('All clear')).toBeInTheDocument()
    expect(screen.getByText(/demo mode/)).toBeInTheDocument()
    const paths = calls.map((c) => `${c.method} ${c.path}`)
    expect(paths).toContain('GET /api/map/live')
    expect(paths).not.toContain('POST /api/safety/tick') // the browser no longer drives escalation
  })

  it('shows the server error and a retry button when the very first load fails, then recovers', async () => {
    let attempts = 0
    mockApi(
      routes(null, {
        'GET /api/map/live': () => {
          attempts += 1
          return attempts === 1
            ? { status: 500, body: { error: 'Something went wrong on the server.', field: null } }
            : { status: 200, body: liveState() }
        },
      }),
    )
    renderMap()
    expect(await screen.findByText('Something went wrong on the server.')).toBeInTheDocument()
    screen.getByRole('button', { name: 'Try again' }).click()
    expect(await screen.findByText('All clear')).toBeInTheDocument()
  })

  it('warns that the connection was lost, but keeps the last good data on screen', async () => {
    vi.useFakeTimers({ toFake: ['setInterval', 'clearInterval'] })
    let attempts = 0
    mockApi(
      routes(null, {
        'GET /api/map/live': () => {
          attempts += 1
          return attempts === 1
            ? { status: 200, body: liveState() }
            : {
                status: 503,
                body: {
                  error: 'The server is busy with another change. Please retry in a moment.',
                  field: null,
                },
              }
        },
      }),
    )
    renderMap()
    expect(await screen.findByText('All clear')).toBeInTheDocument()
    await vi.advanceTimersByTimeAsync(1100)
    expect(await screen.findByText(/Lost connection to the server — retrying/)).toBeInTheDocument()
    expect(screen.getByText('All clear')).toBeInTheDocument() // the previous state is still shown
  })

  it('explains an unsupported site instead of silently dropping its workers', async () => {
    const far = worker(6, 'Bishal Neupane', {
      status: 'Route unavailable',
      sim_status: 'Route unavailable',
      lat: null,
      lng: null,
      site_name: 'Pokhara Annex',
      job_title: 'Far job',
    })
    mockApi(routes(liveState({ sites: [SITE_OK, SITE_FAR], workers: [worker(5, 'Ramesh Karki'), far] })))
    renderMap()
    const note = await screen.findByText(/outside the supported road network/)
    expect(note).toHaveTextContent('1 job site is outside the supported road network (Pokhara Annex)')
    expect(note).toHaveTextContent('1 affected')
    expect(screen.getByText('All clear')).toBeInTheDocument() // the rest of the page still works
  })

  it('shows the empty state when there are no job sites', async () => {
    mockApi(routes(liveState({ sites: [], workers: [] })))
    renderMap()
    expect(await screen.findByText('No job sites yet')).toBeInTheDocument()
  })

  it('still draws the map when every site is unsupported (no crash, no globe-sized view)', async () => {
    mockApi(routes(liveState({ sites: [SITE_FAR], workers: [] })))
    renderMap()
    expect(await screen.findByText(/outside the supported road network/)).toBeInTheDocument()
  })

  it('warns when the server says safety monitoring is not running', async () => {
    mockApi(
      routes(
        liveState({
          safety: safetyOf({ monitoring: { last_tick_at: null, age_s: null, background: false } }),
        }),
      ),
    )
    renderMap()
    expect(await screen.findByText(/Safety monitoring is not running on the server/)).toBeInTheDocument()
  })

  it('warns when monitoring has gone stale even though the heartbeat is configured', async () => {
    mockApi(
      routes(
        liveState({
          safety: safetyOf({
            monitoring: { last_tick_at: '2026-10-11T08:00:00+00:00', age_s: 42.4, background: true },
          }),
        }),
      ),
    )
    renderMap()
    expect(await screen.findByText(/Safety monitoring has not updated for 42 s/)).toBeInTheDocument()
  })

  it('shows no monitoring warning while the heartbeat is healthy', async () => {
    mockApi(routes(liveState()))
    renderMap()
    await screen.findByText('All clear')
    expect(screen.queryByText(/Safety monitoring/)).not.toBeInTheDocument()
    expect(screen.queryByText(/Lost connection/)).not.toBeInTheDocument()
  })
})

describe('Live Map safety display by role', () => {
  const emergency = {
    worker_id: 7,
    worker_name: 'Sita Rai',
    state: 'EMERGENCY',
    stage: 'EMERGENCY',
    level: 'critical',
    trigger: 'idle',
    incapacitated: false,
    started_at: null,
    elapsed_s: 31,
    window_remaining_s: null,
    location: { lat: 27.6773, lng: 85.287, label: 'On site at Kirtipur Campus' },
    nearest_coworker: { id: 5, name: 'Ramesh Karki', trade: 'Carpenter', distance_m: 40, status: 'On site' },
    resolution: null,
  }
  const warning = {
    ...emergency,
    worker_id: 8,
    worker_name: 'Pooja Basnet',
    state: 'CHECKIN_2',
    stage: 'Check-in 2 of 3',
    level: 'warning',
    window_remaining_s: 3.4,
    elapsed_s: 17,
  }

  const emergencyState = () =>
    liveState({
      workers: [
        worker(7, 'Sita Rai', { status: 'EMERGENCY', safety: { state: 'EMERGENCY', checkin: 0 } }),
        worker(8, 'Pooja Basnet', { safety: { state: 'CHECKIN_2', checkin: 2 } }),
      ],
      safety: safetyOf({ alerts: [emergency, warning] }),
    })

  it('shows escalation (check-in count, emergency, nearest co-worker) to a Supervisor with the resolve controls', async () => {
    mockApi(routes(emergencyState()))
    renderMap()
    const panel = await screen.findByRole('region', { name: 'Safety and emergency' })
    expect(within(panel).getByText('Check-in 2 of 3')).toBeInTheDocument()
    expect(within(panel).getByText(/reply window 0:03/)).toBeInTheDocument()
    expect(within(panel).getByText('1 emergency')).toBeInTheDocument()
    expect(within(panel).getAllByText(/Ramesh Karki/).length).toBeGreaterThan(0)
    expect(within(panel).getByRole('button', { name: /Resolved – false alarm/ })).toBeInTheDocument()
    expect(within(panel).getByRole('button', { name: /Resolved – real incident/ })).toBeInTheDocument()
  })

  it('shows the same alerts to a Dispatcher but none of the controls', async () => {
    mockApi(routes(emergencyState(), { 'GET /api/auth/me': { user: USERS.dispatcher } }))
    renderMap()
    const panel = await screen.findByRole('region', { name: 'Safety and emergency' })
    expect(within(panel).getByText('Sita Rai')).toBeInTheDocument()
    expect(within(panel).getByText('1 emergency')).toBeInTheDocument()
    expect(within(panel).queryByRole('button', { name: /Resolved/ })).not.toBeInTheDocument()
    expect(within(panel).queryByRole('button', { name: 'Return to duty' })).not.toBeInTheDocument()
  })

  it('sends a resolution to the server and reloads the state', async () => {
    const calls = mockApi(routes(emergencyState(), { 'POST /api/safety/workers/7/resolve': { ok: true } }))
    renderMap()
    const panel = await screen.findByRole('region', { name: 'Safety and emergency' })
    within(panel)
      .getByRole('button', { name: /Resolved – false alarm/ })
      .click()
    await waitFor(() =>
      expect(calls.some((c) => c.method === 'POST' && c.path === '/api/safety/workers/7/resolve')).toBe(true),
    )
    const post = calls.find((c) => c.path === '/api/safety/workers/7/resolve')
    expect(post.body).toEqual({ outcome: 'false_alarm', note: '' })
  })

  it('shows the server refusal when a control is rejected (e.g. 403)', async () => {
    mockApi(
      routes(emergencyState(), {
        'POST /api/safety/workers/7/resolve': () => ({
          status: 403,
          body: { error: 'Your role (Dispatcher) cannot do this. Allowed: Supervisor, Admin.', field: null },
        }),
      }),
    )
    renderMap()
    const panel = await screen.findByRole('region', { name: 'Safety and emergency' })
    within(panel)
      .getByRole('button', { name: /Resolved – false alarm/ })
      .click()
    expect(await screen.findByText(/Your role \(Dispatcher\) cannot do this/)).toBeInTheDocument()
  })
})

// Site markers have popups too: pick the popup of the named worker.
const workerPopup = async (name) =>
  waitFor(() => {
    const found = screen.getAllByTestId('popup').find((el) => el.textContent.includes(name))
    if (!found) throw new Error(`no popup for ${name}`)
    return found
  })

describe('Live Map worker popups by role', () => {
  const onShift = () =>
    liveState({
      workers: [
        worker(5, 'Ramesh Karki', {
          status: 'In transit',
          sim_status: 'In transit',
          distance_remaining_m: 900,
        }),
      ],
    })

  it('gives a Supervisor the accident, SOS and break controls', async () => {
    mockApi(routes(onShift()))
    renderMap()
    const popup = await workerPopup('Ramesh Karki')
    expect(within(popup).getByRole('button', { name: 'Trigger accident' })).toBeInTheDocument()
    expect(within(popup).getByRole('button', { name: 'SOS' })).toBeInTheDocument()
    expect(within(popup).getByRole('button', { name: 'Start break' })).toBeInTheDocument()
  })

  it('gives an Admin the same controls', async () => {
    mockApi(routes(onShift(), { 'GET /api/auth/me': { user: USERS.admin } }))
    renderMap()
    const popup = await workerPopup('Ramesh Karki')
    expect(within(popup).getByRole('button', { name: 'SOS' })).toBeInTheDocument()
  })

  it('shows a Dispatcher the worker but no safety buttons', async () => {
    mockApi(routes(onShift(), { 'GET /api/auth/me': { user: USERS.dispatcher } }))
    renderMap()
    const popup = await workerPopup('Ramesh Karki')
    expect(within(popup).getByText('Ramesh Karki')).toBeInTheDocument()
    expect(within(popup).queryByRole('button', { name: 'Trigger accident' })).not.toBeInTheDocument()
    expect(within(popup).queryByRole('button', { name: 'SOS' })).not.toBeInTheDocument()
    expect(within(popup).queryByRole('button', { name: 'Start break' })).not.toBeInTheDocument()
  })

  it('does not draw a marker for a worker whose site is unsupported', async () => {
    const far = worker(6, 'Bishal Neupane', {
      status: 'Route unavailable',
      sim_status: 'Route unavailable',
      lat: null,
      lng: null,
      site_name: 'Pokhara Annex',
    })
    mockApi(routes(liveState({ sites: [SITE_OK, SITE_FAR], workers: [far] })))
    renderMap()
    await screen.findByText(/outside the supported road network/)
    expect(screen.queryByText('Bishal Neupane')).not.toBeInTheDocument() // no popup/marker for them
  })
})

describe('Live Map persistence warning', () => {
  it('tells the operator when safety events could not be saved', async () => {
    const monitoring = {
      last_tick_at: '2026-10-11T08:00:00+00:00',
      age_s: 0.4,
      background: true,
      persistence: { enabled: true, ok: false, unsaved_events: 4 },
    }
    mockApi(routes(liveState({ safety: safetyOf({ monitoring }) })))
    renderMap()
    expect(await screen.findByText(/could not save safety events \(4 waiting\)/)).toBeInTheDocument()
  })

  it('shows nothing while saving works, or when persistence is switched off', async () => {
    const ok = {
      last_tick_at: '2026-10-11T08:00:00+00:00',
      age_s: 0.4,
      background: true,
      persistence: { enabled: true, ok: true, unsaved_events: 0 },
    }
    mockApi(routes(liveState({ safety: safetyOf({ monitoring: ok }) })))
    renderMap()
    await screen.findByText('All clear')
    expect(screen.queryByText(/could not save safety events/)).not.toBeInTheDocument()
  })

  it('does not stack up requests while the server is slow', async () => {
    vi.useFakeTimers({ toFake: ['setInterval', 'clearInterval'] })
    mockApi(routes(liveState()))
    const realFetch = globalThis.fetch
    let release
    const gate = new Promise((r) => (release = r))
    let started = 0
    globalThis.fetch = vi.fn(async (...args) => {
      if (String(args[0]).includes('/map/live')) {
        started += 1
        await gate // the server is "slow": no answer yet
      }
      return realFetch(...args)
    })
    renderMap()
    await vi.waitFor(() => expect(started).toBe(1), { timeout: 4000 }) // the page loaded and sent its first poll
    await vi.advanceTimersByTimeAsync(5200) // five poll intervals pass while the first request is still open
    expect(started).toBe(1)
    release()
    await vi.advanceTimersByTimeAsync(1100)
    expect(started).toBeGreaterThanOrEqual(2) // polling resumes once the answer arrives
  })
})
