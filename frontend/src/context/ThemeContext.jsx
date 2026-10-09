import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react'

// Must match the inline script in index.html, which applies the theme before the first paint.
const THEME_KEY = 'fieldtrack_theme'
const ThemeContext = createContext(null)

function storedTheme() {
  try {
    const t = localStorage.getItem(THEME_KEY)
    return t === 'light' || t === 'dark' ? t : null
  } catch {
    return null
  }
}

const systemTheme = () => (window.matchMedia?.('(prefers-color-scheme: dark)').matches ? 'dark' : 'light')

/**
 * Light / dark theme. Until the user picks one with the toggle, the app follows the operating
 * system setting (and keeps following it if that changes); after that, their choice is kept in
 * localStorage. The theme is the data-theme attribute on <html>, which tokens.css keys off.
 */
export function ThemeProvider({ children }) {
  const [theme, setThemeState] = useState(() => storedTheme() || systemTheme())

  useEffect(() => {
    document.documentElement.dataset.theme = theme
  }, [theme])

  useEffect(() => {
    const media = window.matchMedia?.('(prefers-color-scheme: dark)')
    if (!media) return undefined
    const follow = () => !storedTheme() && setThemeState(systemTheme())
    media.addEventListener('change', follow)
    return () => media.removeEventListener('change', follow)
  }, [])

  const toggleTheme = useCallback(() => {
    setThemeState((current) => {
      const next = current === 'dark' ? 'light' : 'dark'
      try {
        localStorage.setItem(THEME_KEY, next)
      } catch {
        /* storage unavailable — the choice lasts until refresh */
      }
      return next
    })
  }, [])

  const value = useMemo(() => ({ theme, toggleTheme }), [theme, toggleTheme])
  return <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>
}

/** Read the current theme ('light' | 'dark') and toggleTheme() from any component. */
export function useTheme() {
  const ctx = useContext(ThemeContext)
  if (!ctx) throw new Error('useTheme must be used inside <ThemeProvider>')
  return ctx
}
