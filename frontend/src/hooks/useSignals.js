import { useState, useEffect } from 'react'
import axios from 'axios'

// Relative on purpose -- see the same note in services/api.js. Routes
// through Vite's dev-server proxy so this works from any host the page
// was loaded from (localhost, home wifi, Tailscale) with no changes.
const API_BASE = import.meta.env.VITE_API_URL || ''

export function useSignals() {
  const [signals, setSignals] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  useEffect(() => {
    let cancelled = false
    const load = () => {
      // This used to call '/api/screener/signals/', a path that has never
      // been registered in urls.py -- it 404'd on every load, the catch
      // block swallowed it, and the component was permanently stuck
      // showing 8 hardcoded demo rows (NESTLEIND/BAJAJ-AUTO/TVSMOTOR/...)
      // no matter what the market was actually doing.
      axios.get(`${API_BASE}/api/signals/`)
        .then(r => {
          if (cancelled) return
          const data = r.data
          const arr = Array.isArray(data) ? data
            : Array.isArray(data.signals) ? data.signals
            : Array.isArray(data.results) ? data.results
            : []
          setSignals(arr)
          setError(null)
        })
        .catch((e) => {
          if (cancelled) return
          setError(e.message || 'Failed to load signals')
        })
        .finally(() => { if (!cancelled) setLoading(false) })
    }
    load()
    const interval = setInterval(load, 15000)
    return () => { cancelled = true; clearInterval(interval) }
  }, [])

  return { signals, loading, error }
}