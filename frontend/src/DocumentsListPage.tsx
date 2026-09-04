import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { ApiError, fetchDocuments } from './api'
import type { DocumentListItem, SortDir, SortField } from './api'
import { useTabs } from './TabsContext'

const PAGE_SIZE = 20

const COLUMNS: { field: SortField; label: string }[] = [
  { field: 'id', label: 'ID' },
  { field: 'title', label: 'Title' },
  { field: 'youtube_video_id', label: 'YouTube Video ID' },
  { field: 'created_at', label: 'Created At' },
]

export function DocumentsListPage() {
  const navigate = useNavigate()
  const { openIds } = useTabs()

  const [page, setPage] = useState(1)
  const [sortBy, setSortBy] = useState<SortField>('created_at')
  const [sortDir, setSortDir] = useState<SortDir>('desc')

  const [items, setItems] = useState<DocumentListItem[]>([])
  const [total, setTotal] = useState(0)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setError(null)

    fetchDocuments({ page, pageSize: PAGE_SIZE, sortBy, sortDir })
      .then((result) => {
        if (cancelled) return
        setItems(result.items)
        setTotal(result.total)
      })
      .catch((err) => {
        if (cancelled) return
        setError(err instanceof ApiError ? err.message : 'Failed to load documents.')
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })

    return () => {
      cancelled = true
    }
  }, [page, sortBy, sortDir])

  function handleSort(field: SortField) {
    if (field === sortBy) {
      setSortDir((dir) => (dir === 'asc' ? 'desc' : 'asc'))
    } else {
      setSortBy(field)
      setSortDir('asc')
    }
    setPage(1)
  }

  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE))
  const columnCount = COLUMNS.length + 1

  return (
    <div className="documents-list">
      <h1>Existing Documents</h1>

      {error && <p className="form-error">{error}</p>}

      <table>
        <thead>
          <tr>
            <th aria-label="Open in a tab" />
            {COLUMNS.map(({ field, label }) => (
              <th key={field}>
                <button
                  type="button"
                  className="sort-button"
                  onClick={() => handleSort(field)}
                >
                  {label}
                  {sortBy === field ? (sortDir === 'asc' ? ' ▲' : ' ▼') : ''}
                </button>
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {!loading && items.length === 0 && (
            <tr>
              <td colSpan={columnCount} className="empty-state">
                No documents yet.
              </td>
            </tr>
          )}
          {items.map((doc) => (
            <tr
              key={doc.id}
              className="clickable-row"
              onClick={() => navigate(`/documents/${doc.id}`)}
            >
              <td className="tab-indicator">{openIds.has(doc.id) ? '👁' : ''}</td>
              <td>{doc.id}</td>
              <td>{doc.title}</td>
              <td>{doc.youtube_video_id ?? '—'}</td>
              <td>{new Date(doc.created_at).toLocaleString()}</td>
            </tr>
          ))}
        </tbody>
      </table>

      <div className="pagination">
        <button type="button" disabled={page <= 1} onClick={() => setPage((p) => p - 1)}>
          Previous
        </button>
        <span>
          Page {page} of {totalPages} ({total} total)
        </span>
        <button
          type="button"
          disabled={page >= totalPages}
          onClick={() => setPage((p) => p + 1)}
        >
          Next
        </button>
      </div>
    </div>
  )
}
