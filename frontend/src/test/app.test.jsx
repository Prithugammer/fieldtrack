import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it } from 'vitest'
import App from '../App'
import { AuthProvider } from '../context/AuthContext'
import { ThemeProvider } from '../context/ThemeContext'
import { DASHBOARD, USERS, mockApi } from './mockApi'

function renderApp(path = '/') {
  return render(
    <ThemeProvider>
      <MemoryRouter initialEntries={[path]}>
        <AuthProvider>
          <App />
        </AuthProvider>
      </MemoryRouter>
    </ThemeProvider>,
  )
}

async function signIn(user, email = 'admin@fieldtrack.com', password = 'Admin123!') {
  await user.type(await screen.findByLabelText('Email'), email)
  await user.type(screen.getByLabelText('Password'), password)
  await user.click(screen.getByRole('button', { name: 'Sign in' }))
}

describe('application entry point and authentication', () => {
  it('sends a signed-out visitor to the sign-in page, whatever URL they asked for', async () => {
    const calls = mockApi({})
    renderApp('/reports')
    expect(await screen.findByRole('heading', { name: 'Sign in' })).toBeInTheDocument()
    expect(calls).toHaveLength(0) // no data is requested without a session
  })

  it('signs in and shows the dashboard with the server data', async () => {
    const calls = mockApi({
      'POST /api/auth/login': { token: 'tok-1', user: USERS.admin },
      'GET /api/dashboard': DASHBOARD,
    })
    const user = userEvent.setup()
    renderApp()
    await signIn(user)

    expect(await screen.findByText('Active jobs')).toBeInTheDocument()
    expect(screen.getByText('12.5')).toBeInTheDocument()
    expect(screen.getByText('Level 4 framing')).toBeInTheDocument()
    const login = calls.find((c) => c.path === '/api/auth/login')
    expect(login.body).toEqual({ email: 'admin@fieldtrack.com', password: 'Admin123!' })
    const dash = calls.find((c) => c.path === '/api/dashboard')
    expect(dash.headers.Authorization).toBe('Bearer tok-1')
    expect(localStorage.getItem('fieldtrack_token')).toBe('tok-1')
  })

  it('shows a wrong-password error under the field and stays on the sign-in page', async () => {
    mockApi({
      'POST /api/auth/login': () => ({
        status: 401,
        body: { error: 'Invalid email or password.', field: 'password' },
      }),
    })
    const user = userEvent.setup()
    renderApp()
    await signIn(user, 'admin@fieldtrack.com', 'wrong')
    expect(await screen.findByText('Invalid email or password.')).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Sign in' })).toBeInTheDocument()
    expect(localStorage.getItem('fieldtrack_token')).toBeNull()
  })

  it('shows the throttling message when the server answers 429', async () => {
    mockApi({
      'POST /api/auth/login': () => ({
        status: 429,
        body: { error: 'Too many failed sign-in attempts. Try again in 300 seconds.', field: null },
      }),
    })
    const user = userEvent.setup()
    renderApp()
    await signIn(user)
    expect(await screen.findByText(/Too many failed sign-in attempts/)).toBeInTheDocument()
  })

  it('asks for both fields before calling the server', async () => {
    const calls = mockApi({})
    const user = userEvent.setup()
    renderApp()
    await user.click(await screen.findByRole('button', { name: 'Sign in' }))
    expect(await screen.findByText('Email is required.')).toBeInTheDocument()
    expect(screen.getByText('Password is required.')).toBeInTheDocument()
    expect(calls).toHaveLength(0)
  })

  it('demo-account buttons only fill the form', async () => {
    const calls = mockApi({})
    const user = userEvent.setup()
    renderApp()
    await user.click(await screen.findByRole('button', { name: /Supervisor/ }))
    expect(screen.getByLabelText('Email')).toHaveValue('supervisor@fieldtrack.com')
    expect(calls).toHaveLength(0)
  })

  it('restores a stored session and signs out when the token is rejected', async () => {
    localStorage.setItem('fieldtrack_token', 'old-token')
    mockApi({
      'GET /api/auth/me': () => ({ status: 401, body: { error: 'expired', field: null } }),
    })
    renderApp()
    expect(await screen.findByRole('heading', { name: 'Sign in' })).toBeInTheDocument()
    await waitFor(() => expect(localStorage.getItem('fieldtrack_token')).toBeNull())
  })

  it('restores a valid stored session straight to the dashboard', async () => {
    localStorage.setItem('fieldtrack_token', 'good-token')
    mockApi({ 'GET /api/auth/me': { user: USERS.dispatcher }, 'GET /api/dashboard': DASHBOARD })
    renderApp()
    expect(await screen.findByText('Active jobs')).toBeInTheDocument()
    expect(screen.getByText(/Rajesh Shrestha/)).toBeInTheDocument()
  })
})

describe('dashboard error handling', () => {
  it('shows the server message and a retry button when the data cannot load', async () => {
    localStorage.setItem('fieldtrack_token', 'good-token')
    let attempts = 0
    mockApi({
      'GET /api/auth/me': { user: USERS.admin },
      'GET /api/dashboard': () => {
        attempts += 1
        return attempts === 1
          ? { status: 500, body: { error: 'Something went wrong on the server.', field: null } }
          : { status: 200, body: DASHBOARD }
      },
    })
    const user = userEvent.setup()
    renderApp()
    expect(await screen.findByText('Something went wrong on the server.')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Try again' }))
    expect(await screen.findByText('Active jobs')).toBeInTheDocument()
  })
})
