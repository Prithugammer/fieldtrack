import { useCallback, useEffect, useState } from 'react'
import { api } from './client'

/**
 * Load JSON from the API and track loading/error state.
 *   const { data, loading, error, reload } = useApi('/jobs', { date, status })
 * Re-fetches whenever the path or params change. Pass path = null to skip loading.
 */
export function useApi(path, params) {
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(Boolean(path))
  const [error, setError] = useState(null)
  const [version, setVersion] = useState(0)
  const paramsKey = JSON.stringify(params || {})

  useEffect(() => {
    if (!path) return undefined
    let cancelled = false
    setLoading(true)
    setError(null)
    api(path, { params: JSON.parse(paramsKey) })
      .then((result) => !cancelled && setData(result))
      .catch((err) => !cancelled && setError(err))
      .finally(() => !cancelled && setLoading(false))
    return () => {
      cancelled = true
    }
  }, [path, paramsKey, version])

  const reload = useCallback(() => setVersion((v) => v + 1), [])
  return { data, loading, error, reload }
}
