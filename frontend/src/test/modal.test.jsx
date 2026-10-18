import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useState } from 'react'
import { describe, expect, it } from 'vitest'
import Modal from '../components/Modal'

function Harness() {
  const [open, setOpen] = useState(false)
  return (
    <>
      <button type="button" onClick={() => setOpen(true)}>
        Open dialog
      </button>
      <button type="button">Behind the dialog</button>
      <Modal
        open={open}
        title="Edit thing"
        onClose={() => setOpen(false)}
        footer={
          <>
            <button type="button" onClick={() => setOpen(false)}>
              Cancel
            </button>
            <button type="button">Save</button>
          </>
        }
      >
        <label htmlFor="a">First</label>
        <input id="a" />
        <label htmlFor="b">Second</label>
        <input id="b" />
      </Modal>
    </>
  )
}

const dialog = () => screen.getByRole('dialog')
const inside = () => dialog().contains(document.activeElement)

describe('Modal accessibility', () => {
  it('moves focus into the dialog when it opens', async () => {
    const user = userEvent.setup()
    render(<Harness />)
    await user.click(screen.getByRole('button', { name: 'Open dialog' }))
    expect(inside()).toBe(true)
    expect(document.activeElement).toHaveAttribute('id', 'a') // the first form control
  })

  it('keeps Tab inside the dialog, wrapping from the last control to the first', async () => {
    const user = userEvent.setup()
    render(<Harness />)
    await user.click(screen.getByRole('button', { name: 'Open dialog' }))
    for (let i = 0; i < 30; i++) {
      await user.tab()
      expect(inside()).toBe(true)
    }
  })

  it('keeps Shift+Tab inside the dialog, wrapping from the first control to the last', async () => {
    const user = userEvent.setup()
    render(<Harness />)
    await user.click(screen.getByRole('button', { name: 'Open dialog' }))
    for (let i = 0; i < 30; i++) {
      await user.tab({ shift: true })
      expect(inside()).toBe(true)
    }
    await user.tab({ shift: true })
    await user.tab({ shift: true })
    expect(document.activeElement).not.toBe(screen.getByRole('button', { name: 'Behind the dialog' }))
  })

  it('wraps exactly: Shift+Tab past the first control reaches the last one, and Tab wraps back', async () => {
    const user = userEvent.setup()
    render(<Harness />)
    await user.click(screen.getByRole('button', { name: 'Open dialog' }))
    expect(document.activeElement).toHaveAttribute('id', 'a')
    await user.tab({ shift: true }) // the header's Close button comes before the first field
    expect(document.activeElement).toBe(screen.getByRole('button', { name: 'Close' }))
    await user.tab({ shift: true }) // before the very first control: wrap to the last
    expect(document.activeElement).toBe(screen.getByRole('button', { name: 'Save' }))
    await user.tab() // after the very last control: wrap to the first
    expect(document.activeElement).toBe(screen.getByRole('button', { name: 'Close' }))
  })

  it('closes on Escape and gives focus back to the button that opened it', async () => {
    const user = userEvent.setup()
    render(<Harness />)
    const opener = screen.getByRole('button', { name: 'Open dialog' })
    await user.click(opener)
    await user.keyboard('{Escape}')
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    expect(opener).toHaveFocus()
  })

  it('also returns focus when closed with the Cancel button, and labels the dialog by its title', async () => {
    const user = userEvent.setup()
    render(<Harness />)
    const opener = screen.getByRole('button', { name: 'Open dialog' })
    await user.click(opener)
    expect(screen.getByRole('dialog', { name: 'Edit thing' })).toHaveAttribute('aria-modal', 'true')
    await user.click(screen.getByRole('button', { name: 'Cancel' }))
    expect(opener).toHaveFocus()
  })
})
