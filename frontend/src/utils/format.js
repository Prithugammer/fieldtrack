// Display helpers. The API sends local times without a timezone ("2026-10-01T07:00:00"),
// which the browser parses as local time — exactly what we want for a site's clock.

const pad = (n) => String(n).padStart(2, '0')

/** "2026-10-01" -> Date at local midnight (avoids the UTC shift of new Date('2026-10-01')). */
export function parseDateOnly(iso) {
  const [y, m, d] = iso.split('-').map(Number)
  return new Date(y, m - 1, d)
}

export function toISODate(date) {
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`
}

export function todayISO() {
  return toISODate(new Date())
}

export function addDays(iso, days) {
  const d = parseDateOnly(iso)
  d.setDate(d.getDate() + days)
  return toISODate(d)
}

export function formatDate(iso) {
  if (!iso) return '—'
  return parseDateOnly(iso).toLocaleDateString(undefined, {
    weekday: 'short',
    month: 'short',
    day: 'numeric',
  })
}

export function formatDateTime(iso) {
  if (!iso) return '—'
  return new Date(iso).toLocaleString(undefined, {
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  })
}

export function formatHours(hours) {
  if (hours === null || hours === undefined) return '—'
  return `${Number(hours).toFixed(2)} h`
}

export function formatMetres(m) {
  if (m === null || m === undefined) return '—'
  return `${Math.round(m)} m`
}

/** Value for <input type="datetime-local">: "YYYY-MM-DDTHH:MM". */
export function toLocalInput(date) {
  return `${toISODate(date)}T${pad(date.getHours())}:${pad(date.getMinutes())}`
}

export function initials(name = '') {
  return name
    .split(' ')
    .filter(Boolean)
    .slice(0, 2)
    .map((part) => part[0].toUpperCase())
    .join('')
}

/**
 * Turn an ApiError into form error state: if the server named a field this form has,
 * show the message under that field; otherwise show it at the top of the form.
 */
export function errorState(err, fields) {
  if (err.field && fields.includes(err.field)) return { [err.field]: err.message }
  return { _form: err.message }
}
