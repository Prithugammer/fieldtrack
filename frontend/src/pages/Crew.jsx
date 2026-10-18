import { useState } from 'react'
import { api } from '../api/client'
import { useApi } from '../api/useApi'
import DataTable from '../components/DataTable'
import FormField from '../components/FormField'
import { IconPlus } from '../components/Icons'
import Modal from '../components/Modal'
import StatusChip from '../components/StatusChip'
import TopBar from '../components/TopBar'
import { Alert } from '../components/States'
import { useAuth } from '../context/AuthContext'
import { errorState } from '../utils/format'

const ROLES = ['Worker', 'Dispatcher', 'Supervisor', 'Admin']
const USER_FIELDS = ['full_name', 'email', 'phone', 'role', 'trade', 'password', 'is_active']
const TABS = [
  { key: '', label: 'Everyone' },
  { key: 'Worker', label: 'Workers' },
  { key: 'staff', label: 'Staff' },
]

/**
 * People: staff (who log in) and workers (records only). Admins can add, edit and deactivate.
 * People are deactivated rather than deleted so their past time entries stay intact for payroll.
 */
export default function Crew() {
  const { hasRole, user: me } = useAuth()
  const isAdmin = hasRole('Admin')
  const [tab, setTab] = useState('')
  const { data, loading, error, reload } = useApi('/users', tab === 'Worker' ? { role: 'Worker' } : undefined)
  const [editing, setEditing] = useState(null)
  const [notice, setNotice] = useState(null)
  const [actionError, setActionError] = useState(null)

  const rows = (data?.users || []).filter((u) => tab !== 'staff' || u.role !== 'Worker')

  async function toggleActive(u) {
    setActionError(null)
    try {
      const res = await api(`/users/${u.user_id}`, { method: 'PATCH', body: { is_active: !u.is_active } })
      setNotice(`${res.user.full_name} ${res.user.is_active ? 'activated' : 'deactivated'}.`)
      reload()
    } catch (err) {
      setActionError(err.message)
    }
  }

  const columns = [
    {
      key: 'full_name',
      header: 'Name',
      render: (u) => (
        <>
          <div className="cell-title">{u.full_name}</div>
          <div className="cell-sub">{u.email}</div>
        </>
      ),
    },
    { key: 'phone', header: 'Phone', render: (u) => <span className="num">{u.phone || '—'}</span> },
    { key: 'role', header: 'Role', render: (u) => <StatusChip status={u.role} /> },
    { key: 'trade', header: 'Trade', render: (u) => u.trade || <span className="muted">—</span> },
    {
      key: 'is_active',
      header: 'Status',
      render: (u) => <StatusChip status={u.is_active ? 'Active' : 'Inactive'} />,
    },
    {
      key: 'actions',
      header: '',
      align: 'right',
      render: (u) =>
        isAdmin && (
          <div className="actions">
            <button type="button" className="btn btn--secondary btn--sm" onClick={() => setEditing(u)}>
              Edit
            </button>
            {u.user_id !== me.user_id && (
              <button
                type="button"
                className={`btn btn--sm ${u.is_active ? 'btn--ghost' : 'btn--success'}`}
                onClick={() => toggleActive(u)}
              >
                {u.is_active ? 'Deactivate' : 'Activate'}
              </button>
            )}
          </div>
        ),
    },
  ]

  return (
    <>
      <TopBar
        title="Crew"
        subtitle="Workers and staff accounts"
        actions={
          isAdmin && (
            <button type="button" className="btn btn--primary" onClick={() => setEditing('new')}>
              <IconPlus size={16} /> Add person
            </button>
          )
        }
      />
      <div className="page">
        {notice && (
          <Alert tone="success" onClose={() => setNotice(null)}>
            {notice}
          </Alert>
        )}
        {actionError && <Alert onClose={() => setActionError(null)}>{actionError}</Alert>}
        <div className="card">
          <div className="card__header">
            <div className="segmented" role="tablist">
              {TABS.map((t) => (
                <button
                  key={t.key}
                  type="button"
                  role="tab"
                  aria-selected={tab === t.key}
                  className={tab === t.key ? 'is-active' : ''}
                  onClick={() => setTab(t.key)}
                >
                  {t.label}
                </button>
              ))}
            </div>
            {!isAdmin && <span className="muted small">Only admins can edit people.</span>}
          </div>
          <DataTable
            columns={columns}
            rows={data ? rows : null}
            rowKey="user_id"
            loading={loading}
            error={error}
            onRetry={reload}
            emptyTitle="No people found"
          />
        </div>
      </div>
      {editing && (
        <UserFormModal
          person={editing === 'new' ? null : editing}
          onClose={() => setEditing(null)}
          onSaved={(u, isNew) => {
            setEditing(null)
            setNotice(`${u.full_name} ${isNew ? 'added' : 'updated'}.`)
            reload()
          }}
        />
      )}
    </>
  )
}

/**
 * Create or edit a user. Staff need a password (they log in); workers need a trade (they are
 * dispatched by skill). The server enforces both; this form shows its field errors inline.
 */
function UserFormModal({ person, onClose, onSaved }) {
  const isNew = !person
  const [form, setForm] = useState({
    full_name: person?.full_name ?? '',
    email: person?.email ?? '',
    phone: person?.phone ?? '',
    role: person?.role ?? 'Worker',
    trade: person?.trade ?? '',
    password: '',
  })
  const [errors, setErrors] = useState({})
  const [saving, setSaving] = useState(false)
  const isWorker = form.role === 'Worker'

  const set = (field) => (e) => {
    setForm({ ...form, [field]: e.target.value })
    setErrors({ ...errors, [field]: undefined, _form: undefined })
  }

  async function submit(e) {
    e.preventDefault()
    setSaving(true)
    const body = { ...form }
    if (!body.password) delete body.password
    if (!isWorker && !body.trade) body.trade = null
    try {
      const res = isNew
        ? await api('/users', { method: 'POST', body })
        : await api(`/users/${person.user_id}`, { method: 'PATCH', body })
      onSaved(res.user, isNew)
    } catch (err) {
      setErrors(errorState(err, USER_FIELDS))
    } finally {
      setSaving(false)
    }
  }

  return (
    <Modal
      open
      title={isNew ? 'Add person' : `Edit ${person.full_name}`}
      onClose={onClose}
      footer={
        <>
          <button type="button" className="btn btn--secondary" onClick={onClose}>
            Cancel
          </button>
          <button type="submit" form="user-form" className="btn btn--primary" disabled={saving}>
            {saving ? 'Saving…' : isNew ? 'Add person' : 'Save changes'}
          </button>
        </>
      }
    >
      <form id="user-form" className="form" onSubmit={submit} noValidate>
        {errors._form && <Alert>{errors._form}</Alert>}
        <div className="form-grid">
          <FormField label="Full name" htmlFor="u-name" error={errors.full_name} required className="span-2">
            <input id="u-name" className="input" value={form.full_name} onChange={set('full_name')} />
          </FormField>
          <FormField label="Email" htmlFor="u-email" error={errors.email} required>
            <input id="u-email" type="email" className="input" value={form.email} onChange={set('email')} />
          </FormField>
          <FormField label="Phone" htmlFor="u-phone" error={errors.phone}>
            <input
              id="u-phone"
              className="input"
              value={form.phone}
              onChange={set('phone')}
              placeholder="+977-98XXXXXXXX"
            />
          </FormField>
          <FormField label="Role" htmlFor="u-role" error={errors.role} required>
            <select id="u-role" className="input" value={form.role} onChange={set('role')}>
              {ROLES.map((r) => (
                <option key={r}>{r}</option>
              ))}
            </select>
          </FormField>
          <FormField label="Trade" htmlFor="u-trade" error={errors.trade} required={isWorker}>
            <input
              id="u-trade"
              className="input"
              value={form.trade}
              onChange={set('trade')}
              placeholder="e.g. Carpenter"
            />
          </FormField>
          {!isWorker && (
            <FormField
              label={isNew ? 'Password' : 'New password'}
              htmlFor="u-password"
              error={errors.password}
              required={isNew}
              hint={isNew ? 'At least 8 characters.' : 'Leave blank to keep the current password.'}
              className="span-2"
            >
              <input
                id="u-password"
                type="password"
                className="input"
                value={form.password}
                onChange={set('password')}
                autoComplete="new-password"
              />
            </FormField>
          )}
        </div>
        {isWorker && <div className="field__hint">Workers don’t log in, so they don’t need a password.</div>}
      </form>
    </Modal>
  )
}
