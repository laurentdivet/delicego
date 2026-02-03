// Client API public (sans clé interne)
// Consomme /api/impact/* via le proxy Vite.

export type ErreurApi = {
  statut_http: number
  message: string
}

// ==============================
// Impact (pilotage) – lecture seule (public / DEV only côté backend)
// ==============================

export type ImpactDashboardKpis = {
  days: number
  waste_rate: number
  local_share: number
  co2_kgco2e: number
}

export type ImpactDashboardAction = {
  id: string
  status: string
  description?: string | null
  assignee?: string | null
  due_date?: string | null
  priority?: number | null
  created_at?: string | null
  updated_at?: string | null
}

export type ImpactDashboardRecommendation = {
  id: string
  code: string
  severity: string
  status: string
  occurrences: number
  last_seen_at: string
  entities?: Record<string, unknown> | null
  actions: ImpactDashboardAction[]
}

export type ImpactDashboardAlert = {
  key: string
  severity: string
  title: string
  message: string
  metric: string
  value: number
  threshold: number
  days: number
  period_end: string
}

export type ImpactDashboardResponse = {
  kpis: ImpactDashboardKpis
  alerts: ImpactDashboardAlert[]
  recommendations: ImpactDashboardRecommendation[]
  trends?: {
    waste_rate: { series: { date: string; value: number }[]; delta_pct?: number | null; delta_abs?: number | null }
    local_share: { series: { date: string; value: number }[]; delta_pct?: number | null; delta_abs?: number | null }
    co2_kg: { series: { date: string; value: number }[]; delta_pct?: number | null; delta_abs?: number | null }
  } | null
  top_causes?: {
    waste: {
      ingredients: { id: string; label: string; value: number }[]
      menus: { id: string; label: string; value: number }[]
    }
    local: {
      fournisseurs: { id: string; nom: string; value: number }[]
    }
    co2: {
      ingredients: { id: string; label: string; value_kgco2e: number }[]
      fournisseurs: { id: string; nom: string; value: number }[]
    }
  } | null
}

// ==============================
// Impact (pilotage) – write (public / DEV only côté backend)
// ==============================

export type ImpactActionCreateRequest = {
  action_type: string
  description?: string | null
  assignee?: string | null
  due_date?: string | null
  priority?: 1 | 2 | 3 | null
}

export type ImpactActionResponse = {
  id: string
  recommendation_event_id: string
  action_type: string
  description?: string | null
  status: string
  created_at: string
  updated_at?: string | null
  assignee?: string | null
  due_date?: string | null
  priority?: number | null
}

export type ImpactActionPatchRequest = {
  status?: 'OPEN' | 'DONE' | 'CANCELLED'
  description?: string | null
  assignee?: string | null
  due_date?: string | null
  priority?: 1 | 2 | 3 | null
}

export type ImpactRecommendationStatusUpdateRequest = {
  status?: 'OPEN' | 'ACKNOWLEDGED' | 'RESOLVED'
  comment?: string | null
}

async function lireErreur(reponse: Response): Promise<string> {
  try {
    const data = await reponse.json()
    if (data?.detail) return String(data.detail)
    return JSON.stringify(data)
  } catch {
    return await reponse.text()
  }
}

async function requeteJson<T>(path: string, options?: RequestInit): Promise<T> {
  const reponse = await fetch(path, {
    ...options,
    headers: {
      'Content-Type': 'application/json',
      ...(options?.headers || {}),
    },
  })

  if (!reponse.ok) {
    const message = await lireErreur(reponse)
    throw { statut_http: reponse.status, message } satisfies ErreurApi
  }

  return (await reponse.json()) as T
}

export async function lireImpactDashboardPublic(params?: {
  days?: number
  compare_days?: number | null
  limit?: number
  magasin_id?: string | null
  status?: 'OPEN' | 'ACKNOWLEDGED' | 'RESOLVED' | null
  severity?: 'LOW' | 'MEDIUM' | 'HIGH' | null
  sort?: 'last_seen_desc' | 'occurrences_desc' | null
}): Promise<ImpactDashboardResponse> {
  const qs = new URLSearchParams()
  if (params?.days != null) qs.set('days', String(params.days))
  if (params?.compare_days != null) qs.set('compare_days', String(params.compare_days))
  if (params?.limit != null) qs.set('limit', String(params.limit))
  if (params?.magasin_id) qs.set('magasin_id', String(params.magasin_id))
  if (params?.status) qs.set('status', String(params.status))
  if (params?.severity) qs.set('severity', String(params.severity))
  if (params?.sort) qs.set('sort', String(params.sort))
  const suffix = qs.toString() ? `?${qs.toString()}` : ''
  return requeteJson<ImpactDashboardResponse>(`/api/impact/dashboard${suffix}`)
}

export async function creerImpactActionPublic(
  recommendation_event_id: string,
  payload: ImpactActionCreateRequest
): Promise<ImpactActionResponse> {
  return requeteJson<ImpactActionResponse>(
    `/api/impact/recommendations/${encodeURIComponent(recommendation_event_id)}/actions`,
    {
      method: 'POST',
      body: JSON.stringify(payload),
    }
  )
}

export async function patchImpactActionPublic(
  action_id: string,
  payload: ImpactActionPatchRequest
): Promise<ImpactActionResponse> {
  return requeteJson<ImpactActionResponse>(`/api/impact/actions/${encodeURIComponent(action_id)}`, {
    method: 'PATCH',
    body: JSON.stringify(payload),
  })
}

export async function patchImpactRecommendationPublic(
  recommendation_event_id: string,
  payload: ImpactRecommendationStatusUpdateRequest
): Promise<unknown> {
  return requeteJson<unknown>(`/api/impact/recommendations/${encodeURIComponent(recommendation_event_id)}`, {
    method: 'PATCH',
    body: JSON.stringify(payload),
  })
}
