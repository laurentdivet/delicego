// API Step14: forecast vs actual (read-only)

// NOTE: on réutilise le helper privé `requeteJson` via une fonction locale (copie minimale)
// pour éviter de refactorer tout `interne.ts` en exportant requeteJson.

export type ErreurApi = {
  statut_http: number
  message: string
}

function construireUrl(path: string): string {
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

  const reponse = await fetch(url, {
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

export type ForecastActualPoint = {
  date: string
  store_id: string
  forecast_total_amount: number
  actual_total_amount: number
  abs_diff: number
  pct_diff?: number | null
}

export type ForecastVsActualKpis = {
  accuracy_pct?: number | null
  mape_pct?: number | null
  days_over_threshold: number
}

export type ForecastVsActualResponse = {
  points: ForecastActualPoint[]
  kpis: ForecastVsActualKpis
}

export async function lireForecastVsActual(params: {
  store_id?: string | null
  date_from: string
  date_to?: string | null
  horizon?: number | null
}): Promise<ForecastVsActualResponse> {
  const qs = new URLSearchParams({ date_from: params.date_from })
  if (params.store_id) qs.set('store_id', params.store_id)
  if (params.date_to) qs.set('date_to', params.date_to)
  if (params.horizon != null) qs.set('horizon', String(params.horizon))
  return requeteJson<ForecastVsActualResponse>(`/api/interne/monitoring/forecast-vs-actual?${qs.toString()}`)
}
