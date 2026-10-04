import { NavLink } from 'react-router-dom'
import {
  IconBriefcase,
  IconChart,
  IconClock,
  IconDashboard,
  IconMap,
  IconPin,
  IconUsers,
} from './Icons'

const SECTIONS = [
  {
    title: 'Operations',
    links: [
      { to: '/', label: 'Dashboard', icon: IconDashboard, end: true },
      { to: '/jobs', label: 'Jobs', icon: IconBriefcase },
      { to: '/live-map', label: 'Live Map', icon: IconMap },
      { to: '/sites', label: 'Job Sites', icon: IconPin },
      { to: '/crew', label: 'Crew', icon: IconUsers },
    ],
  },
  {
    title: 'Time & Pay',
    links: [
      { to: '/time-entries', label: 'Time Entries', icon: IconClock },
      { to: '/reports', label: 'Reports', icon: IconChart },
    ],
  },
]

export function BrandMark({ size = 32 }) {
  return (
    <div className="brand-mark" style={{ width: size, height: size }}>
      <svg width={size * 0.6} height={size * 0.6} viewBox="0 0 24 24" aria-hidden="true">
        <path
          d="M12 2c-4 0-7 3-7 7 0 5.2 7 13 7 13s7-7.8 7-13c0-4-3-7-7-7zm0 9.5a2.5 2.5 0 110-5 2.5 2.5 0 010 5z"
          fill="#fff"
        />
      </svg>
    </div>
  )
}

export default function Sidebar() {
  return (
    <aside className="sidebar">
      <div className="sidebar__brand">
        <BrandMark />
        <span>
          Field<span className="brand-accent">Track</span>
        </span>
      </div>
      <nav className="sidebar__nav" aria-label="Main">
        {SECTIONS.map((section) => (
          <div key={section.title}>
            <div className="sidebar__section">{section.title}</div>
            {section.links.map(({ to, label, icon: Icon, end }) => (
              <NavLink key={to} to={to} end={end} className="sidebar__link">
                <Icon />
                <span>{label}</span>
              </NavLink>
            ))}
          </div>
        ))}
      </nav>
      <div className="sidebar__footer">FieldTrack v1.0 · Admin portal</div>
    </aside>
  )
}
