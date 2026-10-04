// Loading, empty and error states used on every page.

export function LoadingState({ label = 'Loading…' }) {
  return (
    <div className="state" role="status">
      <div className="spinner" />
      <div>{label}</div>
    </div>
  )
}

/**
 * Shown when a list has no rows, so an empty table reads as "nothing yet" rather than broken.
 */
export function EmptyState({ title = 'Nothing here yet', message, action }) {
  return (
    <div className="state">
      <div className="state__title">{title}</div>
      {message && <div>{message}</div>}
      {action}
    </div>
  )
}

/**
 * Shown when a request fails: the server's own message plus a "Try again" button, never a blank page.
 */
export function ErrorState({ message, onRetry }) {
  return (
    <div className="state">
      <div className="state__title" style={{ color: 'var(--color-red)' }}>
        Couldn’t load this data
      </div>
      <div>{message}</div>
      {onRetry && (
        <button type="button" className="btn btn--secondary btn--sm" onClick={onRetry}>
          Try again
        </button>
      )}
    </div>
  )
}

/**
 * Inline banner for success / warning / error messages. Errors use role="alert" so screen
 * readers announce them; the others use role="status".
 */
export function Alert({ tone = 'error', children, onClose }) {
  return (
    <div className={`alert alert--${tone}`} role={tone === 'error' ? 'alert' : 'status'}>
      <div>{children}</div>
      {onClose && (
        <button type="button" className="alert__close" onClick={onClose} aria-label="Dismiss">
          ×
        </button>
      )}
    </div>
  )
}
