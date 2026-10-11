import { describe, expect, it, vi } from 'vitest'
import { ApiError, api, setAuthToken, setUnauthorizedHandler } from '../api/client'
import { mockApi } from './mockApi'

describe('api client', () => {
  it('sends the JWT, JSON bodies and query parameters', async () => {
    setAuthToken('abc.def.ghi')
    const calls = mockApi({ 'POST /api/jobs': { ok: true } })
    await api('/jobs', { method: 'POST', body: { title: 'x' }, params: { a: 1, skip: null, empty: '' } })
    expect(calls[0].headers.Authorization).toBe('Bearer abc.def.ghi')
    expect(calls[0].headers['Content-Type']).toBe('application/json')
    expect(calls[0].body).toEqual({ title: 'x' })
    setAuthToken(null)
  })

  it('turns server errors into an ApiError with the message, status and field', async () => {
    mockApi({
      'GET /api/jobs': () => ({ status: 400, body: { error: 'Date is bad.', field: 'date' } }),
    })
    await expect(api('/jobs')).rejects.toMatchObject({
      name: 'ApiError',
      message: 'Date is bad.',
      status: 400,
      field: 'date',
    })
  })

  it('reports a rate-limited login (429) with the server message', async () => {
    mockApi({
      'POST /api/auth/login': () => ({
        status: 429,
        body: { error: 'Too many failed sign-in attempts. Try again in 120 seconds.', field: null },
      }),
    })
    const err = await api('/auth/login', { method: 'POST', body: {} }).catch((e) => e)
    expect(err).toBeInstanceOf(ApiError)
    expect(err.status).toBe(429)
    expect(err.message).toMatch(/Too many failed/)
  })

  it('explains an unreachable server in plain words', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('Failed to fetch')))
    await expect(api('/jobs')).rejects.toThrow(/Cannot reach the FieldTrack server/)
  })

  it('calls the unauthorized handler on a 401 while signed in', async () => {
    const onUnauthorized = vi.fn()
    setAuthToken('token')
    setUnauthorizedHandler(onUnauthorized)
    mockApi({ 'GET /api/jobs': () => ({ status: 401, body: { error: 'expired', field: null } }) })
    await expect(api('/jobs')).rejects.toThrow('expired')
    expect(onUnauthorized).toHaveBeenCalledOnce()
    setAuthToken(null)
    setUnauthorizedHandler(null)
  })
})
