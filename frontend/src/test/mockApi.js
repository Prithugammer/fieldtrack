import { vi } from 'vitest'

/**
 * Replace window.fetch with a fake FieldTrack API. `routes` maps "METHOD /api/path" to either a
 * JSON body (200) or a function (request) => ({ status, body }). Unlisted calls fail the test
 * loudly so nothing silently reaches a real server. Returns the list of calls made.
 */
export function mockApi(routes) {
  const calls = []
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url, init = {}) => {
      const { pathname } = new URL(url)
      const method = init.method || 'GET'
      const call = {
        method,
        path: pathname,
        headers: init.headers || {},
        body: init.body ? JSON.parse(init.body) : undefined,
      }
      calls.push(call)
      const handler = routes[`${method} ${pathname}`]
      if (handler === undefined) throw new Error(`Unmocked API call: ${method} ${pathname}`)
      const { status = 200, body } =
        typeof handler === 'function' ? handler(call) : { status: 200, body: handler }
      return {
        ok: status >= 200 && status < 300,
        status,
        json: async () => body,
        blob: async () => new Blob([JSON.stringify(body)]),
      }
    }),
  )
  return calls
}

export const DASHBOARD = {
  date: '2026-10-01',
  kpis: { active_jobs: 3, workers_clocked_in: 4, hours_today: 12.5, flagged_entries: 2 },
  jobs_today: [
    {
      job_id: 1,
      title: 'Level 4 framing',
      site_name: 'Kirtipur Campus Expansion',
      assigned_count: 2,
      crew_size: 3,
      status: 'In progress',
      crew: [{ full_name: 'Ramesh Karki' }, { full_name: 'Pooja Basnet' }],
    },
  ],
  unassigned_workers: [],
  needs_attention: [],
}

export const USERS = {
  admin: { user_id: 1, full_name: 'Sunita Sharma', email: 'admin@fieldtrack.com', role: 'Admin' },
  dispatcher: {
    user_id: 2,
    full_name: 'Rajesh Shrestha',
    email: 'dispatch@fieldtrack.com',
    role: 'Dispatcher',
  },
  supervisor: {
    user_id: 4,
    full_name: 'Bikash Thapa',
    email: 'supervisor@fieldtrack.com',
    role: 'Supervisor',
  },
}
