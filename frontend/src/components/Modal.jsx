import { useEffect, useRef } from 'react'

/** Dialog with header, scrollable body and footer. Closes on Escape or overlay click. */
export default function Modal({ open, title, onClose, children, footer, wide = false }) {
  const dialogRef = useRef(null)
  // Keep the latest onClose in a ref so the effect below only runs when the modal opens
  // (otherwise every parent re-render would move focus back to the first field).
  const onCloseRef = useRef(onClose)
  onCloseRef.current = onClose

  useEffect(() => {
    if (!open) return undefined
    const onKey = (e) => e.key === 'Escape' && onCloseRef.current()
    document.addEventListener('keydown', onKey)
    // Focus the first form control for keyboard users.
    const first = dialogRef.current?.querySelector('input, select, textarea, button:not(.modal__close)')
    first?.focus()
    return () => document.removeEventListener('keydown', onKey)
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
