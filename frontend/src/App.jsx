import { Navigate, Route, Routes } from 'react-router-dom'
import Layout from './components/Layout'
import { ProtectedRoute } from './context/AuthContext'
import Crew from './pages/Crew'
import Dashboard from './pages/Dashboard'
import Jobs from './pages/Jobs'
import JobSites from './pages/JobSites'
import Login from './pages/Login'

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
        <Route path="sites" element={<JobSites />} />
        <Route path="crew" element={<Crew />} />
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  )
}
