import { useCallback, useEffect, useMemo, useState } from 'react'

import {
  lireImpactDashboardPublic,
  creerImpactActionPublic,
  patchImpactActionPublic,
  patchImpactRecommendationPublic,
  type ImpactDashboardRecommendation,
  type ImpactDashboardResponse,
} from '../api/impact'

import {
  lireImpactDashboard,
  creerImpactAction,
  patchImpactAction,
  patchImpactRecommendation,
  lireMagasins,
  type MagasinListItem,
} from '../api/interne'

function boolEnv(v: unknown): boolean {
  return String(v || '').trim().toLowerCase() === '1' || String(v || '').trim().toLowerCase() === 'true'
}

function useInternalApi(): boolean {
  // En prod on peut fixer VITE_USE_INTERNAL_API=1
  return boolEnv(import.meta.env.VITE_USE_INTERNAL_API)
}

function tokenPresent(): boolean {
  return Boolean(localStorage.getItem('INTERNAL_TOKEN') || '')
}

function formatPct(n: number) {
  return `${Intl.NumberFormat('fr-FR', { maximumFractionDigits: 1 }).format(n * 100)}%`
}

function formatNombre(n: number, digits = 2) {
  return Intl.NumberFormat('fr-FR', { maximumFractionDigits: digits }).format(n)
}

function formatDateHeure(iso: string) {
  try {
    return new Date(iso).toLocaleString('fr-FR')
  } catch {
    return iso
  }
}

function badgeSeverity(severity: string): { className: string; label: string } {
  const s = (severity || '').toUpperCase()
  if (s === 'CRITICAL' || s === 'HIGH') {
    return { className: 'bg-red-100 text-red-800 border-red-200', label: s }
  }
  if (s === 'MEDIUM' || s === 'WARN' || s === 'WARNING') {
    return { className: 'bg-amber-100 text-amber-800 border-amber-200', label: s }
  }
  if (s === 'LOW' || s === 'INFO') {
    return { className: 'bg-emerald-100 text-emerald-800 border-emerald-200', label: s }
  }
  return { className: 'bg-slate-100 text-slate-700 border-slate-200', label: s || '—' }
}

function badgeStatus(status: string): { className: string; label: string } {
  const s = (status || '').toUpperCase()
  if (s === 'OPEN') return { className: 'bg-blue-100 text-blue-800 border-blue-200', label: s }
  if (s === 'ACKNOWLEDGED') return { className: 'bg-slate-200 text-slate-800 border-slate-300', label: s }
  if (s === 'RESOLVED') return { className: 'bg-emerald-100 text-emerald-800 border-emerald-200', label: s }
  if (s === 'DONE') return { className: 'bg-emerald-100 text-emerald-800 border-emerald-200', label: s }
  if (s === 'CANCELLED') return { className: 'bg-slate-200 text-slate-700 border-slate-300', label: s }
  return { className: 'bg-slate-100 text-slate-700 border-slate-200', label: s || '—' }
}

function KpiMiniCard({ titre, valeur, sousTitre }: { titre: string; valeur: string; sousTitre?: string }) {
  return (
    <div className="rounded-xl border bg-white p-4 shadow-sm">
      <div className="text-xs font-medium text-slate-500">{titre}</div>
      <div className="mt-1 text-2xl font-semibold tabular-nums">{valeur}</div>
      {sousTitre && <div className="mt-1 text-xs text-slate-500">{sousTitre}</div>}
    </div>
  )
}

function RecoActions({ r, internal }: { r: ImpactDashboardRecommendation; internal: boolean }) {
  if (!r.actions || r.actions.length === 0) {
    return <div className="text-xs text-slate-500">Aucune action</div>
  }

  return (
    <ul className="space-y-1">
      {r.actions.slice(0, 6).map((a) => (
        <li key={a.id} className="flex items-start gap-2 text-xs">
          <span className={['inline-flex items-center rounded border px-2 py-0.5 font-medium', badgeStatus(a.status).className].join(' ')}>
            {badgeStatus(a.status).label}
          </span>
          <select
            className="rounded border bg-white px-2 py-1 text-[11px]"
            value={(a.status || 'OPEN').toUpperCase()}
            onChange={async (e) => {
              const next = e.target.value as 'OPEN' | 'DONE' | 'CANCELLED'
              try {
                if (internal) {
                  await patchImpactAction(a.id, { status: next })
                } else {
                  await patchImpactActionPublic(a.id, { status: next })
                }
              } finally {
                // refresh global via event (simple)
                window.dispatchEvent(new CustomEvent('impact:refresh'))
              }
            }}
            aria-label="Statut action"
            title="Statut action"
          >
            <option value="OPEN">OPEN</option>
            <option value="DONE">DONE</option>
            <option value="CANCELLED">CANCELLED</option>
          </select>
          <span className="text-slate-700">{a.description || <span className="text-slate-400">(sans description)</span>}</span>
        </li>
      ))}
      {r.actions.length > 6 && <li className="text-xs text-slate-500">… +{r.actions.length - 6} autres</li>}
    </ul>
  )
}

function Modal({ open, onClose, children }: { open: boolean; onClose: () => void; children: React.ReactNode }) {
  if (!open) return null
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/30 p-4" role="dialog" aria-modal="true">
      <div className="w-full max-w-lg rounded-xl border bg-white p-4 shadow-lg">
        {children}
        <div className="mt-4 flex justify-end">
          <button type="button" className="rounded-md border px-3 py-2 text-sm" onClick={onClose} aria-label="Fermer la modale">
            Fermer
          </button>
        </div>
      </div>
    </div>
  )
}

export function ImpactDashboard() {
  const internal = useInternalApi()
  const [days, setDays] = useState<number>(30)
  const [limit, setLimit] = useState<number>(200)

  // filtres dashboard (querystring + localStorage)
  const [magasins, setMagasins] = useState<MagasinListItem[]>([])
  const [magasinId, setMagasinId] = useState<string | null>(null)
  const [recoStatus, setRecoStatus] = useState<'OPEN' | 'ACKNOWLEDGED' | 'RESOLVED' | ''>('')
  const [recoSeverity, setRecoSeverity] = useState<'LOW' | 'MEDIUM' | 'HIGH' | ''>('')
  const [recoSort, setRecoSort] = useState<'last_seen_desc' | 'occurrences_desc'>('last_seen_desc')

  // UI "Accès interne" (pas de login): stockage local uniquement.
  const [internalTokenInput, setInternalTokenInput] = useState<string>(() => localStorage.getItem('INTERNAL_TOKEN') || '')
  const [internalTokenSavedAt, setInternalTokenSavedAt] = useState<string | null>(null)

  const [data, setData] = useState<ImpactDashboardResponse | null>(null)
  const [loading, setLoading] = useState(false)
  const [erreur, setErreur] = useState<string | null>(null)
  const [lastRefreshAt, setLastRefreshAt] = useState<string | null>(null)

  const [modalOpen, setModalOpen] = useState(false)
  const [modalRecoId, setModalRecoId] = useState<string | null>(null)
  const [newActionType, setNewActionType] = useState('MANUAL')
  const [newActionDesc, setNewActionDesc] = useState('')
  const [saving, setSaving] = useState(false)

  const [messageSucces, setMessageSucces] = useState<string | null>(null)
  const [editionDesactivee, setEditionDesactivee] = useState(false)

  // init from URL / localStorage
  useEffect(() => {
    const qs = new URLSearchParams(window.location.search)
    const qsMagasin = qs.get('magasin_id')
    const savedMagasin = localStorage.getItem('IMPACT_MAGASIN_ID')
    const initialMagasin = qsMagasin || savedMagasin
    setMagasinId(initialMagasin && initialMagasin !== 'GLOBAL' ? initialMagasin : null)

    const qsStatus = (qs.get('status') || '').toUpperCase()
    if (qsStatus === 'OPEN' || qsStatus === 'ACKNOWLEDGED' || qsStatus === 'RESOLVED') setRecoStatus(qsStatus)
    const qsSeverity = (qs.get('severity') || '').toUpperCase()
    if (qsSeverity === 'LOW' || qsSeverity === 'MEDIUM' || qsSeverity === 'HIGH') setRecoSeverity(qsSeverity)
    const qsSort = (qs.get('sort') || '').toLowerCase()
    if (qsSort === 'occurrences_desc' || qsSort === 'last_seen_desc') setRecoSort(qsSort)
  }, [])

  // load magasins for internal mode
  useEffect(() => {
    if (!internal) return
    ;(async () => {
      try {
        const m = await lireMagasins()
        setMagasins(m)
      } catch {
        // non bloquant
        setMagasins([])
      }
    })()
  }, [internal])

  const scopeLabel = useMemo(() => {
    if (!magasinId) return 'GLOBAL'
    const m = magasins.find((x) => x.id === magasinId)
    return m ? m.nom : magasinId
  }, [magasinId, magasins])

  const syncUrlAndStorage = useCallback(
    (next: { magasin_id?: string | null; status?: string; severity?: string; sort?: string }) => {
      const qs = new URLSearchParams(window.location.search)
      if ('magasin_id' in next) {
        if (next.magasin_id) {
          qs.set('magasin_id', next.magasin_id)
          localStorage.setItem('IMPACT_MAGASIN_ID', next.magasin_id)
        } else {
          qs.delete('magasin_id')
          localStorage.setItem('IMPACT_MAGASIN_ID', 'GLOBAL')
        }
      }
      if ('status' in next) {
        if (next.status) qs.set('status', next.status)
        else qs.delete('status')
      }
      if ('severity' in next) {
        if (next.severity) qs.set('severity', next.severity)
        else qs.delete('severity')
      }
      if ('sort' in next) {
        if (next.sort) qs.set('sort', next.sort)
        else qs.delete('sort')
      }
      const url = `${window.location.pathname}${qs.toString() ? `?${qs.toString()}` : ''}`
      window.history.replaceState({}, '', url)
    },
    []
  )

  const charger = useCallback(async () => {
    setLoading(true)
    setErreur(null)
    setMessageSucces(null)
    try {
      const params = {
        days,
        limit,
        magasin_id: magasinId,
        status: recoStatus || null,
        severity: recoSeverity || null,
        sort: recoSort || null,
      } as const
      const d = internal ? await lireImpactDashboard(params) : await lireImpactDashboardPublic(params)
      setData(d)
      setLastRefreshAt(new Date().toISOString())
      setEditionDesactivee(false)
    } catch (e: unknown) {
      const err = e as { statut_http?: number; message?: string }
      if (internal && err?.statut_http === 401) {
        setErreur('Token invalide ou absent')
        setEditionDesactivee(true)
      } else {
        const msg = err?.message || 'Erreur de chargement (impact dashboard)'
        setErreur(msg)
        // Public: 403 si guard DEV-only off. Interne: 401 si token absent/invalid.
        setEditionDesactivee(
          msg.includes('403') ||
            msg.includes('401') ||
            msg.toLowerCase().includes('désactivé') ||
            msg.toLowerCase().includes('forbidden') ||
            msg.toLowerCase().includes('token')
        )
      }
    } finally {
      setLoading(false)
    }
  }, [days, limit, magasinId, recoStatus, recoSeverity, recoSort, internal])

  useEffect(() => {
    charger()
  }, [charger])

  useEffect(() => {
    const handler = () => charger()
    window.addEventListener('impact:refresh', handler as EventListener)
    return () => window.removeEventListener('impact:refresh', handler as EventListener)
  }, [charger])

  const counts = useMemo(() => {
    const bySeverity: Record<string, number> = {}
    for (const r of data?.recommendations || []) {
      const k = (r.severity || '—').toUpperCase()
      bySeverity[k] = (bySeverity[k] || 0) + 1
    }
    return bySeverity
  }, [data])

  return (
    <div className="space-y-6">
      {internal && (
        <div className="rounded-xl border bg-white p-4 shadow-sm">
          <div className="flex flex-col gap-2 md:flex-row md:items-end md:justify-between">
            <div>
              <div className="text-sm font-semibold">Accès interne</div>
              <div className="text-xs text-slate-500">
                Cette page utilise <span className="font-mono">/api/interne/impact/*</span>. Saisis un token Bearer pour accéder.
              </div>
            </div>

            <div className="flex flex-col gap-2 md:flex-row md:items-end">
              <div>
                <label className="block text-xs font-medium text-slate-600">Token</label>
                <input
                  type="password"
                  className="mt-1 w-80 max-w-full rounded-md border bg-white px-3 py-2 text-sm font-mono"
                  value={internalTokenInput}
                  onChange={(e) => setInternalTokenInput(e.target.value)}
                  placeholder="Bearer token…"
                  aria-label="Token interne"
                />
              </div>
              <button
                type="button"
                className="rounded-md bg-slate-900 px-4 py-2 text-sm font-semibold text-white hover:bg-slate-800"
                onClick={() => {
                  const t = internalTokenInput.trim()
                  if (!t) {
                    localStorage.removeItem('INTERNAL_TOKEN')
                  } else {
                    localStorage.setItem('INTERNAL_TOKEN', t)
                  }
                  setInternalTokenSavedAt(new Date().toISOString())
                  window.dispatchEvent(new CustomEvent('impact:refresh'))
                }}
              >
                Enregistrer
              </button>
            </div>
          </div>

          <div className="mt-2 text-xs text-slate-500">
            Statut: {tokenPresent() ? <span className="text-emerald-700">token présent</span> : <span className="text-amber-700">token manquant</span>}
            {internalTokenSavedAt ? ` • sauvegardé: ${formatDateHeure(internalTokenSavedAt)}` : ''}
          </div>
        </div>
      )}
      <div className="flex flex-col gap-3 md:flex-row md:items-end md:justify-between">
        <div>
          <h1 className="text-2xl font-semibold">Impact – Pilotage (lecture seule)</h1>
          <p className="text-sm text-slate-500">1 écran pour voir ce que DeliceGo sait aujourd’hui: KPIs, alertes, recommandations & actions.</p>
        </div>

        <div className="flex flex-col gap-3 md:flex-row md:items-end">
          <div>
            <label className="block text-xs font-medium text-slate-600">Fenêtre (jours)</label>
            <input
              type="number"
              min={7}
              max={365}
              className="mt-1 w-28 rounded-md border bg-white px-3 py-2 text-sm"
              value={days}
              onChange={(e) => setDays(Number(e.target.value || 30))}
              aria-label="Fenêtre (jours)"
            />
          </div>

          <div>
            <label className="block text-xs font-medium text-slate-600">Limite recos</label>
            <input
              type="number"
              min={1}
              max={1000}
              className="mt-1 w-28 rounded-md border bg-white px-3 py-2 text-sm"
              value={limit}
              onChange={(e) => setLimit(Number(e.target.value || 200))}
              aria-label="Limite recommandations"
            />
          </div>

          <button
            type="button"
            onClick={charger}
            className="rounded-md bg-slate-900 px-4 py-2 text-sm font-semibold text-white hover:bg-slate-800"
          >
            {loading ? 'Rafraîchissement…' : 'Rafraîchir'}
          </button>
        </div>
      </div>

      {editionDesactivee && (
        <div className="rounded border border-amber-200 bg-amber-50 p-3 text-sm text-amber-900">
          {internal ? (
            <>
              Accès interne requis. Vérifie que tu as saisi le bon token et que le backend a <span className="font-mono">INTERNAL_API_TOKEN</span>.
            </>
          ) : (
            <>
              Édition désactivée. Active <span className="font-mono">IMPACT_DASHBOARD_PUBLIC_DEV=1</span> côté backend.
            </>
          )}
        </div>
      )}
      {messageSucces && <div className="rounded border border-emerald-200 bg-emerald-50 p-3 text-sm text-emerald-800">{messageSucces}</div>}
      {erreur && <div className="rounded border border-red-200 bg-red-50 p-3 text-sm text-red-700">{erreur}</div>}

      <div className="rounded-xl border bg-white p-3 shadow-sm">
        <div className="flex flex-col gap-2 md:flex-row md:items-center md:justify-between">
          <div className="text-sm font-semibold">Résumé</div>
          <div className="text-xs text-slate-500">
            API: {internal ? '/api/interne/impact/dashboard' : '/api/impact/dashboard'} • {loading ? 'Mise à jour…' : lastRefreshAt ? `Dernier refresh: ${formatDateHeure(lastRefreshAt)}` : '—'}
          </div>
        </div>

        <div className="mt-2 flex flex-col gap-2 md:flex-row md:items-end md:justify-between">
          <div className="text-xs text-slate-600">
            Scope: <span className="font-semibold">{scopeLabel}</span>
          </div>

          <div className="flex flex-col gap-2 md:flex-row md:items-end">
            <div>
              <label className="block text-xs font-medium text-slate-600">Magasin</label>
              <select
                className="mt-1 w-56 rounded-md border bg-white px-3 py-2 text-sm disabled:opacity-60"
                value={magasinId || ''}
                disabled={!internal}
                onChange={(e) => {
                  const next = e.target.value || null
                  setMagasinId(next)
                  syncUrlAndStorage({ magasin_id: next })
                  window.dispatchEvent(new CustomEvent('impact:refresh'))
                }}
                aria-label="Magasin"
                title={internal ? 'Filtrer par magasin' : 'Disponible uniquement en mode interne'}
              >
                <option value="">GLOBAL</option>
                {magasins.map((m) => (
                  <option key={m.id} value={m.id}>
                    {m.nom}
                  </option>
                ))}
              </select>
              {!internal && <div className="mt-1 text-[11px] text-slate-500">Le filtre magasin est disponible en mode API interne.</div>}
            </div>

            <div>
              <label className="block text-xs font-medium text-slate-600">Statut</label>
              <select
                className="mt-1 w-40 rounded-md border bg-white px-3 py-2 text-sm"
                value={recoStatus}
                aria-label="Filtre statut recommandations"
                title="Filtrer par statut"
                onChange={(e) => {
                  const v = (e.target.value || '') as typeof recoStatus
                  setRecoStatus(v)
                  syncUrlAndStorage({ status: v || '' })
                  window.dispatchEvent(new CustomEvent('impact:refresh'))
                }}
              >
                <option value="">Tous</option>
                <option value="OPEN">OPEN</option>
                <option value="ACKNOWLEDGED">ACK</option>
                <option value="RESOLVED">RESOLVED</option>
              </select>
            </div>

            <div>
              <label className="block text-xs font-medium text-slate-600">Sévérité</label>
              <select
                className="mt-1 w-40 rounded-md border bg-white px-3 py-2 text-sm"
                value={recoSeverity}
                aria-label="Filtre sévérité recommandations"
                title="Filtrer par sévérité"
                onChange={(e) => {
                  const v = (e.target.value || '') as typeof recoSeverity
                  setRecoSeverity(v)
                  syncUrlAndStorage({ severity: v || '' })
                  window.dispatchEvent(new CustomEvent('impact:refresh'))
                }}
              >
                <option value="">Toutes</option>
                <option value="LOW">LOW</option>
                <option value="MEDIUM">MEDIUM</option>
                <option value="HIGH">HIGH</option>
              </select>
            </div>

            <div>
              <label className="block text-xs font-medium text-slate-600">Tri</label>
              <select
                className="mt-1 w-56 rounded-md border bg-white px-3 py-2 text-sm"
                value={recoSort}
                aria-label="Tri recommandations"
                title="Trier les recommandations"
                onChange={(e) => {
                  const v = (e.target.value || 'last_seen_desc') as typeof recoSort
                  setRecoSort(v)
                  syncUrlAndStorage({ sort: v })
                  window.dispatchEvent(new CustomEvent('impact:refresh'))
                }}
              >
                <option value="last_seen_desc">Dernier vu</option>
                <option value="occurrences_desc">Occurrences</option>
              </select>
            </div>
          </div>
        </div>

        <div className="mt-2 flex flex-wrap gap-2">
          {Object.keys(counts).length === 0 && <div className="text-sm text-slate-500">Aucune recommandation.</div>}
          {Object.entries(counts)
            .sort((a, b) => b[1] - a[1])
            .map(([sev, n]) => (
              <div key={sev} className={['inline-flex items-center gap-2 rounded-full border px-3 py-1 text-xs', badgeSeverity(sev).className].join(' ')}>
                <span className="font-semibold">{sev}</span>
                <span className="tabular-nums">{n}</span>
              </div>
            ))}
        </div>
      </div>

      {/* KPIs (3 cartes) */}
      <div className="grid gap-4 md:grid-cols-3">
        <KpiMiniCard
          titre="Taux de gaspillage"
          valeur={data ? formatPct(data.kpis.waste_rate) : loading ? '…' : '—'}
          sousTitre={data ? `${data.kpis.days} jours` : undefined}
        />
        <KpiMiniCard
          titre="Part locale"
          valeur={data ? formatPct(data.kpis.local_share) : loading ? '…' : '—'}
          sousTitre={data ? `${data.kpis.days} jours` : undefined}
        />
        <KpiMiniCard
          titre="CO₂ estimé"
          valeur={data ? `${formatNombre(data.kpis.co2_kgco2e, 0)} kgCO₂e` : loading ? '…' : '—'}
          sousTitre={data ? `${data.kpis.days} jours` : undefined}
        />
      </div>

      {/* Alertes */}
      <div className="rounded-xl border bg-white p-4 shadow-sm">
        <div className="mb-3 flex items-center justify-between">
          <div>
            <div className="text-sm font-semibold">Alertes</div>
            <div className="text-xs text-slate-500">Signaux calculés (waste/local/co2)</div>
          </div>
          <div className="text-xs text-slate-500">{data ? `${data.alerts.length} alerte(s)` : '—'}</div>
        </div>

        <div className="space-y-2">
          {(data?.alerts || []).length === 0 && <div className="text-sm text-slate-500">Aucune alerte.</div>}
          {(data?.alerts || []).slice(0, 8).map((a) => (
            <div key={a.key} className="flex flex-col gap-2 rounded-lg border bg-white p-3 md:flex-row md:items-center md:justify-between">
              <div className="min-w-0">
                <div className="flex items-center gap-2">
                  <span className={['inline-flex items-center rounded border px-2 py-0.5 text-xs font-semibold', badgeSeverity(a.severity).className].join(' ')}>
                    {badgeSeverity(a.severity).label}
                  </span>
                  <div className="truncate text-sm font-medium">{a.title}</div>
                </div>
                <div className="mt-1 text-xs text-slate-600">{a.message}</div>
              </div>
              <div className="text-xs text-slate-500 md:text-right">
                <div className="tabular-nums">
                  {a.metric}: {formatNombre(a.value)} (seuil {formatNombre(a.threshold)})
                </div>
                <div>{a.days}j • fin {formatDateHeure(a.period_end)}</div>
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* Recommandations */}
      <div className="rounded-xl border bg-white p-4 shadow-sm">
        <div className="mb-3 flex items-center justify-between">
          <div>
            <div className="text-sm font-semibold">Recommandations</div>
            <div className="text-xs text-slate-500">Historique des événements + actions associées</div>
          </div>
          <div className="text-xs text-slate-500">{data ? `${data.recommendations.length} reco(s)` : '—'}</div>
        </div>

        <div className="overflow-x-auto">
          <table className="w-full border-separate border-spacing-y-2">
            <thead>
              <tr className="text-left text-xs text-slate-500">
                <th className="px-2">Code</th>
                <th className="px-2">Sévérité</th>
                <th className="px-2">Statut</th>
                <th className="px-2 text-right">Occurrences</th>
                <th className="px-2">Dernière occurrence</th>
                <th className="px-2">Actions associées</th>
                <th className="px-2"></th>
              </tr>
            </thead>
            <tbody>
              {(data?.recommendations || []).map((r) => (
                <tr key={r.id} className="rounded-lg bg-white text-sm shadow-sm">
                  <td className="px-2 py-3 font-mono text-xs">{r.code}</td>
                  <td className="px-2 py-3">
                    <span className={['inline-flex items-center rounded border px-2 py-0.5 text-xs font-semibold', badgeSeverity(r.severity).className].join(' ')}>
                      {badgeSeverity(r.severity).label}
                    </span>
                  </td>
                  <td className="px-2 py-3">
                    <div className="flex items-center gap-2">
                      <span className={['inline-flex items-center rounded border px-2 py-0.5 text-xs font-semibold', badgeStatus(r.status).className].join(' ')}>
                        {badgeStatus(r.status).label}
                      </span>
                      <select
                        className="rounded border bg-white px-2 py-1 text-xs"
                        value={(r.status || 'OPEN').toUpperCase()}
                        onChange={async (e) => {
                          const next = e.target.value as 'OPEN' | 'ACKNOWLEDGED' | 'RESOLVED'
                          setErreur(null)
                          setMessageSucces(null)
                          setLoading(true)
                          try {
                            if (internal) {
                              await patchImpactRecommendation(r.id, { status: next })
                            } else {
                              await patchImpactRecommendationPublic(r.id, { status: next })
                            }
                            setMessageSucces('Recommandation mise à jour.')
                          } catch (err: unknown) {
                            const e2 = err as { message?: string }
                            setErreur(e2?.message || 'Erreur: mise à jour recommandation')
                          } finally {
                            setLoading(false)
                            window.dispatchEvent(new CustomEvent('impact:refresh'))
                          }
                        }}
                        aria-label="Statut recommandation"
                        title="Statut recommandation"
                      >
                        <option value="OPEN">OPEN</option>
                        <option value="ACKNOWLEDGED">ACK</option>
                        <option value="RESOLVED">RESOLVED</option>
                      </select>
                    </div>
                  </td>
                  <td className="px-2 py-3 text-right tabular-nums">{r.occurrences}</td>
                  <td className="px-2 py-3 text-xs text-slate-600">{formatDateHeure(r.last_seen_at)}</td>
                  <td className="px-2 py-3">
                    <RecoActions r={r} internal={internal} />
                  </td>
                  <td className="px-2 py-3 text-right">
                    <button
                      type="button"
                      className="rounded-md bg-slate-900 px-3 py-2 text-xs font-semibold text-white hover:bg-slate-800"
                      disabled={saving}
                      onClick={() => {
                        setModalRecoId(r.id)
                        setNewActionType('MANUAL')
                        setNewActionDesc('')
                        setModalOpen(true)
                      }}
                    >
                      Ajouter action
                    </button>
                  </td>
                </tr>
              ))}

              {data && data.recommendations.length === 0 && (
                <tr>
                  <td className="px-2 py-3 text-sm text-slate-500" colSpan={6}>
                    Aucune recommandation.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>

        <div className="mt-2 text-xs text-slate-500">Lecture seule : pas de bouton d’ack/resolution ici.</div>
      </div>

      <Modal
        open={modalOpen}
        onClose={() => {
          if (!saving) setModalOpen(false)
        }}
      >
        <div className="text-sm font-semibold">Ajouter une action</div>
        <div className="mt-3 grid gap-3">
          <div>
            <label className="block text-xs font-medium text-slate-600">Type d’action</label>
            <select
              className="mt-1 w-full rounded-md border bg-white px-3 py-2 text-sm"
              value={newActionType}
              onChange={(e) => setNewActionType(e.target.value)}
              aria-label="Type d’action"
              title="Type d’action"
            >
              <option value="MANUAL">MANUAL</option>
              <option value="SUPPLY">SUPPLY</option>
              <option value="RECIPE">RECIPE</option>
              <option value="PROCESS">PROCESS</option>
            </select>
            <div className="mt-1 text-[11px] text-slate-500">Liste libre (simple). Backend accepte une string.</div>
          </div>

          <div>
            <label className="block text-xs font-medium text-slate-600">Description</label>
            <textarea
              className="mt-1 w-full rounded-md border bg-white px-3 py-2 text-sm"
              rows={4}
              value={newActionDesc}
              onChange={(e) => setNewActionDesc(e.target.value)}
              placeholder="Décris l’action à mener…"
            />
          </div>

          {erreur && <div className="rounded border border-red-200 bg-red-50 p-2 text-xs text-red-700">{erreur}</div>}

          <div className="flex justify-end gap-2">
            <button
              type="button"
              className="rounded-md border px-3 py-2 text-sm"
              onClick={() => setModalOpen(false)}
              disabled={saving}
            >
              Annuler
            </button>
            <button
              type="button"
              className="rounded-md bg-slate-900 px-4 py-2 text-sm font-semibold text-white hover:bg-slate-800 disabled:opacity-60"
              disabled={saving || !modalRecoId || !newActionType}
              onClick={async () => {
                if (!modalRecoId) return
                setSaving(true)
                setErreur(null)
                setMessageSucces(null)
                try {
                  if (internal) {
                    await creerImpactAction(modalRecoId, {
                      action_type: newActionType,
                      description: newActionDesc.trim() ? newActionDesc.trim() : null,
                    })
                  } else {
                    await creerImpactActionPublic(modalRecoId, {
                      action_type: newActionType,
                      description: newActionDesc.trim() ? newActionDesc.trim() : null,
                    })
                  }
                  setModalOpen(false)
                  setMessageSucces('Action créée.')
                  window.dispatchEvent(new CustomEvent('impact:refresh'))
                } catch (e: unknown) {
                  const err = e as { message?: string }
                  setErreur(err?.message || 'Erreur: création action')
                } finally {
                  setSaving(false)
                }
              }}
            >
              {saving ? 'Enregistrement…' : 'Créer'}
            </button>
          </div>
        </div>
      </Modal>
    </div>
  )
}
