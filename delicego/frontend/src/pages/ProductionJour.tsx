import { useEffect, useMemo, useState } from 'react'

import { listerMagasins, type MagasinClient } from '../api/client'
import {
  lireProductionPreparation,
  executerProductionDuJour,
  type BesoinIngredient,
  type ErreurApi,
  type LigneCuisine,
} from '../api/interne'

function isoDateDuJour(): string {
  const d = new Date()
  const yyyy = d.getFullYear()
  const mm = String(d.getMonth() + 1).padStart(2, '0')
  const dd = String(d.getDate()).padStart(2, '0')
  return `${yyyy}-${mm}-${dd}`
}

export function ProductionJour() {
  const [magasins, setMagasins] = useState<MagasinClient[]>([])
  const [magasinId, setMagasinId] = useState<string>('')
  const [date, setDate] = useState<string>(isoDateDuJour())

  const [chargement, setChargement] = useState(false)
  const [erreur, setErreur] = useState<string | null>(null)
  const [succes, setSucces] = useState<string | null>(null)

  // Recettes du plan (source backend existante)
  const [lignes, setLignes] = useState<LigneCuisine[]>([])

  // Quantités utilisateur (par recette_id)
  const [quantites, setQuantites] = useState<Record<string, number>>({})

  // Résultat : besoins ingrédients
  const [planId, setPlanId] = useState<string | null>(null)
  const [besoins, setBesoins] = useState<BesoinIngredient[] | null>(null)
  const [resume, setResume] = useState<{
    lots_crees: number
    consommations_creees: number
  } | null>(null)

  const peutCharger = useMemo(() => Boolean(magasinId && date), [magasinId, date])

  async function chargerRecettes() {
    if (!peutCharger) return
    setChargement(true)
    setErreur(null)
    setSucces(null)
    setPlanId(null)
    setBesoins(null)
    setResume(null)

    try {
      const data = await lireProductionPreparation(magasinId, date)
      setLignes(data.cuisine)

      // Initialiser les quantités (par défaut: quantite_planifiee)
      const init: Record<string, number> = {}
      for (const l of data.cuisine) {
        init[l.recette_id] = Number.isFinite(l.quantite_planifiee)
          ? Number(l.quantite_planifiee)
          : 0
      }
      setQuantites(init)
    } catch (e) {
      const err = e as ErreurApi
      setErreur(err?.message || 'Erreur')
    } finally {
      setChargement(false)
    }
  }

  async function lancerProduction() {
    if (!peutCharger) return
    setChargement(true)
    setErreur(null)
    setSucces(null)
    setPlanId(null)
    setBesoins(null)
    setResume(null)

    try {
      // Payload envoyé:
      // {
      //   magasin_id: "<uuid>",
      //   date_jour: "YYYY-MM-DD",
      //   lignes: [{ recette_id: "<uuid>", quantite_a_produire: 12 }, ...]
      // }

      const lignesPayload = lignes
        .map((l) => ({
          recette_id: l.recette_id,
          quantite_a_produire: Number(quantites[l.recette_id] ?? 0),
        }))
        .filter((l) => Number.isFinite(l.quantite_a_produire) && l.quantite_a_produire > 0)

      if (lignesPayload.length === 0) {
        setErreur('Renseigner au moins une quantité > 0 avant de lancer la production.')
        return
      }

      const rep = await executerProductionDuJour({
        magasin_id: magasinId,
        date_jour: date,
        lignes: lignesPayload,
      })

      setPlanId(rep.plan_id)
      setResume({
        lots_crees: rep.lots_crees,
        consommations_creees: rep.consommations_creees,
      })
      // Optionnel : si le backend renvoie les besoins, on les affiche.
      setBesoins((rep.besoins as BesoinIngredient[] | null | undefined) ?? null)

      setSucces('Production exécutée et stock consommé.')
    } catch (e) {
      const err = e as ErreurApi
      setErreur(err?.message || 'Erreur')
    } finally {
      setChargement(false)
    }
  }

  useEffect(() => {
    listerMagasins()
      .then((ms) => {
        setMagasins(ms)
        if (!magasinId && ms.length > 0) setMagasinId(ms[0].id)
      })
      .catch(() => {
        // non bloquant
      })

    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <div className="text-sm text-slate-500">Production</div>
          <h1 className="text-2xl font-semibold">Production du jour</h1>
        </div>
      </div>

      <div className="rounded-lg border bg-white p-4">
        <div className="grid grid-cols-1 gap-3 md:grid-cols-4">
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
            <div className="text-xs font-medium text-slate-600">Date</div>
            <input
              className="w-full rounded-md border px-3 py-2 text-sm"
              type="date"
              value={date}
              onChange={(e) => setDate(e.target.value)}
            />
          </label>

          <div className="flex items-end">
            <button
              className="w-full rounded-md bg-slate-900 px-3 py-2 text-sm font-medium text-white disabled:opacity-50"
              onClick={() => void chargerRecettes()}
              disabled={!peutCharger || chargement || magasins.length === 0}
            >
              {chargement ? 'Chargement...' : 'Charger recettes'}
            </button>
          </div>

          <div className="flex items-end">
            <button
              className="w-full rounded-md bg-emerald-600 px-3 py-2 text-sm font-medium text-white disabled:opacity-50"
              onClick={() => void lancerProduction()}
              disabled={!peutCharger || chargement || magasins.length === 0}
            >
              {chargement ? 'En cours...' : 'Lancer production'}
            </button>
          </div>
        </div>

        {erreur && <div className="mt-3 rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">{erreur}</div>}
        {succes && <div className="mt-3 rounded-md border border-emerald-200 bg-emerald-50 px-3 py-2 text-sm text-emerald-800">{succes}</div>}
        {planId && <div className="mt-2 text-xs text-slate-500">PlanProduction: {planId}</div>}
        {resume && (
          <div className="mt-1 text-xs text-slate-500">
            Lots créés: {resume.lots_crees} — Consommations créées: {resume.consommations_creees}
          </div>
        )}
      </div>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <div className="rounded-lg border bg-white overflow-hidden">
          <div className="border-b px-4 py-3 text-sm font-medium">Recettes</div>
          <div className="divide-y">
            {lignes.length === 0 ? (
              <div className="px-4 py-6 text-sm text-slate-500">
                Clique “Charger recettes” pour obtenir la liste (plan du jour).
              </div>
            ) : (
              lignes.map((l) => (
                <div key={l.recette_id} className="flex items-center justify-between gap-3 px-4 py-3">
                  <div className="min-w-0">
                    <div className="truncate font-medium">{l.recette_nom}</div>
                    <div className="text-xs text-slate-500">Planifié: {l.quantite_planifiee}</div>
                  </div>

                  <div className="flex items-center gap-2">
                    <input
                      className="w-24 rounded-md border px-2 py-1 text-sm"
                      type="number"
                      min={0}
                      step={1}
                      value={quantites[l.recette_id] ?? 0}
                      onChange={(e) => {
                        const v = Number(e.target.value)
                        setQuantites((prev) => ({
                          ...prev,
                          [l.recette_id]: Number.isFinite(v) && v >= 0 ? v : 0,
                        }))
                      }}
                      aria-label={`Quantité à produire pour ${l.recette_nom}`}
                    />
                    <span className="text-xs text-slate-500">unités</span>
                  </div>
                </div>
              ))
            )}
          </div>
          <div className="border-t bg-slate-50 px-4 py-2 text-xs text-slate-500">
            Astuce: mets 0 pour ignorer une recette.
          </div>
        </div>

        <div className="rounded-lg border bg-white overflow-hidden">
          <div className="border-b px-4 py-3 text-sm font-medium">Besoins ingrédients</div>
          <div className="px-4 py-4">
            {!besoins ? (
              <div className="text-sm text-slate-500">
                Lance la production pour exécuter les lots + la consommation (et afficher les besoins si le backend les renvoie).
              </div>
            ) : besoins.length === 0 ? (
              <div className="text-sm text-slate-500">Aucun besoin.</div>
            ) : (
              <div className="overflow-x-auto">
                <table className="min-w-full text-sm">
                  <thead className="bg-slate-50 text-slate-600">
                    <tr>
                      <th className="px-3 py-2 text-left font-semibold">Ingrédient</th>
                      <th className="px-3 py-2 text-right font-semibold">Quantité</th>
                      <th className="px-3 py-2 text-left font-semibold">Unité</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y">
                    {besoins.map((b) => (
                      <tr key={b.ingredient_id}>
                        <td className="px-3 py-2 font-medium text-slate-900">{b.ingredient_nom}</td>
                        <td className="px-3 py-2 text-right tabular-nums">{b.quantite}</td>
                        <td className="px-3 py-2 text-slate-600">{b.unite}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}
