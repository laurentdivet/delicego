import { Navigate, Outlet, useLocation } from 'react-router-dom'

import { lireSession, fournirTokenInterne } from './auth'

function boolEnv(v: unknown): boolean {
  return String(v || '').trim().toLowerCase() === '1' || String(v || '').trim().toLowerCase() === 'true'
}

function useInternalApi(): boolean {
  return boolEnv(import.meta.env.VITE_USE_INTERNAL_API)
}

export function ProtectedRoute() {
  const location = useLocation()
  const internal = useInternalApi()

  // Mode API interne: on protège par présence du token interne.
  if (internal) {
    const t = (fournirTokenInterne() || '').trim()
    if (!t) {
      return <Navigate to="/login" replace state={{ from: location.pathname }} />
    }
    return <Outlet />
  }

  // Mode standard: protection JWT (si implémenté).
  const session = lireSession()

  if (!session) {
    return <Navigate to="/login" replace state={{ from: location.pathname }} />
  }

  return <Outlet />
}
