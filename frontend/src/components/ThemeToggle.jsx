import { useTheme } from '../context/ThemeContext'
import { IconMoon, IconSun } from './Icons'

/** Icon button that switches between the light and dark theme. */
export default function ThemeToggle() {
  const { theme, toggleTheme } = useTheme()
  const label = theme === 'dark' ? 'Switch to light mode' : 'Switch to dark mode'
  return (
    <button
      type="button"
      className="btn btn--ghost btn--sm btn--icon"
      onClick={toggleTheme}
      title={label}
      aria-label={label}
    >
      {theme === 'dark' ? <IconSun size={18} /> : <IconMoon size={18} />}
    </button>
  )
}
