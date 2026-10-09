import { useAuth } from '../context/AuthContext'
import { initials } from '../utils/format'
import { IconLogout } from './Icons'
import ThemeToggle from './ThemeToggle'

/** Page header: title + subtitle on the left, page actions and the signed-in user on the right. */
export default function TopBar({ title, subtitle, actions }) {
  const { user, logout } = useAuth()
  return (
    <header className="topbar">
      <div>
        <h1 className="topbar__title">{title}</h1>
        {subtitle && <div className="topbar__subtitle">{subtitle}</div>}
      </div>
      <div className="topbar__user">
        {actions}
        <ThemeToggle />
        {user && (
          <>
            <div className="avatar" title={user.full_name}>
              {initials(user.full_name)}
            </div>
            <div className="topbar__meta">
              <div className="topbar__name">{user.full_name}</div>
              <div className="topbar__role">{user.role}</div>
            </div>
            <button
              type="button"
              className="btn btn--ghost btn--sm"
              onClick={logout}
              title="Sign out"
              // the text label is hidden on narrow screens, leaving only the icon
              aria-label="Sign out"
            >
              <IconLogout size={16} />
              <span className="topbar__meta">Sign out</span>
            </button>
          </>
        )}
      </div>
    </header>
  )
}
