import { useEffect, useRef } from 'react'

const FOCUSABLE =
  'a[href], button:not([disabled]), input:not([disabled]):not([type="hidden"]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])'

/** Dialog with header, scrollable body and footer. Closes on Escape or overlay click; keeps Tab
 * inside while open and gives focus back to the opening control on close. */
export default function Modal({ open, title, onClose, children, footer, wide = false }) {
  const dialogRef = useRef(null)
  // Keep the latest onClose in a ref so the effect below only runs when the modal opens
  // (otherwise every parent re-render would move focus back to the first field).
  const onCloseRef = useRef(onClose)
  onCloseRef.current = onClose

  useEffect(() => {
    if (!open) return undefined
    const opener = document.activeElement // where focus goes back to when the dialog closes
    const focusable = () =>
      [...(dialogRef.current?.querySelectorAll(FOCUSABLE) || [])].filter((el) => !el.hidden)
    const onKey = (e) => {
      if (e.key === 'Escape') return onCloseRef.current()
      if (e.key !== 'Tab') return
      // Focus trap: Tab and Shift+Tab cycle inside the dialog instead of reaching the page behind it.
      const items = focusable()
      if (items.length === 0) return e.preventDefault()
      const first = items[0]
      const last = items[items.length - 1]
      const inside = dialogRef.current.contains(document.activeElement)
      if (e.shiftKey && (!inside || document.activeElement === first)) {
        e.preventDefault()
        last.focus()
      } else if (!e.shiftKey && (!inside || document.activeElement === last)) {
        e.preventDefault()
        first.focus()
      }
    }
    document.addEventListener('keydown', onKey)
    // Focus the first form control for keyboard users.
    const first = dialogRef.current?.querySelector('input, select, textarea, button:not(.modal__close)')
    first?.focus()
    return () => {
      document.removeEventListener('keydown', onKey)
      if (opener && opener !== document.body && document.contains(opener)) opener.focus()
    }
  }, [open])

  if (!open) return null

  return (
    <div className="modal-overlay" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div
        className={`modal${wide ? ' modal--wide' : ''}`}
        role="dialog"
        aria-modal="true"
        aria-labelledby="modal-title"
        ref={dialogRef}
      >
        <div className="modal__header">
          <h2 className="modal__title" id="modal-title">
            {title}
          </h2>
          <button type="button" className="modal__close" onClick={onClose} aria-label="Close">
            ×
          </button>
        </div>
        <div className="modal__body">{children}</div>
        {footer && <div className="modal__footer">{footer}</div>}
      </div>
    </div>
  )
}
