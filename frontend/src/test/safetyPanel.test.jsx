import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import SafetyPanel from '../components/SafetyPanel'

const CONFIG = {
  mode: 'demo',
  idle_threshold_seconds: 15,
  num_checkins: 3,
  checkin_response_window_seconds: 5,
}

const emergency = {
  worker_id: 7,
  worker_name: 'Bishal Neupane',
  state: 'EMERGENCY',
  stage: 'EMERGENCY',
  level: 'critical',
  trigger: 'sos',
  incapacitated: false,
  started_at: null,
  elapsed_s: 12,
  window_remaining_s: null,
  location: { lat: 27.7, lng: 85.3, label: 'On site at Kirtipur' },
  nearest_coworker: null,
  resolution: null,
}

const postIncident = {
  ...emergency,
  worker_id: 8,
  worker_name: 'Sita Rai',
  location: { lat: 27.71, lng: 85.31, label: 'Near Koteshwor' },
  state: 'POST_INCIDENT',
  stage: 'Post-incident',
  level: 'info',
  resolution: { outcome: 'real_incident', note: 'Cut hand' },
}

const safety = (alerts) => ({
  config: CONFIG,
  privacy_note: 'Privacy: location data is used only to raise safety alerts.',
  alerts,
  notifications: [],
})

describe('SafetyPanel role behaviour', () => {
  it('lets a supervisor resolve an emergency and return a worker to duty', async () => {
    const onAction = vi.fn()
    const user = userEvent.setup()
    render(<SafetyPanel safety={safety([emergency, postIncident])} workers={[]} onAction={onAction} />)

    await user.type(screen.getByLabelText('Resolution note for Bishal Neupane'), 'Tied a bootlace')
    await user.click(screen.getByRole('button', { name: /false alarm/ }))
    expect(onAction).toHaveBeenCalledWith('workers/7/resolve', {
      outcome: 'false_alarm',
      note: 'Tied a bootlace',
    })
    await user.click(screen.getByRole('button', { name: 'Return to duty' }))
    expect(onAction).toHaveBeenCalledWith('workers/8/return-to-duty')
  })

  it('shows a dispatcher the alerts but none of the controls', () => {
    render(<SafetyPanel safety={safety([emergency, postIncident])} workers={[]} onAction={null} />)
    expect(screen.getByText('Bishal Neupane')).toBeInTheDocument()
    expect(screen.getByText('On site at Kirtipur')).toBeInTheDocument()
    expect(screen.getByText(/1 emergency/)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Resolved/ })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Return to duty' })).not.toBeInTheDocument()
    expect(screen.queryByLabelText(/Resolution note/)).not.toBeInTheDocument()
    expect(screen.getByText('Note: Cut hand')).toBeInTheDocument()
  })

  it('says all is clear when there are no alerts', () => {
    render(<SafetyPanel safety={safety([])} workers={[]} onAction={null} />)
    expect(screen.getByText('All clear')).toBeInTheDocument()
    expect(screen.getByText(/No active alerts/)).toBeInTheDocument()
  })
})
