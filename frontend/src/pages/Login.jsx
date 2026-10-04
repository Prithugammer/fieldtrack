import { useState } from 'react'
import { Navigate, useLocation, useNavigate } from 'react-router-dom'
import FormField from '../components/FormField'
import { IconCheck } from '../components/Icons'
import { BrandMark } from '../components/Sidebar'
import { Alert } from '../components/States'
import { useAuth } from '../context/AuthContext'
import { errorState } from '../utils/format'

const DEMO_ACCOUNTS = [
  { role: 'Admin', email: 'admin@fieldtrack.com', password: 'Admin123!' },
  { role: 'Dispatcher', email: 'dispatch@fieldtrack.com', password: 'Dispatch123!' },
  { role: 'Dispatcher 2', email: 'dispatch2@fieldtrack.com', password: 'Dispatch123!' },
  { role: 'Supervisor', email: 'supervisor@fieldtrack.com', password: 'Super123!' },
]

export default function Login() {
  const { user, login } = useAuth()
  const navigate = useNavigate()
  const location = useLocation()
  const [form, setForm] = useState({ email: '', password: '' })
  const [errors, setErrors] = useState({})
  const [submitting, setSubmitting] = useState(false)

  if (user) return <Navigate to="/" replace />

  const update = (field) => (e) => {
    setForm({ ...form, [field]: e.target.value })
    setErrors({})
  }

  async function handleSubmit(e) {
    e.preventDefault()
    const clientErrors = {}
    if (!form.email.trim()) clientErrors.email = 'Email is required.'
    if (!form.password) clientErrors.password = 'Password is required.'
    if (Object.keys(clientErrors).length) return setErrors(clientErrors)

    setSubmitting(true)
    try {
      await login(form.email.trim(), form.password)
      navigate(location.state?.from?.pathname || '/', { replace: true })
    } catch (err) {
      setErrors(errorState(err, ['email', 'password']))
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="login">
      <section className="login__brand">
        <div className="login__logo">
          <BrandMark size={40} />
          <span>
            Field<span className="brand-accent">Track</span>
          </span>
        </div>
        <div>
          <h1 className="login__headline">
            Dispatch crews. Verify hours. <span className="brand-accent">Know they were on site.</span>
          </h1>
          <p className="login__tagline">
            The administrative portal for scheduling jobs, assigning crews and approving
            GPS-verified time.
          </p>
          <ul className="login__features">
            {[
              'No double-booked workers — ever',
              'Geofenced clock-ins flag off-site time automatically',
              'Supervisor approvals with a full audit trail',
              'Payroll-ready hours reports and CSV export',
            ].map((text) => (
              <li key={text}>
                <span className="dot">
                  <IconCheck size={14} />
                </span>
                {text}
              </li>
            ))}
          </ul>
        </div>
        <div className="small" style={{ color: 'rgba(255,255,255,0.45)' }}>
          © {new Date().getFullYear()} FieldTrack Construction Services
        </div>
      </section>

      <section className="login__formside">
        <form className="login__form form" onSubmit={handleSubmit} noValidate>
          <div>
            <h2 className="login__title">Sign in</h2>
            <p className="muted" style={{ margin: '4px 0 0' }}>
              Staff accounts only — admins, dispatchers and supervisors.
            </p>
          </div>

          {errors._form && <Alert>{errors._form}</Alert>}

          <FormField label="Email" htmlFor="email" error={errors.email}>
            <input
              id="email"
              className="input"
              type="email"
              autoComplete="username"
              value={form.email}
              onChange={update('email')}
              placeholder="you@fieldtrack.com"
            />
          </FormField>
          <FormField label="Password" htmlFor="password" error={errors.password}>
            <input
              id="password"
              className="input"
              type="password"
              autoComplete="current-password"
              value={form.password}
              onChange={update('password')}
            />
          </FormField>
          <button type="submit" className="btn btn--primary btn--block" disabled={submitting}>
            {submitting ? 'Signing in…' : 'Sign in'}
          </button>

          <div className="demo-accounts">
            <div className="small muted strong">Demo accounts — click to fill</div>
            <div className="demo-accounts__grid">
              {DEMO_ACCOUNTS.map((acc) => (
                <button
                  type="button"
                  key={acc.email}
                  className="demo-account"
                  onClick={() => {
                    setForm({ email: acc.email, password: acc.password })
                    setErrors({})
                  }}
                >
                  <div className="strong small">{acc.role}</div>
                  <div className="muted small">{acc.email}</div>
                </button>
              ))}
            </div>
          </div>
        </form>
      </section>
    </div>
  )
}
