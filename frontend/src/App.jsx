import { Suspense, lazy } from 'react'
import { Navigate, Route, Routes } from 'react-router-dom'
import Layout from './components/Layout'
import { ProtectedRoute } from './context/AuthContext'
import Crew from './pages/Crew'
import Dashboard from './pages/Dashboard'
import Jobs from './pages/Jobs'
import JobSites from './pages/JobSites'
import Login from './pages/Login'
import Reports from './pages/Reports'
import { LoadingState } from './components/States'
import TimeEntries from './pages/TimeEntries'

// The Live Map pulls in Leaflet (the largest dependency), so it is fetched only when opened.
const LiveMap = lazy(() => import('./pages/LiveMap'))

/**
 * Route table. Everything except /login sits inside ProtectedRoute + Layout, so a missing or
 * expired session always lands on the login page, and only staff roles get past it.
 */
export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<Login />} />
      <Route
        element={
          <ProtectedRoute roles={['Admin', 'Dispatcher', 'Supervisor']}>
            <Layout />
          </ProtectedRoute>
        }
      >
        <Route index element={<Dashboard />} />
        <Route path="jobs" element={<Jobs />} />
        <Route
          path="live-map"
          element={
            <Suspense fallback={<LoadingState label="Loading the map…" />}>
              <LiveMap />
            </Suspense>
          }
        />
        <Route path="sites" element={<JobSites />} />
        <Route path="crew" element={<Crew />} />
        <Route path="time-entries" element={<TimeEntries />} />
        <Route path="reports" element={<Reports />} />
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  )
}
