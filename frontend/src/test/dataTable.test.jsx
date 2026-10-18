import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import DataTable from '../components/DataTable'

const columns = [
  { key: 'name', header: 'Name' },
  { key: 'hours', header: 'Hours', align: 'right' },
]

describe('DataTable', () => {
  it('renders rows inside a named, keyboard-focusable scroll region', async () => {
    render(
      <DataTable
        columns={columns}
        rows={[{ id: 1, name: 'Ramesh Karki', hours: 4.5 }]}
        rowKey="id"
        label="Jobs table"
      />,
    )
    const region = screen.getByRole('region', { name: 'Jobs table' })
    expect(region).toHaveAttribute('tabindex', '0')
    await userEvent.tab()
    expect(region).toHaveFocus() // a keyboard user can reach it to scroll a wide table
    expect(screen.getByRole('table')).toBeInTheDocument()
    expect(screen.getByText('Ramesh Karki')).toBeInTheDocument()
  })

  it('has a default accessible name', () => {
    render(<DataTable columns={columns} rows={[{ id: 1, name: 'A', hours: 1 }]} rowKey="id" />)
    expect(screen.getByRole('region', { name: 'Data table' })).toBeInTheDocument()
  })

  it('shows loading, error (with retry) and empty states instead of a table', () => {
    const { rerender } = render(<DataTable columns={columns} rows={null} rowKey="id" loading />)
    expect(screen.getByRole('status')).toBeInTheDocument()
    rerender(
      <DataTable
        columns={columns}
        rows={null}
        rowKey="id"
        error={new Error('Server said no')}
        onRetry={() => {}}
      />,
    )
    expect(screen.getByText('Server said no')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Try again' })).toBeInTheDocument()
    rerender(
      <DataTable columns={columns} rows={[]} rowKey="id" emptyTitle="Nothing here" emptyMessage="Add one." />,
    )
    expect(screen.getByText('Nothing here')).toBeInTheDocument()
    expect(screen.queryByRole('table')).not.toBeInTheDocument()
  })
})
