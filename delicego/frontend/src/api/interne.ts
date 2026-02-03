// Client API interne : consomme /api/interne via le proxy Vite.
// NB: en prod, on pourra remplacer par un vrai mécanisme d'auth.

export type ErreurApi = {
  statut_http: number
  message: string
}

// ==============================
// Impact (pilotage) – lecture seule
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
}

export type ImpactActionCreateRequest = {
  action_type: string
  description?: string | null
  // created_by / expected_impact / status existent côté backend mais non requis pour l'UX simple
}

export type ImpactActionResponse = {
  id: string
  recommendation_event_id: string
  action_type: string
  description?: string | null
  status: string
  created_at: string
}

export type ImpactActionPatchRequest = {
  status?: 'OPEN' | 'DONE' | 'CANCELLED'
  description?: string | null
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
}

export async function lireImpactDashboard(params?: {
  days?: number
  limit?: number
  magasin_id?: string | null
  status?: 'OPEN' | 'ACKNOWLEDGED' | 'RESOLVED' | null
  severity?: 'LOW' | 'MEDIUM' | 'HIGH' | null
  sort?: 'last_seen_desc' | 'occurrences_desc' | null
}): Promise<ImpactDashboardResponse> {
  const qs = new URLSearchParams()
  if (params?.days != null) qs.set('days', String(params.days))
  if (params?.limit != null) qs.set('limit', String(params.limit))
  if (params?.magasin_id) qs.set('magasin_id', String(params.magasin_id))
  if (params?.status) qs.set('status', String(params.status))
  if (params?.severity) qs.set('severity', String(params.severity))
  if (params?.sort) qs.set('sort', String(params.sort))
  const suffix = qs.toString() ? `?${qs.toString()}` : ''
  return requeteJson<ImpactDashboardResponse>(`/api/interne/impact/dashboard${suffix}`)
}

// ==============================
// Magasins (liste pour UI)
// ==============================

export type MagasinListItem = {
  id: string
  nom: string
}

export async function lireMagasins(): Promise<MagasinListItem[]> {
  return requeteJson<MagasinListItem[]>('/api/interne/magasins')
}

export async function creerImpactAction(
  recommendation_event_id: string,
  payload: ImpactActionCreateRequest
): Promise<ImpactActionResponse> {
  return requeteJson<ImpactActionResponse>(`/api/interne/impact/recommendations/${encodeURIComponent(recommendation_event_id)}/actions`, {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

export async function patchImpactAction(action_id: string, payload: ImpactActionPatchRequest): Promise<ImpactActionResponse> {
  return requeteJson<ImpactActionResponse>(`/api/interne/impact/actions/${encodeURIComponent(action_id)}`, {
    method: 'PATCH',
    body: JSON.stringify(payload),
  })
}

export async function patchImpactRecommendation(
  recommendation_event_id: string,
  payload: ImpactRecommendationStatusUpdateRequest
): Promise<unknown> {
  return requeteJson<unknown>(`/api/interne/impact/recommendations/${encodeURIComponent(recommendation_event_id)}`, {
    method: 'PATCH',
    body: JSON.stringify(payload),
  })
}

function lireToken(): string | null {
  // Token minimal pour l'API interne (saisi via l'UI "Accès interne")
  return localStorage.getItem('INTERNAL_TOKEN')
}

function construireUrl(path: string): string {
  // Toujours relatif (proxy Vite en dev, même domaine en prod)
  return path
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
  const url = construireUrl(path)
  const token = lireToken()

  const reponse = await fetch(url, {
    ...options,
    headers: {
      'Content-Type': 'application/json',
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...(options?.headers || {}),
    },
  })

  if (!reponse.ok) {
    const message = await lireErreur(reponse)
    throw { statut_http: reponse.status, message } satisfies ErreurApi
  }

  return (await reponse.json()) as T
}

export type VueGlobaleDashboard = {
  date: string
  commandes_du_jour: number
  productions_du_jour: number
  quantite_produite: number
  alertes: {
    stocks_bas: number
    lots_proches_dlc: number
  }
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

export async function lireConsommation(date_debut: string, date_fin: string): Promise<ConsommationIngredient[]> {
  const qs = new URLSearchParams({ date_debut, date_fin })
  return requeteJson<ConsommationIngredient[]>(`/api/interne/dashboard/consommation?${qs.toString()}`)
}

export type StatutKPI = {
  niveau: 'vert' | 'orange' | 'rouge'
  message?: string | null
}

export type KPITendance = {
  valeur: number
  variation_pct?: number | null
}

export type KPIDashboardInpulse = {
  date_cible: string
  ca_jour: KPITendance
  ca_semaine: KPITendance
  ca_mois: KPITendance
  ecart_vs_prevision_pct?: number | null
  food_cost_reel_pct?: number | null
  marge_brute_eur?: number | null
  marge_brute_pct?: number | null
  pertes_gaspillage_eur?: number | null
  ruptures_produits_nb: number
  ruptures_impact_eur?: number | null
  heures_economisees?: number | null
}

export type DashboardExecutif = {
  magasin_id?: string | null
  date_cible: string
  kpis: KPIDashboardInpulse
  statuts: Record<string, StatutKPI>
  alertes: string[]
}

export async function lireDashboardExecutif(date_cible: string, magasin_id?: string | null): Promise<DashboardExecutif> {
  const qs = new URLSearchParams({ date_cible })
  if (magasin_id) qs.set('magasin_id', magasin_id)
  return requeteJson<DashboardExecutif>(`/api/interne/kpis/dashboard-executif?${qs.toString()}`)
}

export type PointHoraireVentes = {
  heure: number
  quantite_prevue: number
  quantite_reelle: number
  ecart_quantite: number
  ca_prevu: number
  ca_reel: number
  ecart_ca: number
}

export type LignePrevisionProduit = {
  menu_id: string
  menu_nom: string
  quantite_prevue: number
  quantite_vendue: number
  ecart_quantite: number
  ca_prevu: number
  ca_reel: number
  ecart_ca: number
  impact_meteo_pct?: number | null
  impact_jour_ferie_pct?: number | null
}

export type FiabiliteModele = {
  wape_ca_pct?: number | null
  mape_ca_pct?: number | null
  fiabilite_ca_pct?: number | null
}

export type PrevisionVentes = {
  magasin_id?: string | null
  date_cible: string
  ca_prevu: number
  ca_reel: number
  ecart_ca: number
  quantite_prevue: number
  quantite_reelle: number
  ecart_quantite: number
  fiabilite: FiabiliteModele
  courbe_horaire: PointHoraireVentes[]
  table_produits: LignePrevisionProduit[]
  facteurs: {
    meteo_active: boolean
    jour_ferie_active: boolean
  }
}

export async function lirePrevisionVentes(date_cible: string, magasin_id?: string | null): Promise<PrevisionVentes> {
  const qs = new URLSearchParams({ date_cible })
  if (magasin_id) qs.set('magasin_id', magasin_id)
  return requeteJson<PrevisionVentes>(`/api/interne/previsions/ventes?${qs.toString()}`)
}

export type ReponseGenererBesoins = { commandes_ids: string[] }

export async function genererBesoins(magasin_id: string, date_cible: string, horizon: number): Promise<ReponseGenererBesoins> {
  return requeteJson<ReponseGenererBesoins>('/api/interne/achats/besoins/generer', {
    method: 'POST',
    body: JSON.stringify({ magasin_id, date_cible, horizon }),
  })
}

// ==============================
// Production & Préparation – Cuisine (opérationnel)
// ==============================

export type StatutCuisine = 'A_PRODUIRE' | 'PRODUIT' | 'AJUSTE' | 'NON_PRODUIT'

export type QuantiteCreneau = {
  debut: string
  fin: string
  quantite: number
}

export type LigneCuisine = {
  recette_id: string
  recette_nom: string
  quantite_planifiee: number
  quantite_produite: number
  statut: StatutCuisine
}

export type LectureProductionPreparation = {
  quantites_a_produire_aujourdhui: number
  quantites_par_creneau: QuantiteCreneau[]
  cuisine: LigneCuisine[]
}

export async function lireProductionPreparation(magasin_id: string, date: string): Promise<LectureProductionPreparation> {
  const qs = new URLSearchParams({ magasin_id, date })
  return requeteJson<LectureProductionPreparation>(`/api/interne/production-preparation?${qs.toString()}`)
}

export async function actionProduit(magasin_id: string, date: string, recette_id: string): Promise<{ status: string }> {
  return requeteJson<{ status: string }>('/api/interne/production-preparation/produit', {
    method: 'POST',
    body: JSON.stringify({ magasin_id, date, recette_id }),
  })
}

export async function actionAjuste(
  magasin_id: string,
  date: string,
  recette_id: string,
  quantite: number
): Promise<{ status: string }> {
  return requeteJson<{ status: string }>('/api/interne/production-preparation/ajuste', {
    method: 'POST',
    body: JSON.stringify({ magasin_id, date, recette_id, quantite }),
  })
}

export async function actionNonProduit(magasin_id: string, date: string, recette_id: string): Promise<{ status: string }> {
  return requeteJson<{ status: string }>('/api/interne/production-preparation/non-produit', {
    method: 'POST',
    body: JSON.stringify({ magasin_id, date, recette_id }),
  })
}

export type EvenementTraceabilite = {
  type: 'PRODUIT' | 'AJUSTE' | 'NON_PRODUIT'
  date_heure: string
  quantite: number | null
  lot_production_id: string | null
}

export type TraceabiliteProductionPreparation = {
  evenements: EvenementTraceabilite[]
}

export async function lireTraceabilite(magasin_id: string, date: string, recette_id: string): Promise<TraceabiliteProductionPreparation> {
  const qs = new URLSearchParams({ magasin_id, date, recette_id })
  return requeteJson<TraceabiliteProductionPreparation>(`/api/interne/production-preparation/traceabilite?${qs.toString()}`)
}

// ==============================
// Production (scan gencode)
// ==============================

export type LigneProductionScan = {
  id: string
  produit_nom: string
  a_produire: number
  produit: number
  restant: number
}

export type ReponseScanGencode = {
  ligne: LigneProductionScan
}

export async function scannerGencodeProduction(
  gencode: string,
  magasin_id: string,
  date: string
): Promise<ReponseScanGencode> {
  return requeteJson<ReponseScanGencode>('/api/interne/production-preparation/scan', {
    method: 'POST',
    body: JSON.stringify({ gencode, magasin_id, date }),
  })
}

// ==============================
// Production du jour (MVP)
// ==============================

export type RequetePlanReel = {
  magasin_id: string
  date_plan: string
  fenetre_jours?: number
  donnees_meteo?: Record<string, number>
  evenements?: string[]
}

export type ReponsePlanReel = {
  plan_production_id: string
}

export type BesoinIngredient = {
  ingredient_id: string
  ingredient_nom: string
  quantite: number
  unite: string
}

export type ReponseBesoins = {
  plan_production_id: string
  besoins: BesoinIngredient[]
}

export async function creerPlanReel(requete: RequetePlanReel): Promise<ReponsePlanReel> {
  return requeteJson<ReponsePlanReel>('/api/interne/production/plan-reel', {
    method: 'POST',
    body: JSON.stringify(requete),
  })
}

export async function lireBesoins(plan_production_id: string): Promise<ReponseBesoins> {
  const qs = new URLSearchParams({ plan_production_id })
  return requeteJson<ReponseBesoins>(`/api/interne/production/besoins?${qs.toString()}`)
}

// ==============================
// Production du jour (end-to-end)
// ==============================

export type LigneProductionDuJour = {
  recette_id: string
  quantite_a_produire: number
}

export type RequeteProductionDuJour = {
  magasin_id: string
  date_jour: string
  lignes: LigneProductionDuJour[]
}

export type ReponseProductionDuJour = {
  plan_id: string
  lots_crees: number
  consommations_creees: number
  mouvements_stock_crees: number
  besoins?: BesoinIngredient[] | null
  warnings?: string[] | null
}

export async function executerProductionDuJour(requete: RequeteProductionDuJour): Promise<ReponseProductionDuJour> {
  return requeteJson<ReponseProductionDuJour>('/api/interne/operations/production-du-jour', {
    method: 'POST',
    body: JSON.stringify(requete),
  })
}
