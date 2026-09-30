import { Outlet } from 'react-router-dom'
import Sidebar from './Sidebar'

/** Authenticated app shell: fixed navy sidebar + page content. */
export default function Layout() {
  return (
    <div className="app-shell">
      <Sidebar />
      <main className="app-main">
        <Outlet />
      </main>
    </div>
  )
}
