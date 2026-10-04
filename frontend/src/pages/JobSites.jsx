import { useState } from 'react'
import { api } from '../api/client'
import { useApi } from '../api/useApi'
import DataTable from '../components/DataTable'
import FormField from '../components/FormField'
import { IconPlus } from '../components/Icons'
import Modal from '../components/Modal'
import TopBar from '../components/TopBar'
import { Alert } from '../components/States'
import { useAuth } from '../context/AuthContext'
import { errorState } from '../utils/format'

const SITE_FIELDS = ['site_name', 'address', 'latitude', 'longitude', 'geofence_radius_m']

/**
 * Geolocated job sites. Each site carries the geofence radius its time entries are checked
 * against, so the radius is data the dispatcher can edit, not a constant in the code.
 */
export default function JobSites() {
  const { hasRole } = useAuth()
  const canEdit = hasRole('Admin', 'Dispatcher')
  const { data, loading, error, reload } = useApi('/sites')
  const [editing, setEditing] = useState(null) // null | 'new' | site
  const [notice, setNotice] = useState(null)

  const columns = [
    {
      key: 'site_name',
      header: 'Site',
      render: (s) => (
        <>
          <div className="cell-title">{s.site_name}</div>
          <div className="cell-sub">{s.address}</div>
        </>
      ),
    },
    {
      key: 'coords',
      header: 'Coordinates',
      render: (s) => (
        <span className="num">
          {s.latitude.toFixed(6)}, {s.longitude.toFixed(6)}
        </span>
      ),
    },
    {
      key: 'geofence_radius_m',
      header: 'Geofence',
      align: 'right',
      render: (s) => <span className="num">{s.geofence_radius_m} m</span>,
    },
    { key: 'job_count', header: 'Jobs', align: 'right', render: (s) => <span className="num">{s.job_count}</span> },
    {
      key: 'actions',
      header: '',
      align: 'right',
      render: (s) =>
        canEdit && (
          <button type="button" className="btn btn--secondary btn--sm" onClick={() => setEditing(s)}>
            Edit
          </button>
        ),
    },
  ]

  return (
    <>
      <TopBar
        title="Job Sites"
        subtitle="Locations and geofence radius used to verify clock-ins"
        actions={
          canEdit && (
            <button type="button" className="btn btn--primary" onClick={() => setEditing('new')}>
              <IconPlus size={16} /> New site
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
        <div className="card">
          <DataTable
            columns={columns}
            rows={data?.sites}
            rowKey="site_id"
            loading={loading}
            error={error}
            onRetry={reload}
            emptyTitle="No job sites yet"
            emptyMessage="Add a site with its GPS coordinates to start scheduling jobs."
          />
        </div>
      </div>
      {editing && (
        <SiteFormModal
          site={editing === 'new' ? null : editing}
          onClose={() => setEditing(null)}
          onSaved={(site, isNew) => {
            setEditing(null)
            setNotice(`Site “${site.site_name}” ${isNew ? 'created' : 'updated'}.`)
            reload()
          }}
        />
      )}
    </>
  )
}

/**
 * Create or edit a site. Coordinates and the 25–5000 m radius are validated on the server.
 */
function SiteFormModal({ site, onClose, onSaved }) {
  const isNew = !site
  const [form, setForm] = useState({
    site_name: site?.site_name ?? '',
    address: site?.address ?? '',
    latitude: site?.latitude ?? '',
    longitude: site?.longitude ?? '',
    geofence_radius_m: site?.geofence_radius_m ?? 200,
  })
  const [errors, setErrors] = useState({})
  const [saving, setSaving] = useState(false)

  const set = (field) => (e) => {
    setForm({ ...form, [field]: e.target.value })
    setErrors({ ...errors, [field]: undefined, _form: undefined })
  }

  async function submit(e) {
    e.preventDefault()
    setSaving(true)
    try {
      const res = isNew
        ? await api('/sites', { method: 'POST', body: form })
        : await api(`/sites/${site.site_id}`, { method: 'PATCH', body: form })
      onSaved(res.site, isNew)
    } catch (err) {
      setErrors(errorState(err, SITE_FIELDS))
    } finally {
      setSaving(false)
    }
  }

  return (
    <Modal
      open
      title={isNew ? 'New job site' : 'Edit job site'}
      onClose={onClose}
      footer={
        <>
          <button type="button" className="btn btn--secondary" onClick={onClose}>
            Cancel
          </button>
          <button type="submit" form="site-form" className="btn btn--primary" disabled={saving}>
            {saving ? 'Saving…' : isNew ? 'Create site' : 'Save changes'}
          </button>
        </>
      }
    >
      <form id="site-form" className="form" onSubmit={submit} noValidate>
        {errors._form && <Alert>{errors._form}</Alert>}
        <div className="form-grid">
          <FormField label="Site name" htmlFor="site-name" error={errors.site_name} required className="span-2">
            <input id="site-name" className="input" value={form.site_name} onChange={set('site_name')} />
          </FormField>
          <FormField label="Address" htmlFor="site-address" error={errors.address} required className="span-2">
            <input id="site-address" className="input" value={form.address} onChange={set('address')} />
          </FormField>
          <FormField label="Latitude" htmlFor="site-lat" error={errors.latitude} required hint="−90 to 90, e.g. 43.659100">
            <input id="site-lat" type="number" step="0.000001" className="input" value={form.latitude} onChange={set('latitude')} />
          </FormField>
          <FormField label="Longitude" htmlFor="site-lng" error={errors.longitude} required hint="−180 to 180, e.g. -79.350300">
            <input id="site-lng" type="number" step="0.000001" className="input" value={form.longitude} onChange={set('longitude')} />
          </FormField>
          <FormField
            label="Geofence radius (m)"
            htmlFor="site-radius"
            error={errors.geofence_radius_m}
            required
            hint="Clock-ins farther than this from the site are flagged (25–5000 m)."
            className="span-2"
          >
            <input id="site-radius" type="number" min="25" max="5000" className="input" value={form.geofence_radius_m} onChange={set('geofence_radius_m')} />
          </FormField>
        </div>
      </form>
    </Modal>
  )
}
