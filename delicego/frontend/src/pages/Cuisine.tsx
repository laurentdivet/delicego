import { useEffect, useMemo, useState } from 'react'

import { listerMagasins, type MagasinClient } from '../api/client'
import {
  actionAjuste,
  actionNonProduit,
  actionProduit,
  lireProductionPreparation,
  lireTraceabilite,
} from '../api/interne'
import type { ErreurApi, LigneCuisine, TraceabiliteProductionPreparation } from '../api/interne'

function isoDateDuJour(): string {
  const d = new Date()
  const yyyy = d.getFullYear()
  const mm = String(d.getMonth() + 1).padStart(2, '0')
  const dd = String(d.getDate()).padStart(2, '0')
  return `${yyyy}-${mm}-${dd}`
}

export function Cuisine() {
  const [magasins, setMagasins] = useState<MagasinClient[]>([])
  const [magasinId, setMagasinId] = useState<string>('')
  const [date, setDate] = useState<string>(isoDateDuJour())

  const [chargement, setChargement] = useState(false)
  const [erreur, setErreur] = useState<string | null>(null)

  const [lignes, setLignes] = useState<LigneCuisine[]>([])
  const [total, setTotal] = useState<number>(0)

  const [recetteSelectionnee, setRecetteSelectionnee] = useState<LigneCuisine | null>(null)
  const [traceabilite, setTraceabilite] = useState<TraceabiliteProductionPreparation | null>(null)

  const peutCharger = useMemo(() => Boolean(magasinId && date), [magasinId, date])

  async function charger() {
    if (!peutCharger) return
    setChargement(true)
    setErreur(null)

    try {
      const data = await lireProductionPreparation(magasinId, date)
      setLignes(data.cuisine)
      setTotal(data.quantites_a_produire_aujourdhui)

      // Rafraîchir la traçabilité si une recette est sélectionnée
      if (recetteSelectionnee) {
        const t = await lireTraceabilite(magasinId, date, recetteSelectionnee.recette_id)
        setTraceabilite(t)
      }
    } catch (e) {
      const err = e as ErreurApi
      setErreur(err?.message || 'Erreur')
    } finally {
      setChargement(false)
    }
  }

  async function chargerTraceabilite(recette: LigneCuisine) {
    setRecetteSelectionnee(recette)
    setTraceabilite(null)
    setErreur(null)

    try {
      const t = await lireTraceabilite(magasinId, date, recette.recette_id)
      setTraceabilite(t)
    } catch (e) {
      const err = e as ErreurApi
      setErreur(err?.message || 'Erreur')
    }
  }

  async function onProduit(recette: LigneCuisine) {
    setChargement(true)
    setErreur(null)
    try {
      await actionProduit(magasinId, date, recette.recette_id)
      await charger()
      await chargerTraceabilite(recette)
    } catch (e) {
      const err = e as ErreurApi
      setErreur(err?.message || 'Erreur')
    } finally {
      setChargement(false)
    }
  }

  async function onAjuste(recette: LigneCuisine) {
    const val = window.prompt('Quantité produite (nombre) ?')
    if (val == null) return
    const q = Number(val)
    if (!Number.isFinite(q) || q < 0) {
      setErreur('Quantité invalide')
      return
    }

    setChargement(true)
    setErreur(null)
    try {
      await actionAjuste(magasinId, date, recette.recette_id, q)
      await charger()
      await chargerTraceabilite(recette)
    } catch (e) {
      const err = e as ErreurApi
      setErreur(err?.message || 'Erreur')
    } finally {
      setChargement(false)
    }
  }

  async function onNonProduit(recette: LigneCuisine) {
    setChargement(true)
    setErreur(null)
    try {
      await actionNonProduit(magasinId, date, recette.recette_id)
      await charger()
      await chargerTraceabilite(recette)
    } catch (e) {
      const err = e as ErreurApi
      setErreur(err?.message || 'Erreur')
    } finally {
      setChargement(false)
    }
  }

  useEffect(() => {
    // Charger la liste des magasins (pour éviter de saisir un UUID)
    listerMagasins()
      .then((ms) => {
        setMagasins(ms)
        if (!magasinId && ms.length > 0) setMagasinId(ms[0].id)
      })
      .catch(() => {
        // non bloquant (on peut toujours saisir un UUID si besoin)
      })

    // auto-load si magasin_id est déjà renseigné
    if (peutCharger) {
      void charger()
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <div className="text-sm text-slate-500">Production & Préparation</div>
          <h1 className="text-2xl font-semibold">Cuisine</h1>
        </div>
        <div className="text-sm text-slate-600">Total à produire : {total}</div>
      </div>

      <div className="rounded-lg border bg-white p-4">
        <div className="grid grid-cols-1 gap-3 md:grid-cols-3">
          <label className="space-y-1">
            <div className="text-xs font-medium text-slate-600">Magasin</div>
            <select
              className="w-full rounded-md border bg-white px-3 py-2 text-sm"
              value={magasinId}
              onChange={(e) => setMagasinId(e.target.value)}
              aria-label="Magasin"
            >
              {magasins.length === 0 ? (
                <option value="">Chargement…</option>
              ) : (
                magasins.map((m) => (
                  <option key={m.id} value={m.id}>
                    {m.nom}
                  </option>
                ))
              )}
            </select>
          </label>

          <label className="space-y-1">
            <div className="text-xs font-medium text-slate-600">date</div>
            <input className="w-full rounded-md border px-3 py-2 text-sm" type="date" value={date} onChange={(e) => setDate(e.target.value)} />
          </label>

          <div className="flex items-end">
            <button
              className="w-full rounded-md bg-slate-900 px-3 py-2 text-sm font-medium text-white disabled:opacity-50"
              onClick={() => void charger()}
              disabled={!peutCharger || chargement || magasins.length === 0}
            >
              {chargement ? 'Chargement...' : 'Charger'}
            </button>
          </div>
        </div>

        {erreur && <div className="mt-3 rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">{erreur}</div>}
      </div>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
        <div className="lg:col-span-2 rounded-lg border bg-white">
          <div className="border-b px-4 py-3 text-sm font-medium">À produire aujourd’hui</div>
          <div className="divide-y">
            {lignes.length === 0 ? (
              <div className="px-4 py-6 text-sm text-slate-500">Aucune ligne (choisis un magasin + une date puis Charger).</div>
            ) : (
              lignes.map((l) => (
                <div key={l.recette_id} className="flex flex-col gap-2 px-4 py-3 md:flex-row md:items-center md:justify-between">
                  <div className="min-w-0">
                    <div className="flex items-center gap-2">
                      <div className="truncate font-medium">{l.recette_nom}</div>
                      <span className="rounded-full bg-slate-100 px-2 py-0.5 text-xs text-slate-700">{l.statut}</span>
                    </div>
                    <div className="text-xs text-slate-500">
                      Planifié: {l.quantite_planifiee} • Produit: {l.quantite_produite}
                    </div>
                  </div>

                  <div className="flex flex-wrap gap-2">
                    <button
                      className="rounded-md bg-emerald-600 px-3 py-1.5 text-xs font-medium text-white disabled:opacity-50"
                      onClick={() => void onProduit(l)}
                      disabled={chargement}
                    >
                      Produit
                    </button>
                    <button
                      className="rounded-md bg-amber-500 px-3 py-1.5 text-xs font-medium text-white disabled:opacity-50"
                      onClick={() => void onAjuste(l)}
                      disabled={chargement}
                    >
                      Ajusté
                    </button>
                    <button
                      className="rounded-md bg-slate-700 px-3 py-1.5 text-xs font-medium text-white disabled:opacity-50"
                      onClick={() => void onNonProduit(l)}
                      disabled={chargement}
                    >
                      Non produit
                    </button>
                    <button
                      className="rounded-md border px-3 py-1.5 text-xs font-medium text-slate-800 hover:bg-slate-50 disabled:opacity-50"
                      onClick={() => void chargerTraceabilite(l)}
                      disabled={chargement || !peutCharger}
                    >
                      Traçabilité
                    </button>
                  </div>
                </div>
              ))
            )}
          </div>
        </div>

        <div className="rounded-lg border bg-white">
          <div className="border-b px-4 py-3 text-sm font-medium">Traçabilité post-service</div>
          <div className="px-4 py-4">
            {!recetteSelectionnee ? (
              <div className="text-sm text-slate-500">Sélectionne une recette puis “Traçabilité”.</div>
            ) : !traceabilite ? (
              <div className="text-sm text-slate-500">Chargement…</div>
            ) : traceabilite.evenements.length === 0 ? (
              <div className="text-sm text-slate-500">Aucun événement.</div>
            ) : (
              <div className="space-y-2">
                <div className="text-xs text-slate-500">Recette : {recetteSelectionnee.recette_nom}</div>
                <ul className="space-y-2">
                  {traceabilite.evenements.map((e, idx) => (
                    <li key={idx} className="rounded-md border bg-slate-50 px-3 py-2 text-xs">
                      <div className="flex items-center justify-between">
                        <span className="font-medium">{e.type}</span>
                        <span className="text-slate-500">{new Date(e.date_heure).toLocaleString()}</span>
                      </div>
                      <div className="mt-1 text-slate-600">Quantité: {e.quantite ?? '—'} • Lot: {e.lot_production_id ?? '—'}</div>
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}
