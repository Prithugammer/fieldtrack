import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react'
import { Navigate, useLocation } from 'react-router-dom'
import { api, setAuthToken, setUnauthorizedHandler } from '../api/client'
import { LoadingState } from '../components/States'

const TOKEN_KEY = 'fieldtrack_token'
const AuthContext = createContext(null)

function readStoredToken() {
  try {
    return localStorage.getItem(TOKEN_KEY)
  } catch {
    return null
  }
}

function storeToken(token) {
  try {
    if (token) localStorage.setItem(TOKEN_KEY, token)
    else localStorage.removeItem(TOKEN_KEY)
  } catch {
    /* storage unavailable — session lasts until refresh */
  }
}

export function AuthProvider({ children }) {
  const [token, setToken] = useState(() => {
    const stored = readStoredToken()
    setAuthToken(stored)
    return stored
  })
  const [user, setUser] = useState(null)
  const [checking, setChecking] = useState(Boolean(token))

  const logout = useCallback(() => {
    setAuthToken(null)
    storeToken(null)
    setToken(null)
    setUser(null)
  }, [])

  // Any 401 from the API (expired token) signs the user out.
  useEffect(() => {
    setUnauthorizedHandler(logout)
  }, [logout])

  // Restore the session on page load by asking the API who the stored token belongs to.
  useEffect(() => {
    if (!token || user) {
      setChecking(false)
      return
    }
    let cancelled = false
    api('/auth/me')
      .then((data) => !cancelled && setUser(data.user))
      .catch(() => !cancelled && logout())
      .finally(() => !cancelled && setChecking(false))
    return () => {
      cancelled = true
    }
  }, [token, user, logout])

  const login = useCallback(async (email, password) => {
    const data = await api('/auth/login', { method: 'POST', body: { email, password } })
    setAuthToken(data.token)
    storeToken(data.token)
    setToken(data.token)
    setUser(data.user)
    return data.user
  }, [])

  const value = useMemo(
    () => ({
      user,
      token,
      checking,
      login,
      logout,
      hasRole: (...roles) => Boolean(user && roles.includes(user.role)),
    }),
    [user, token, checking, login, logout],
  )

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth() {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth must be used inside <AuthProvider>')
  return ctx
}

/** Renders children only for a logged-in user (optionally with one of `roles`). */
export function ProtectedRoute({ children, roles }) {
  const { user, checking } = useAuth()
  const location = useLocation()

  if (checking) {
    return (
      <div className="full-page-state">
        <LoadingState label="Restoring your session…" />
      </div>
    )
  }
  if (!user) return <Navigate to="/login" replace state={{ from: location }} />
  if (roles && !roles.includes(user.role)) return <Navigate to="/" replace />
  return children
}
