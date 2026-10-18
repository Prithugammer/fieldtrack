import { EmptyState, ErrorState, LoadingState } from './States'

/**
 * Column-config driven table.
 *
 *   <DataTable
 *     columns={[
 *       { key: 'title', header: 'Job' },
 *       { key: 'crew', header: 'Crew', align: 'right', render: (row) => `${row.a}/${row.b}` },
 *     ]}
 *     rows={jobs} rowKey="job_id" loading={loading}
 *     emptyTitle="No jobs" rowClassName={(row) => row.flagged ? 'row-flagged' : ''}
 *   />
 */
export default function DataTable({
  columns,
  rows,
  rowKey,
  loading,
  error,
  onRetry,
  emptyTitle = 'No records found',
  emptyMessage,
  rowClassName,
  footer,
  label = 'Data table',
}) {
  if (loading && !rows) return <LoadingState />
  if (error) return <ErrorState message={error.message} onRetry={onRetry} />
  if (!rows || rows.length === 0) return <EmptyState title={emptyTitle} message={emptyMessage} />

  return (
    // A horizontally scrollable area must be reachable by keyboard (WCAG 2.1.1), so it is focusable
    // and named; on a phone a wide table scrolls inside this box instead of widening the page.
    <div
      className="table-wrap"
      tabIndex={0}
      role="region"
      aria-label={label}
      aria-busy={loading || undefined}
    >
      <table className="table">
        <thead>
          <tr>
            {columns.map((col) => (
              <th
                key={col.key}
                className={col.align === 'right' ? 'align-right' : undefined}
                style={col.width ? { width: col.width } : undefined}
              >
                {col.header}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row[rowKey]} className={rowClassName ? rowClassName(row) : undefined}>
              {columns.map((col) => (
                <td key={col.key} className={col.align === 'right' ? 'align-right' : undefined}>
                  {col.render ? col.render(row) : (row[col.key] ?? '—')}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
        {footer && <tfoot>{footer}</tfoot>}
      </table>
    </div>
  )
}
