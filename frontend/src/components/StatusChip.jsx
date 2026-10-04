// Maps every status the API can return to a colour tone.
const TONES = {
  // Jobs
  Scheduled: 'navy',
  'In progress': 'orange',
  Completed: 'green',
  // Time entries
  Pending: 'amber',
  Approved: 'green',
  Rejected: 'red',
  Flagged: 'amber',
  Open: 'orange',
  // Users
  Active: 'green',
  Inactive: 'muted',
  // Roles
  Admin: 'navy',
  Dispatcher: 'orange',
  Supervisor: 'green',
  Worker: 'muted',
}

/**
 * Coloured pill for job and time-entry statuses. The status text is always shown, so colour is
 * never the only signal.
 */
export default function StatusChip({ status, tone }) {
  return <span className={`chip chip--${tone || TONES[status] || 'muted'}`}>{status}</span>
}
