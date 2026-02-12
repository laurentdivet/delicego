import { useEffect, useMemo, useState } from 'react'

import { listerMagasins, type MagasinClient } from '../api/client'
import {
  lireConsommation,
  lireDashboardExecutif,
  lirePrevisionVentes,
  type ConsommationIngredient,
  type DashboardExecutif,
  type PointHoraireVentes,
  type PrevisionVentes,
} from '../api/interne'
import { lireForecastVsActual, type ForecastVsActualResponse } from '../api/forecastVsActual'
import { KpiCard } from '../components/KpiCard'

function formatNombre(n: number) {
  return Intl.NumberFormat('fr-FR', { maximumFractionDigits: 2 }).format(n)
}

function formatEur(n: number) {
  return Intl.NumberFormat('fr-FR', { style: 'currency', currency: 'EUR', maximumFractionDigits: 0 }).format(n)
}

function formatPct(n: number) {
  return `${Intl.NumberFormat('fr-FR', { maximumFractionDigits: 1 }).format(n)}%`
}

export function Dashboard() {
  const [dateCible, setDateCible] = useState('2025-01-01')
  const [magasinId, setMagasinId] = useState<string | null>(null)

  const [magasins, setMagasins] = useState<MagasinClient[]>([])

  const [dash, setDash] = useState<DashboardExecutif | null>(null)
  const [conso, setConso] = useState<ConsommationIngredient[]>([])
  const [prevision, setPrevision] = useState<PrevisionVentes | null>(null)
  const [fvA, setFvA] = useState<ForecastVsActualResponse | null>(null)
  const [loading, setLoading] = useState(false)
  const [erreur, setErreur] = useState<string | null>(null)

  useEffect(() => {
    listerMagasins()
      .then(setMagasins)
      .catch(() => {
        // non bloquant
      })
  }, [])

  useEffect(() => {
    async function charger() {
      setLoading(true)
      setErreur(null)
      try {
        const d = await lireDashboardExecutif(dateCible, magasinId)
        const c = await lireConsommation(dateCible, dateCible)
        const p = await lirePrevisionVentes(dateCible, magasinId)
        const fva = await lireForecastVsActual({
          store_id: magasinId || undefined,
          date_from: dateCible,
          horizon: 14,
        })
        setDash(d)
        setConso(c)
        setPrevision(p)
        setFvA(fva)
      } catch (e: unknown) {
        const err = e as { message?: string }
        setErreur(err?.message || 'Erreur de chargement du dashboard')
      } finally {
        setLoading(false)
      }
    }

    charger()
  }, [dateCible, magasinId])

  const topStocksBas = useMemo(() => {
    return [...conso].sort((a, b) => a.stock_estime - b.stock_estime).slice(0, 6)
  }, [conso])

  const alertes = dash?.alertes || []

  return (
    <div className="space-y-6">
      <div className="flex flex-col gap-3 md:flex-row md:items-end md:justify-between">
        <div>
          <h1 className="text-2xl font-semibold">Dashboard exécutif</h1>
          <p className="text-sm text-slate-500">Objectif: savoir en 30 secondes si le business est sous contrôle.</p>
        </div>

        <div className="flex flex-col gap-3 md:flex-row md:items-end">
          <div>
            <label className="block text-xs font-medium text-slate-600">Site</label>
            <select
              className="mt-1 w-full rounded-md border bg-white px-3 py-2 text-sm"
              value={magasinId || ''}
              onChange={(e) => setMagasinId(e.target.value || null)}
              aria-label="Sélecteur de site"
            >
              <option value="">Tous les sites</option>
              {magasins.map((m) => (
                <option key={m.id} value={m.id}>
                  {m.nom}
                </option>
              ))}
            </select>
          </div>

          <div>
            <label className="block text-xs font-medium text-slate-600">Date</label>
            <input
              type="date"
              className="mt-1 rounded-md border bg-white px-3 py-2 text-sm"
              value={dateCible}
              onChange={(e) => setDateCible(e.target.value)}
              aria-label="Date cible"
            />
          </div>
        </div>
      </div>

      {erreur && <div className="rounded border border-red-200 bg-red-50 p-3 text-sm text-red-700">{erreur}</div>}

      {/* Bandeau alertes visibles sans cliquer */}
      <div className="rounded-xl border bg-white p-3 shadow-sm">
        <div className="flex flex-col gap-2 md:flex-row md:items-center md:justify-between">
          <div className="text-sm font-semibold">Alertes</div>
          <div className="text-xs text-slate-500">{loading ? 'Mise à jour…' : dash ? `Date: ${dash.date_cible}` : '—'}</div>
        </div>

        <div className="mt-2 flex flex-wrap gap-2">
          {alertes.length === 0 && <div className="text-sm text-slate-500">Aucune alerte détectée.</div>}
          {alertes.map((a) => (
            <div key={a} className="rounded-full bg-slate-100 px-3 py-1 text-xs text-slate-700">
              {a}
            </div>
          ))}
        </div>
      </div>

      {/* KPI prioritaires */}
      <div className="grid gap-4 md:grid-cols-3">
        <KpiCard
          titre="CA du jour"
          valeur={dash ? formatEur(dash.kpis.ca_jour.valeur) : loading ? '…' : '—'}
          variationPct={dash?.kpis.ca_jour.variation_pct}
        />
        <KpiCard
          titre="CA semaine"
          valeur={dash ? formatEur(dash.kpis.ca_semaine.valeur) : loading ? '…' : '—'}
          variationPct={dash?.kpis.ca_semaine.variation_pct}
        />
        <KpiCard
          titre="CA mois"
          valeur={dash ? formatEur(dash.kpis.ca_mois.valeur) : loading ? '…' : '—'}
          variationPct={dash?.kpis.ca_mois.variation_pct}
        />

        <KpiCard
          titre="Écart vs prévision"
          valeur={dash?.kpis.ecart_vs_prevision_pct !== undefined && dash?.kpis.ecart_vs_prevision_pct !== null ? formatPct(dash.kpis.ecart_vs_prevision_pct) : loading ? '…' : '—'}
          niveau={dash?.statuts?.ecart_vs_prevision_pct?.niveau}
          sousTitre={dash?.statuts?.ecart_vs_prevision_pct?.message || 'Prévu vs réel'}
        />

        <KpiCard
          titre="Food cost réel"
          valeur={dash?.kpis.food_cost_reel_pct !== undefined && dash?.kpis.food_cost_reel_pct !== null ? formatPct(dash.kpis.food_cost_reel_pct) : loading ? '…' : '—'}
          niveau={dash?.statuts?.food_cost_reel_pct?.niveau}
        />

        <KpiCard
          titre="Marge brute"
          valeur={
            dash && dash.kpis.marge_brute_eur !== null && dash.kpis.marge_brute_eur !== undefined
              ? `${formatEur(dash.kpis.marge_brute_eur)} • ${dash.kpis.marge_brute_pct != null ? formatPct(dash.kpis.marge_brute_pct) : '—'}`
              : loading
                ? '…'
                : '—'
          }
          niveau={dash?.statuts?.marge_brute_pct?.niveau}
        />

        <KpiCard
          titre="Pertes & gaspillages"
          valeur={dash?.kpis.pertes_gaspillage_eur != null ? formatEur(dash.kpis.pertes_gaspillage_eur) : loading ? '…' : '—'}
          niveau={dash?.statuts?.pertes_gaspillage_eur?.niveau}
        />

        <KpiCard
          titre="Ruptures produits"
          valeur={dash ? `${dash.kpis.ruptures_produits_nb}` : loading ? '…' : '—'}
          niveau={dash?.statuts?.ruptures?.niveau}
          sousTitre={dash?.kpis.ruptures_impact_eur != null ? `Impact: ${formatEur(dash.kpis.ruptures_impact_eur)}` : undefined}
        />

        <KpiCard
          titre="Heures économisées"
          valeur={dash?.kpis.heures_economisees != null ? formatNombre(dash.kpis.heures_economisees) : '—'}
          sousTitre="Automatisation"
        />
      </div>

      {/* Prévision des ventes */}
      <div className="rounded-xl border bg-white p-4 shadow-sm">
        <div className="mb-3 flex items-center justify-between">
          <div>
            <div className="text-sm font-semibold">Prévision des ventes</div>
            <div className="text-xs text-slate-500">Prévu vs réel • Fiabilité modèle • Détails produits</div>
          </div>
          <div className="text-xs text-slate-500">API: /api/interne/previsions/ventes</div>
        </div>

        <div className="grid gap-3 md:grid-cols-4">
          <div className="rounded-lg bg-slate-50 p-3">
            <div className="text-xs text-slate-500">CA prévu</div>
            <div className="mt-1 text-lg font-semibold tabular-nums">{prevision ? formatEur(prevision.ca_prevu) : loading ? '…' : '—'}</div>
          </div>
          <div className="rounded-lg bg-slate-50 p-3">
            <div className="text-xs text-slate-500">CA réel</div>
            <div className="mt-1 text-lg font-semibold tabular-nums">{prevision ? formatEur(prevision.ca_reel) : loading ? '…' : '—'}</div>
          </div>
          <div className="rounded-lg bg-slate-50 p-3">
            <div className="text-xs text-slate-500">Écart</div>
            <div className="mt-1 text-lg font-semibold tabular-nums">{prevision ? formatEur(prevision.ecart_ca) : loading ? '…' : '—'}</div>
          </div>
          <div className="rounded-lg bg-slate-50 p-3">
            <div className="text-xs text-slate-500">Fiabilité modèle</div>
            <div className="mt-1 text-lg font-semibold tabular-nums">
              {prevision?.fiabilite?.fiabilite_ca_pct != null ? `${formatNombre(prevision.fiabilite.fiabilite_ca_pct)}%` : loading ? '…' : '—'}
            </div>
            <div className="mt-1 text-xs text-slate-500">
              WAPE: {prevision?.fiabilite?.wape_ca_pct != null ? `${formatNombre(prevision.fiabilite.wape_ca_pct)}%` : '—'}
            </div>
          </div>
        </div>

        {/* Courbe horaire (mini) */}
        <div className="mt-4">
          <div className="mb-2 text-xs font-medium text-slate-600">Courbe horaire (quantités)</div>
          <div className="grid grid-cols-24 items-end gap-1">
            {(prevision?.courbe_horaire ||
              Array.from({ length: 24 }).map((_, i): PointHoraireVentes => ({
                heure: i,
                quantite_reelle: 0,
                quantite_prevue: 0,
                ecart_quantite: 0,
                ca_prevu: 0,
                ca_reel: 0,
                ecart_ca: 0,
              })))
              .slice(0, 24)
              .map((p) => (
                <div key={p.heure} className="flex flex-col gap-1">
                  <div className="h-14 rounded bg-slate-100">
                    <div
                      className="h-full rounded bg-emerald-500/60"
                      style={{ height: `${Math.min(100, Math.max(0, (Number(p.quantite_reelle) || 0) * 10))}%` }}
                    />
                  </div>
                </div>
              ))}
          </div>
          <div className="mt-1 text-xs text-slate-500">MVP: la prévision horaire est dérivée (répartition selon les ventes du jour).</div>
        </div>

        {/* Table produit */}
        <div className="mt-4 overflow-x-auto">
          <table className="w-full border-separate border-spacing-y-2">
            <thead>
              <tr className="text-left text-xs text-slate-500">
                <th className="px-2">Produit</th>
                <th className="px-2 text-right">Qté prévue</th>
                <th className="px-2 text-right">Qté vendue</th>
                <th className="px-2 text-right">Écart</th>
                <th className="px-2 text-right">CA prévu</th>
                <th className="px-2 text-right">CA réel</th>
              </tr>
            </thead>
            <tbody>
              {(prevision?.table_produits || []).slice(0, 12).map((l) => (
                <tr key={l.menu_id} className="rounded-lg bg-white text-sm shadow-sm">
                  <td className="px-2 py-2 font-medium">{l.menu_nom}</td>
                  <td className="px-2 py-2 text-right tabular-nums">{formatNombre(l.quantite_prevue)}</td>
                  <td className="px-2 py-2 text-right tabular-nums">{formatNombre(l.quantite_vendue)}</td>
                  <td className="px-2 py-2 text-right tabular-nums">{formatNombre(l.ecart_quantite)}</td>
                  <td className="px-2 py-2 text-right tabular-nums">{formatEur(l.ca_prevu)}</td>
                  <td className="px-2 py-2 text-right tabular-nums">{formatEur(l.ca_reel)}</td>
                </tr>
              ))}
              {prevision && prevision.table_produits.length === 0 && (
                <tr>
                  <td className="px-2 py-2 text-sm text-slate-500" colSpan={6}>
                    Aucune donnée de prévision/ventes pour cette date.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>

      {/* Forecast vs réel (Step14) — read-only */}
      <div className="rounded-xl border bg-white p-4 shadow-sm">
        <div className="mb-3 flex items-center justify-between">
          <div>
            <div className="text-sm font-semibold">Forecast vs réel (Step14)</div>
            <div className="text-xs text-slate-500">Comparaison non destructive • Lecture seule</div>
          </div>
          <div className="text-xs text-slate-500">API: /api/interne/monitoring/forecast-vs-actual</div>
        </div>

        <div className="grid gap-3 md:grid-cols-3">
          <div className="rounded-lg bg-slate-50 p-3">
            <div className="text-xs text-slate-500">Accuracy</div>
            <div className="mt-1 text-lg font-semibold tabular-nums">
              {fvA?.kpis?.accuracy_pct != null ? formatPct(fvA.kpis.accuracy_pct) : loading ? '…' : '—'}
            </div>
          </div>
          <div className="rounded-lg bg-slate-50 p-3">
            <div className="text-xs text-slate-500">MAPE</div>
            <div className="mt-1 text-lg font-semibold tabular-nums">
              {fvA?.kpis?.mape_pct != null ? formatPct(fvA.kpis.mape_pct) : loading ? '…' : '—'}
            </div>
          </div>
          <div className="rounded-lg bg-slate-50 p-3">
            <div className="text-xs text-slate-500">Jours hors seuil</div>
            <div className="mt-1 text-lg font-semibold tabular-nums">
              {fvA ? String(fvA.kpis.days_over_threshold) : loading ? '…' : '—'}
            </div>
          </div>
        </div>

        <div className="mt-4 overflow-x-auto">
          <table className="w-full border-separate border-spacing-y-2">
            <thead>
              <tr className="text-left text-xs text-slate-500">
                <th className="px-2">Date</th>
                <th className="px-2 text-right">CA forecast</th>
                <th className="px-2 text-right">CA réel</th>
                <th className="px-2 text-right">Écart</th>
                <th className="px-2 text-right">Écart %</th>
              </tr>
            </thead>
            <tbody>
              {(fvA?.points || []).slice(0, 14).map((p) => (
                <tr key={`${p.store_id}-${p.date}`} className="rounded-lg bg-white text-sm shadow-sm">
                  <td className="px-2 py-2 font-medium">{p.date}</td>
                  <td className="px-2 py-2 text-right tabular-nums">{formatEur(p.forecast_total_amount)}</td>
                  <td className="px-2 py-2 text-right tabular-nums">{formatEur(p.actual_total_amount)}</td>
                  <td className="px-2 py-2 text-right tabular-nums">{formatEur(p.actual_total_amount - p.forecast_total_amount)}</td>
                  <td className="px-2 py-2 text-right tabular-nums">{p.pct_diff != null ? formatPct(p.pct_diff) : '—'}</td>
                </tr>
              ))}
              {fvA && fvA.points.length === 0 && (
                <tr>
                  <td className="px-2 py-2 text-sm text-slate-500" colSpan={5}>
                    Aucune donnée forecast/actuals disponible sur la période.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>

        <div className="mt-2 text-xs text-slate-500">Aucun bouton d’action : Step14 est strictement read-only.</div>
      </div>

      {/* Contexte (optionnel) : stock estimé */}
      <div className="grid gap-4 md:grid-cols-2">
        <div className="rounded-xl border bg-white p-4 shadow-sm">
          <div className="mb-3 flex items-center justify-between">
            <div className="text-sm font-semibold">Stock estimé (top bas)</div>
            <div className="text-xs text-slate-500">Détail</div>
          </div>

          <div className="space-y-2">
            {topStocksBas.map((l) => (
              <div key={l.ingredient_id} className="flex items-center gap-3">
                <div className="w-44 truncate text-sm">{l.ingredient}</div>
                <div className="flex-1">
                  <div className="h-2 rounded bg-slate-100">
                    <div
                      className="h-2 rounded bg-emerald-500"
                      style={{ width: `${Math.min(100, Math.max(2, (l.stock_estime / 100) * 100))}%` }}
                    />
                  </div>
                </div>
                <div className="w-16 text-right text-sm tabular-nums">{formatNombre(l.stock_estime)}</div>
              </div>
            ))}

            {topStocksBas.length === 0 && <div className="text-sm text-slate-500">Aucune donnée.</div>}
          </div>
        </div>

        <div className="rounded-xl border bg-white p-4 shadow-sm">
          <div className="mb-3 flex items-center justify-between">
            <div className="text-sm font-semibold">Comparaison prévu vs réel</div>
            <div className="text-xs text-slate-500">Synthèse</div>
          </div>

          <div className="space-y-2 text-sm">
            <div className="flex items-center justify-between">
              <span className="text-slate-600">CA du jour</span>
              <span className="font-medium tabular-nums">{dash ? formatEur(dash.kpis.ca_jour.valeur) : '—'}</span>
            </div>
            <div className="flex items-center justify-between">
              <span className="text-slate-600">Écart vs prévision</span>
              <span className="font-medium tabular-nums">
                {dash?.kpis.ecart_vs_prevision_pct != null ? formatPct(dash.kpis.ecart_vs_prevision_pct) : '—'}
              </span>
            </div>
            <div className="text-xs text-slate-500">
              MVP: la prévision vient de `LignePrevision` (si disponible) et se filtre par site.
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
