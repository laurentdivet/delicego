// Client API interne : consomme /api/interne via le proxy Vite.
// NB: en prod, on pourra remplacer par un vrai mécanisme d'auth.

export type ErreurApi = {
  statut_http: number
  message: string
}

// ==============================
// Helpers env
// ==============================

function boolEnv(value: unknown): boolean {
  const s = String(value ?? '').trim().toLowerCase()
  return s === '1' || s === 'true' || s === 'yes' || s === 'on'
}

function getInternalToken(): string | null {
  const raw = (import.meta.env.VITE_INTERNAL_API_TOKEN as string | undefined) ?? ''
  const token = raw.trim()
  return token ? token : null
}

function buildHeaders(extra?: HeadersInit): Headers {
  const headers = new Headers()

  const useInternal = boolEnv(import.meta.env.VITE_USE_INTERNAL_API)
  const token = getInternalToken()
  if (useInternal && token) {
    headers.set('X-CLE-INTERNE', token)
  }

  // extra en dernier pour permettre d'écraser X-CLE-INTERNE si besoin
  if (extra) {
    new Headers(extra).forEach((value, key) => headers.set(key, value))
  }

  return headers
}

function buildUrl(path: string): string {
  const base = String((import.meta.env.VITE_API_BASE_URL as string | undefined) ?? '').trim()
  if (!base) return path
  if (path.startsWith('http')) return path

  const baseNoSlash = base.endsWith('/') ? base.slice(0, -1) : base
  const pathNoSlash = path.startsWith('/') ? path : `/${path}`
  return `${baseNoSlash}${pathNoSlash}`
}

function erreurApiFrom(status: number, text: string): ErreurApi {
  let message = text
  try {
    const maybe = JSON.parse(text)
    if (maybe?.detail) {
      message = typeof maybe.detail === 'string' ? maybe.detail : JSON.stringify(maybe.detail)
    } else if (maybe?.message) {
      message = String(maybe.message)
    } else {
      message = JSON.stringify(maybe)
    }
  } catch {
    // keep raw text
  }
  return { statut_http: status, message }
}

async function requeteJson<T>(path: string, options?: RequestInit): Promise<T> {
  const url = buildUrl(path)
  const headers = buildHeaders(options?.headers)

  const body = options?.body
  const isFormData = typeof FormData !== 'undefined' && body instanceof FormData

  if (!headers.has('Accept')) {
    headers.set('Accept', 'application/json')
  }

  // Force content-type JSON uniquement si ce n'est pas un FormData
  if (body !== undefined && body !== null && !isFormData) {
    if (!headers.has('Content-Type')) headers.set('Content-Type', 'application/json')
  }

  const res = await fetch(url, { ...options, headers })

  if (!res.ok) {
    const text = await res.text().catch(() => '')
    const details = text || res.statusText
    throw new Error(`[${res.status}] ${path}: ${details}`)
  }

  // 204 / body vide
  if (res.status === 204) return (undefined as unknown) as T

  const text = await res.text().catch(() => '')
  if (!text) return (undefined as unknown) as T

  try {
    return JSON.parse(text) as T
  } catch {
    // Si le backend renvoie autre chose que JSON sur un endpoint typé JSON
    return (undefined as unknown) as T
  }
}

// ==============================
// Impact (pilotage) – lecture seule + actions
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

export type ImpactActionCreateRequest = {
  action_type: string
  description?: string | null
  assignee?: string | null
  due_date?: string | null // YYYY-MM-DD
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

export async function lireImpactDashboard(params?: {
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
  if (params?.compare_days !== undefined) {
    if (params.compare_days === null) qs.set('compare_days', 'null')
    else qs.set('compare_days', String(params.compare_days))
  }
  if (params?.limit != null) qs.set('limit', String(params.limit))
  if (params?.magasin_id) qs.set('magasin_id', params.magasin_id)
  if (params?.status) qs.set('status', params.status)
  if (params?.severity) qs.set('severity', params.severity)
  if (params?.sort) qs.set('sort', params.sort)

  const suffix = qs.toString() ? `?${qs.toString()}` : ''
  return requeteJson<ImpactDashboardResponse>(`/api/interne/impact/dashboard${suffix}`)
}

export type MagasinListItem = { id: string; nom: string }

export async function listerMagasins(): Promise<MagasinListItem[]> {
  return requeteJson<MagasinListItem[]>('/api/interne/magasins')
}

export async function creerImpactAction(recommendation_event_id: string, body: ImpactActionCreateRequest): Promise<ImpactActionResponse> {
  return requeteJson<ImpactActionResponse>(
    `/api/interne/impact/recommendations/${encodeURIComponent(recommendation_event_id)}/actions`,
    { method: 'POST', body: JSON.stringify(body) }
  )
}

export async function patchImpactAction(action_id: string, body: ImpactActionPatchRequest): Promise<ImpactActionResponse> {
  return requeteJson<ImpactActionResponse>(
    `/api/interne/impact/actions/${encodeURIComponent(action_id)}`,
    { method: 'PATCH', body: JSON.stringify(body) }
  )
}

export async function patchImpactRecommendation(
  recommendation_event_id: string,
  body: ImpactRecommendationStatusUpdateRequest
): Promise<unknown> {
  return requeteJson<unknown>(
    `/api/interne/impact/recommendations/${encodeURIComponent(recommendation_event_id)}`,
    { method: 'PATCH', body: JSON.stringify(body) }
  )
}

// Export CSV (fetch direct -> on met le header interne aussi)
export async function exporterImpactActionsCsv(params?: {
  days?: number
  magasin_id?: string | null
  status?: 'OPEN' | 'ACKNOWLEDGED' | 'RESOLVED' | null
  severity?: 'LOW' | 'MEDIUM' | 'HIGH' | null
  action_status?: 'OPEN' | 'DONE' | 'CANCELLED' | null
}): Promise<Blob> {
  const qs = new URLSearchParams()
  if (params?.days != null) qs.set('days', String(params.days))
  if (params?.magasin_id) qs.set('magasin_id', params.magasin_id)
  if (params?.status) qs.set('status', params.status)
  if (params?.severity) qs.set('severity', params.severity)
  if (params?.action_status) qs.set('action_status', params.action_status)

  const suffix = qs.toString() ? `?${qs.toString()}` : ''
  const url = buildUrl(`/api/interne/impact/export/actions.csv${suffix}`)

  const headers = buildHeaders()

  const reponse = await fetch(url, { method: 'GET', headers })
  if (!reponse.ok) {
    const text = await reponse.text().catch(() => '')
    throw erreurApiFrom(reponse.status, text || reponse.statusText)
  }
  return await reponse.blob()
}

// ==============================
// Dashboards / Prévisions / Cuisine / Achats (types minimaux)
// ==============================

export type VueGlobaleDashboard = {
  date: string
  commandes_du_jour: number
  productions_du_jour: number
  quantite_produite: number
  alertes: { stocks_bas: number; lots_proches_dlc: number }
}

export async function lireVueGlobale(date_cible: string): Promise<VueGlobaleDashboard> {
  return requeteJson<VueGlobaleDashboard>(`/api/interne/dashboard/vue-globale?date_cible=${encodeURIComponent(date_cible)}`)
}

export type ConsommationIngredient = {
  ingredient_id: string
  ingredient: string
  quantite_consommee: number
  stock_estime: number
  lots_proches_dlc: number
}

export async function lireConsommation(params: { date_debut: string; date_fin: string }): Promise<ConsommationIngredient[]> {
  const qs = new URLSearchParams(params)
  return requeteJson<ConsommationIngredient[]>(`/api/interne/dashboard/consommation?${qs.toString()}`)
}

export type DashboardExecutif = {
  magasin_id?: string | null
  date_cible: string
  kpis: unknown
  statuts: Record<string, unknown>
  alertes: string[]
}

export async function lireDashboardExecutif(params: { date_cible: string; magasin_id?: string | null }): Promise<DashboardExecutif> {
  const qs = new URLSearchParams()
  qs.set('date_cible', params.date_cible)
  if (params.magasin_id) qs.set('magasin_id', params.magasin_id)
  return requeteJson<DashboardExecutif>(`/api/interne/kpis/dashboard-executif?${qs.toString()}`)
}

export type PrevisionVentes = {
  date_cible: string
  predictions: { magasin_id: string; menu_id: string; quantite_predite: number; source?: string }[]
}

export async function lirePrevisionsVentes(params: { date_cible: string; magasin_id?: string | null; horizon?: number | null }): Promise<PrevisionVentes> {
  const qs = new URLSearchParams()
  qs.set('date_cible', params.date_cible)
  if (params.magasin_id) qs.set('magasin_id', params.magasin_id)
  if (params.horizon != null) qs.set('horizon', String(params.horizon))
  return requeteJson<PrevisionVentes>(`/api/interne/previsions/ventes?${qs.toString()}`)
}

export type ReponseGenererBesoins = { commandes_ids: string[] }

export async function genererBesoins(body: { magasin_id: string; date_cible: string; horizon?: number }): Promise<ReponseGenererBesoins> {
  return requeteJson<ReponseGenererBesoins>('/api/interne/achats/besoins/generer', {
    method: 'POST',
    body: JSON.stringify(body),
  })
}

// Cuisine / production-preparation
export type LigneCuisine = {
  recette_id: string
  recette_nom: string
  quantite_planifiee: number
  quantite_produite: number
  statut: string
}

export type LectureProductionPreparation = {
  quantites_a_produire_aujourdhui: number
  quantites_par_creneau: { debut: string; fin: string; quantite: number }[]
  cuisine: LigneCuisine[]
}

export async function lireProductionPreparation(params: { magasin_id: string; date: string }): Promise<LectureProductionPreparation> {
  const qs = new URLSearchParams(params)
  return requeteJson<LectureProductionPreparation>(`/api/interne/production-preparation?${qs.toString()}`)
}

export type TraceabiliteProductionPreparation = {
  evenements: { type: string; date_heure: string; quantite?: number | null; lot_production_id?: string | null }[]
}

export async function lireTraceabilite(params: { magasin_id: string; date: string; recette_id: string }): Promise<TraceabiliteProductionPreparation> {
  const qs = new URLSearchParams(params)
  return requeteJson<TraceabiliteProductionPreparation>(`/api/interne/production-preparation/traceabilite?${qs.toString()}`)
}

export type LigneProductionScan = { id: string; produit_nom: string; a_produire: number; produit: number; restant: number }
export type ReponseScanGencode = { ligne: LigneProductionScan }

export async function scannerGencodeProduction(body: { gencode: string; magasin_id: string; date: string }): Promise<ReponseScanGencode> {
  return requeteJson<ReponseScanGencode>('/api/interne/production-preparation/scan', {
    method: 'POST',
    body: JSON.stringify(body),
  })
}

export async function actionProduit(body: { magasin_id: string; date: string; recette_id: string }): Promise<{ status: string }> {
  return requeteJson<{ status: string }>('/api/interne/production-preparation/produit', {
    method: 'POST',
    body: JSON.stringify(body),
  })
}

export async function actionAjuste(body: { magasin_id: string; date: string; recette_id: string; quantite: number }): Promise<{ status: string }> {
  return requeteJson<{ status: string }>('/api/interne/production-preparation/ajuste', {
    method: 'POST',
    body: JSON.stringify(body),
  })
}

export async function actionNonProduit(body: { magasin_id: string; date: string; recette_id: string }): Promise<{ status: string }> {
  return requeteJson<{ status: string }>('/api/interne/production-preparation/non-produit', {
    method: 'POST',
    body: JSON.stringify(body),
  })
}

// Production du jour
export type ReponseProductionDuJour = {
  plan_id: string
  lots_crees: number
  consommations_creees: number
  mouvements_stock_crees: number
  besoins?: unknown[]
  warnings?: string[]
}

export async function produireDuJour(body: {
  magasin_id: string
  date_jour: string
  lignes: { recette_id: string; quantite_a_produire: number }[]
}): Promise<ReponseProductionDuJour> {
  return requeteJson<ReponseProductionDuJour>('/api/interne/operations/production-du-jour', {
    method: 'POST',
    body: JSON.stringify(body),
  })
}
