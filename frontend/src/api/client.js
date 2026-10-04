// One fetch wrapper for the whole app.
// - prefixes every path with the API base + /api
// - attaches the JWT
// - throws an ApiError carrying the server's message and the offending field

const API_ORIGIN = import.meta.env.VITE_API_URL || 'http://127.0.0.1:5000'
const API_BASE = `${API_ORIGIN}/api`

let authToken = null
let onUnauthorized = null

export function setAuthToken(token) {
  authToken = token
}

export function setUnauthorizedHandler(handler) {
  onUnauthorized = handler
}

export class ApiError extends Error {
  constructor(message, { status = 0, field = null } = {}) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.field = field
  }
}

function buildUrl(path, params) {
  const url = new URL(API_BASE + path)
  if (params) {
    Object.entries(params).forEach(([key, value]) => {
      if (value !== undefined && value !== null && value !== '') {
        url.searchParams.set(key, value)
      }
    })
  }
  return url.toString()
}

async function send(path, { method = 'GET', body, params } = {}) {
  const headers = {}
  if (body !== undefined) headers['Content-Type'] = 'application/json'
  if (authToken) headers.Authorization = `Bearer ${authToken}`

  let res
  try {
    res = await fetch(buildUrl(path, params), {
      method,
      headers,
      body: body !== undefined ? JSON.stringify(body) : undefined,
    })
  } catch {
    throw new ApiError(
      'Cannot reach the FieldTrack server. Make sure the backend is running on port 5000.',
    )
  }

  if (res.status === 401 && authToken && onUnauthorized) {
    onUnauthorized()
  }
  return res
}

async function readError(res) {
  let data = null
  try {
    data = await res.json()
  } catch {
    /* non-JSON error body */
  }
  return new ApiError(data?.error || `Request failed (${res.status}).`, {
    status: res.status,
    field: data?.field ?? null,
  })
}

/** JSON request: `await api('/jobs', { params: { date } })`, `api('/jobs', { method: 'POST', body })` */
export async function api(path, options = {}) {
  const res = await send(path, options)
  if (!res.ok) throw await readError(res)
  return res.status === 204 ? null : res.json()
}

/** Download a file endpoint (e.g. the CSV export) with the JWT attached. */
export async function apiDownload(path, params, filename) {
  const res = await send(path, { params })
  if (!res.ok) throw await readError(res)
  const blob = await res.blob()
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = filename
  document.body.appendChild(link)
  link.click()
  link.remove()
  URL.revokeObjectURL(url)
}
