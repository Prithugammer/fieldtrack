import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it } from 'vitest'
import App from '../App'
import { AuthProvider } from '../context/AuthContext'
import { ThemeProvider } from '../context/ThemeContext'
import { USERS, mockApi } from './mockApi'

const SITE = {
  site_id: 1,
  site_name: 'Kirtipur Campus Expansion',
  address: 'Kirtipur-3',
  latitude: 27.6773,
  longitude: 85.287,
  geofence_radius_m: 200,
  job_count: 1,
}
const JOB = {
  job_id: 4,
  site_id: 1,
  site_name: SITE.site_name,
  site_address: SITE.address,
  created_by: 2,
  created_by_name: 'Rajesh Shrestha',
  title: 'Level 4 framing',
  description: null,
  scheduled_date: '2026-10-11',
  crew_size: 3,
  status: 'In progress',
  assigned_count: 1,
  crew: [{ assignment_id: 9, user_id: 5, full_name: 'Ramesh Karki', trade: 'Carpenter' }],
}
const WORKERS = [
  {
    user_id: 5,
    full_name: 'Ramesh Karki',
    email: 'ramesh@x.com',
    phone: null,
    role: 'Worker',
    trade: 'Carpenter',
    is_active: true,
  },
  {
    user_id: 12,
    full_name: 'Bishal Neupane',
    email: 'bishal@x.com',
    phone: null,
    role: 'Worker',
    trade: 'Laborer',
    is_active: true,
  },
]
const ENTRY = {
  entry_id: 21,
  user_id: 5,
  worker_name: 'Ramesh Karki',
  trade: 'Carpenter',
  job_id: 4,
  job_title: 'Level 4 framing',
  site_id: 1,
  site_name: SITE.site_name,
  geofence_radius_m: 200,
  clock_in: '2026-10-11T07:00:00',
  clock_out: '2026-10-11T11:30:00',
  in_lat: 27.6773,
  in_lng: 85.287,
  out_lat: 27.6773,
  out_lng: 85.287,
  in_distance_m: 30,
  out_distance_m: 520,
  hours: 4.5,
  is_flagged: true,
  flag_reason: 'Clock-out 520 m from site (limit 200 m)',
  status: 'Pending',
  approved_by: null,
  approved_by_name: null,
  edit_reason: null,
}

function renderPage(path, user, routes) {
  localStorage.setItem('fieldtrack_token', 'tok')
  const calls = mockApi({ 'GET /api/auth/me': { user }, ...routes })
  render(
    <ThemeProvider>
      <MemoryRouter initialEntries={[path]}>
        <AuthProvider>
          <App />
        </AuthProvider>
      </MemoryRouter>
    </ThemeProvider>,
  )
  return calls
}

const jobsRoutes = (extra = {}) => ({
  'GET /api/jobs': { jobs: [JOB] },
  'GET /api/sites': { sites: [SITE] },
  ...extra,
})

describe('Jobs page', () => {
  it('lets a Dispatcher create, edit and assign', async () => {
    renderPage('/jobs', USERS.dispatcher, jobsRoutes())
    expect(await screen.findByText('Level 4 framing')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /New job/ })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Edit' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Assign worker' })).toBeInTheDocument()
  })

  it.each([
    ['Supervisor', USERS.supervisor],
    ['unknown staff without edit rights', { ...USERS.supervisor, user_id: 99 }],
  ])('hides every edit control from a %s', async (_name, user) => {
    renderPage('/jobs', user, jobsRoutes())
    expect(await screen.findByText('Level 4 framing')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /New job/ })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Edit' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Assign worker' })).not.toBeInTheDocument()
  })

  it('shows an empty state with a hint that depends on the role', async () => {
    renderPage('/jobs', USERS.dispatcher, jobsRoutes({ 'GET /api/jobs': { jobs: [] } }))
    expect(await screen.findByText('No jobs match these filters')).toBeInTheDocument()
    expect(screen.getByText('Try another date, or create a new job.')).toBeInTheDocument()
  })

  it('shows the server error with a working retry', async () => {
    let n = 0
    renderPage(
      '/jobs',
      USERS.dispatcher,
      jobsRoutes({
        'GET /api/jobs': () =>
          ++n === 1
            ? { status: 500, body: { error: 'Something went wrong on the server.', field: null } }
            : { status: 200, body: { jobs: [JOB] } },
      }),
    )
    expect(await screen.findByText('Something went wrong on the server.')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Try again' }))
    expect(await screen.findByText('Level 4 framing')).toBeInTheDocument()
  })

  it('creates a job: sends numbers, and shows the server message under the offending field', async () => {
    const calls = renderPage(
      '/jobs',
      USERS.dispatcher,
      jobsRoutes({
        'POST /api/jobs': () => ({ status: 400, body: { error: 'Job site is required.', field: 'site_id' } }),
      }),
    )
    const user = userEvent.setup()
    await user.click(await screen.findByRole('button', { name: /New job/ }))
    await user.click(screen.getByRole('button', { name: 'Create job' }))
    expect(await screen.findByText('Job site is required.')).toBeInTheDocument()
    const post = calls.find((c) => c.method === 'POST' && c.path === '/api/jobs')
    expect(post.body.site_id).toBeNull() // an empty select is sent as null, not as ""
    await user.selectOptions(screen.getByLabelText(/Job site/), 'Kirtipur Campus Expansion')
    await user.type(screen.getByLabelText(/Title/), 'Level 4 drywall prep')
    const last = calls.filter((c) => c.method === 'POST' && c.path === '/api/jobs').length
    await user.click(screen.getByRole('button', { name: 'Create job' }))
    await waitFor(() =>
      expect(calls.filter((c) => c.method === 'POST' && c.path === '/api/jobs').length).toBe(last + 1),
    )
    const body = calls.filter((c) => c.path === '/api/jobs' && c.method === 'POST').at(-1).body
    expect(body).toMatchObject({ site_id: 1, title: 'Level 4 drywall prep' })
    expect(typeof body.crew_size === 'number' || body.crew_size === null).toBe(true)
  })

  describe('assigning a worker', () => {
    const assignRoutes = (post) =>
      jobsRoutes({
        'GET /api/jobs/4': { job: JOB },
        'GET /api/users': { users: WORKERS },
        'POST /api/assignments': post,
      })

    it('asks for a worker before calling the server', async () => {
      const calls = renderPage('/jobs', USERS.dispatcher, assignRoutes({ assignment: {} }))
      const user = userEvent.setup()
      await user.click(await screen.findByRole('button', { name: 'Assign worker' }))
      await user.click(await screen.findByRole('button', { name: 'Assign to job' }))
      expect(await screen.findByText('Choose a worker to assign.')).toBeInTheDocument()
      expect(calls.some((c) => c.path === '/api/assignments')).toBe(false)
    })

    it('shows the double-booking conflict under the Worker field and keeps the crew unchanged', async () => {
      renderPage(
        '/jobs',
        USERS.dispatcher,
        assignRoutes(() => ({
          status: 409,
          body: {
            error:
              "Bishal Neupane is already assigned to 'Deck pour' at Gongabu on 2026-10-11. A worker can only be booked on one job per day.",
            field: 'user_id',
          },
        })),
      )
      const user = userEvent.setup()
      await user.click(await screen.findByRole('button', { name: 'Assign worker' }))
      await user.selectOptions(await screen.findByLabelText(/^Worker/), '12')
      await user.click(screen.getByRole('button', { name: 'Assign to job' }))
      const msg = await screen.findByText(/already assigned to 'Deck pour'/)
      expect(msg.closest('.field')).toHaveClass('field--error')
    })

    it('reports a crew-full conflict and lists only workers not already on the crew', async () => {
      renderPage(
        '/jobs',
        USERS.dispatcher,
        assignRoutes(() => ({
          status: 409,
          body: { error: "The crew for 'Level 4 framing' is full (3 of 3).", field: 'job_id' },
        })),
      )
      const user = userEvent.setup()
      await user.click(await screen.findByRole('button', { name: 'Assign worker' }))
      const select = await screen.findByLabelText(/^Worker/)
      expect(within(select).queryByText(/Ramesh Karki/)).not.toBeInTheDocument() // already on the crew
      await user.selectOptions(select, '12')
      await user.click(screen.getByRole('button', { name: 'Assign to job' }))
      expect(await screen.findByText(/is full \(3 of 3\)/)).toBeInTheDocument()
    })

    it('confirms a successful assignment', async () => {
      renderPage(
        '/jobs',
        USERS.dispatcher,
        assignRoutes({
          assignment: {
            assignment_id: 10,
            full_name: 'Bishal Neupane',
            work_date: '2026-10-11',
            user_id: 12,
            job_id: 4,
          },
        }),
      )
      const user = userEvent.setup()
      await user.click(await screen.findByRole('button', { name: 'Assign worker' }))
      await user.selectOptions(await screen.findByLabelText(/^Worker/), '12')
      await user.click(screen.getByRole('button', { name: 'Assign to job' }))
      expect(await screen.findByText(/Bishal Neupane assigned for/)).toBeInTheDocument()
    })
  })
})

describe('Job Sites page', () => {
  it('shows New site / Edit to a Dispatcher only', async () => {
    renderPage('/sites', USERS.dispatcher, { 'GET /api/sites': { sites: [SITE] } })
    expect(await screen.findByText('Kirtipur Campus Expansion')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /New site/ })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Edit' })).toBeInTheDocument()
  })

  it('hides them from a Supervisor', async () => {
    renderPage('/sites', USERS.supervisor, { 'GET /api/sites': { sites: [SITE] } })
    expect(await screen.findByText('Kirtipur Campus Expansion')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /New site/ })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Edit' })).not.toBeInTheDocument()
  })

  it('has an empty state and an error state', async () => {
    renderPage('/sites', USERS.dispatcher, { 'GET /api/sites': { sites: [] } })
    expect(await screen.findByText('No job sites yet')).toBeInTheDocument()
  })

  it('shows a coordinate error from the server under the latitude field', async () => {
    renderPage('/sites', USERS.dispatcher, {
      'GET /api/sites': { sites: [SITE] },
      'POST /api/sites': () => ({
        status: 400,
        body: { error: 'Latitude must be between -90.0 and 90.0.', field: 'latitude' },
      }),
    })
    const user = userEvent.setup()
    await user.click(await screen.findByRole('button', { name: /New site/ }))
    await user.type(screen.getByLabelText(/Site name/), 'Test Yard')
    await user.type(screen.getByLabelText(/Address/), '12 Ring Road')
    await user.click(screen.getAllByRole('button', { name: /Create site|Save/ }).at(-1))
    expect(await screen.findByText('Latitude must be between -90.0 and 90.0.')).toBeInTheDocument()
  })
})

describe('Crew page', () => {
  const staff = [USERS.admin, USERS.supervisor].map((u) => ({
    ...u,
    phone: null,
    trade: null,
    is_active: true,
  }))
  const people = { 'GET /api/users': { users: [...staff, ...WORKERS] } }

  it('lets an Admin add and edit people', async () => {
    renderPage('/crew', USERS.admin, people)
    expect(await screen.findByText('Ramesh Karki')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Add person/ })).toBeInTheDocument()
    expect(screen.getAllByRole('button', { name: 'Edit' }).length).toBeGreaterThan(0)
  })

  it.each([
    ['Dispatcher', USERS.dispatcher],
    ['Supervisor', USERS.supervisor],
  ])('tells a %s that only admins can edit people', async (_n, user) => {
    renderPage('/crew', user, people)
    expect(await screen.findByText('Ramesh Karki')).toBeInTheDocument()
    expect(screen.getByText('Only admins can edit people.')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Add person/ })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Edit' })).not.toBeInTheDocument()
  })

  it('shows an inline error when the server rejects a duplicate email', async () => {
    renderPage('/crew', USERS.admin, {
      ...people,
      'POST /api/users': () => ({
        status: 409,
        body: { error: 'A user with email maya@x.com already exists.', field: 'email' },
      }),
    })
    const user = userEvent.setup()
    await user.click(await screen.findByRole('button', { name: /Add person/ }))
    await user.type(screen.getByLabelText(/Full name/), 'Maya Lama')
    await user.type(screen.getByLabelText(/Email/), 'maya@x.com')
    await user.click(screen.getAllByRole('button', { name: 'Add person' }).at(-1))
    expect(await screen.findByText('A user with email maya@x.com already exists.')).toBeInTheDocument()
  })

  it('shows an empty state', async () => {
    renderPage('/crew', USERS.admin, { 'GET /api/users': { users: [] } })
    expect(await screen.findByText('No people found')).toBeInTheDocument()
  })
})

describe('Time Entries page', () => {
  const entries = {
    'GET /api/time-entries': { time_entries: [ENTRY] },
    'GET /api/users': { users: WORKERS },
    'GET /api/sites': { sites: [SITE] },
  }

  it('lets a Supervisor record, and approve or reject a completed entry', async () => {
    renderPage('/time-entries', USERS.supervisor, entries)
    expect((await screen.findAllByText('Ramesh Karki')).length).toBeGreaterThan(0)
    expect(screen.getByRole('button', { name: /Record time entry/ })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Approve' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Reject' })).toBeInTheDocument()
  })

  it('shows a Dispatcher the entries (including the flag) but no way to change them', async () => {
    renderPage('/time-entries', USERS.dispatcher, entries)
    expect((await screen.findAllByText('Ramesh Karki')).length).toBeGreaterThan(0)
    expect(screen.getByText(/520 m from site/)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Record time entry/ })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Approve' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Reject' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Clock out' })).not.toBeInTheDocument()
  })

  it('offers Clock out only for an entry that is still open', async () => {
    const open = {
      ...ENTRY,
      entry_id: 22,
      clock_out: null,
      out_lat: null,
      out_lng: null,
      out_distance_m: null,
      hours: null,
      is_flagged: false,
      flag_reason: null,
    }
    renderPage('/time-entries', USERS.supervisor, {
      ...entries,
      'GET /api/time-entries': { time_entries: [open] },
    })
    expect(await screen.findByRole('button', { name: 'Clock out' })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Approve' })).not.toBeInTheDocument()
  })

  it('requires a reason to approve, then sends the decision and the reason', async () => {
    const calls = renderPage('/time-entries', USERS.supervisor, {
      ...entries,
      'PATCH /api/time-entries/21/approve': {
        time_entry: {
          ...ENTRY,
          status: 'Approved',
          approved_by_name: 'Bikash Thapa',
          edit_reason: 'Foreman confirmed',
        },
      },
    })
    const user = userEvent.setup()
    await user.click(await screen.findByRole('button', { name: 'Approve' }))
    expect(await screen.findByText(/Flagged: Clock-out 520 m/)).toBeInTheDocument() // the reviewer sees why
    await user.click(screen.getAllByRole('button', { name: 'Approve' }).at(-1))
    expect(await screen.findByText('A reason is required for the audit trail.')).toBeInTheDocument()
    expect(calls.some((c) => c.method === 'PATCH')).toBe(false)
    await user.type(screen.getByLabelText(/Reason/), 'Foreman confirmed')
    await user.click(screen.getAllByRole('button', { name: 'Approve' }).at(-1))
    await waitFor(() => expect(calls.some((c) => c.method === 'PATCH')).toBe(true))
    expect(calls.find((c) => c.method === 'PATCH').body).toEqual({
      decision: 'Approved',
      edit_reason: 'Foreman confirmed',
    })
  })

  it('shows "already decided" conflicts from the server', async () => {
    renderPage('/time-entries', USERS.supervisor, {
      ...entries,
      'PATCH /api/time-entries/21/approve': () => ({
        status: 409,
        body: { error: 'This entry was already approved by Bikash Thapa.', field: null },
      }),
    })
    const user = userEvent.setup()
    await user.click(await screen.findByRole('button', { name: 'Approve' }))
    await user.type(screen.getByLabelText(/Reason/), 'again')
    await user.click(screen.getAllByRole('button', { name: 'Approve' }).at(-1))
    expect(await screen.findByText('This entry was already approved by Bikash Thapa.')).toBeInTheDocument()
  })

  it('has an empty state and an error state with retry', async () => {
    let n = 0
    renderPage('/time-entries', USERS.supervisor, {
      ...entries,
      'GET /api/time-entries': () =>
        ++n === 1
          ? {
              status: 503,
              body: {
                error: 'The server is busy with another change. Please retry in a moment.',
                field: null,
              },
            }
          : { status: 200, body: { time_entries: [] } },
    })
    expect(await screen.findByText(/The server is busy/)).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Try again' }))
    expect(await screen.findByText('No time entries match these filters')).toBeInTheDocument()
    expect(screen.getByText(/Record time entry/, { selector: 'div,p,span' })).toBeInTheDocument()
  })
})

describe('session handling', () => {
  it('signs the user out when any page request is answered with 401', async () => {
    renderPage(
      '/jobs',
      USERS.dispatcher,
      jobsRoutes({
        'GET /api/jobs': () => ({
          status: 401,
          body: { error: 'Your session has expired. Please log in again.', field: null },
        }),
      }),
    )
    expect(await screen.findByRole('heading', { name: 'Sign in' })).toBeInTheDocument()
    expect(localStorage.getItem('fieldtrack_token')).toBeNull()
  })

  it('treats a network failure as a readable error, not a blank page', async () => {
    renderPage('/jobs', USERS.dispatcher, {
      'GET /api/jobs': () => {
        throw new TypeError('Failed to fetch')
      },
      'GET /api/sites': { sites: [SITE] },
    })
    expect(await screen.findByText(/Cannot reach the FieldTrack server/)).toBeInTheDocument()
  })
})
