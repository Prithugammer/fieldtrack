import { IconAlert } from './Icons'

/**
 * Label + control + inline error.
 * Wrap any input/select/textarea that has className="input":
 *
 *   <FormField label="Crew size" htmlFor="crew" error={errors.crew_size} required>
 *     <input id="crew" className="input" ... />
 *   </FormField>
 */
export default function FormField({ label, htmlFor, error, hint, required, className = '', children }) {
  return (
    <div className={`field${error ? ' field--error' : ''} ${className}`.trim()}>
      {label && (
        <label className="field__label" htmlFor={htmlFor}>
          {label}
          {required && <span className="field__required">*</span>}
        </label>
      )}
      {children}
      {error ? (
        <div className="field__error" role="alert">
          <IconAlert size={14} style={{ flexShrink: 0, marginTop: 1 }} />
          <span>{error}</span>
        </div>
      ) : (
        hint && <div className="field__hint">{hint}</div>
      )}
    </div>
  )
}
