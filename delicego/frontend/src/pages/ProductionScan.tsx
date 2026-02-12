import { useEffect, useMemo, useRef, useState } from 'react'

import { listerMagasins, type MagasinClient } from '../api/client'
import { lireProductionPreparation, scannerGencodeProduction, type LigneProductionScan } from '../api/interne'

function isoDateDuJour(): string {
  const d = new Date()
  const yyyy = d.getFullYear()
  const mm = String(d.getMonth() + 1).padStart(2, '0')
  const dd = String(d.getDate()).padStart(2, '0')
  return `${yyyy}-${mm}-${dd}`
}

type Ligne = LigneProductionScan

export function ProductionScan() {
  const [magasins, setMagasins] = useState<MagasinClient[]>([])
  const [magasinId, setMagasinId] = useState<string>('')
  const [date, setDate] = useState<string>(isoDateDuJour())

  const [chargement, setChargement] = useState(false)
  const [erreur, setErreur] = useState<string | null>(null)

  // MVP UI-only: wiring backend to come next
  const [lignes, setLignes] = useState<Ligne[]>([])
  const [lastHighlightId, setLastHighlightId] = useState<string | null>(null)

  const inputRef = useRef<HTMLInputElement | null>(null)

  const peutCharger = useMemo(() => Boolean(magasinId && date), [magasinId, date])

  async function charger() {
    if (!peutCharger) return
    setChargement(true)
    setErreur(null)

    try {
      const data = await lireProductionPreparation(magasinId, date)

      // Projection vers le tableau scan :
      // - id = recette_id (stable)
      // - produit_nom = recette_nom (lisible)
      // - à produire = quantite_planifiee
      // - produit = quantite_produite
      // - restant = a_produire - produit
      const lignesTable: Ligne[] = data.cuisine.map((l) => {
        const a = Number(l.quantite_planifiee || 0)
        const p = Number(l.quantite_produite || 0)
        return {
          id: l.recette_id,
          produit_nom: l.recette_nom,
          a_produire: a,
          produit: p,
          restant: a - p,
        }
      })

      setLignes(lignesTable)
    } catch (e: unknown) {
      const msg =
        typeof e === 'object' && e && 'message' in e
          ? String((e as { message?: unknown }).message)
          : 'Erreur'
      setErreur(msg)
    } finally {
      setChargement(false)
    }
  }

  async function onScan(code: string) {
    // IMPORTANT: code must never be shown in UI
    const trimmed = (code || '').trim()
    if (!trimmed) return

    if (!peutCharger) {
      setErreur('Sélectionner un magasin et une date')
      if (inputRef.current) inputRef.current.value = ''
      return
    }

    setErreur(null)

    try {
      const res = await scannerGencodeProduction(trimmed, magasinId, date)

      setLignes((prev) => {
        const idx = prev.findIndex((p) => p.id === res.ligne.id)
        if (idx < 0) {
          // Si la ligne n'est pas chargée (rare) : on l'ajoute.
          return [res.ligne, ...prev]
        }
        const next = [...prev]
        next[idx] = res.ligne
        return next
      })

      setLastHighlightId(res.ligne.id)
    } catch (e: unknown) {
      const msg =
        typeof e === 'object' && e && 'message' in e
          ? String((e as { message?: unknown }).message)
          : 'Scan impossible'
      setErreur(msg)
      setLastHighlightId(null)
    } finally {
      // Clear input for next scan
      if (inputRef.current) {
        inputRef.current.value = ''
        inputRef.current.focus()
      }
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

    // autofocus scan field
    setTimeout(() => inputRef.current?.focus(), 50)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <div className="text-sm text-slate-500">Opérations</div>
          <h1 className="text-2xl font-semibold">Production (scan)</h1>
        </div>
      </div>

      <div className="rounded-lg border bg-white p-4 space-y-3">
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
              onClick={() => void charger()}
              disabled={!peutCharger || chargement || magasins.length === 0}
            >
              {chargement ? 'Chargement...' : 'Charger'}
            </button>
          </div>
        </div>

        {/* Zone de scan : un simple input qui récupère les frappes du lecteur */}
        <div className="rounded-md border bg-slate-50 p-3">
          <div className="text-xs font-medium text-slate-700">Scanner un produit</div>
          <div className="mt-2 flex gap-2">
            <input
              ref={inputRef}
              inputMode="none"
              autoCapitalize="off"
              autoCorrect="off"
              spellCheck={false}
              className="w-full rounded-md border bg-white px-3 py-2 text-sm"
              placeholder="(scanner ici)"
              aria-label="Scan gencode"
              onKeyDown={(e) => {
                if (e.key === 'Enter') {
                  const target = e.target as HTMLInputElement
                  void onScan(target.value)
                }
              }}
            />
            <button
              className="rounded-md bg-emerald-600 px-3 py-2 text-sm font-medium text-white disabled:opacity-50"
              onClick={() => void onScan(inputRef.current?.value || '')}
            >
              Valider
            </button>
          </div>
          <div className="mt-1 text-xs text-slate-500">Le gencode n’est jamais affiché. L’opérateur scanne puis appuie sur Entrée.</div>
        </div>

        {erreur && <div className="rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">{erreur}</div>}
      </div>

      {/* Tableau production */}
      <div className="rounded-lg border bg-white overflow-hidden">
        <div className="border-b px-4 py-3 text-sm font-medium">Tableau de production</div>

        <div className="overflow-x-auto">
          <table className="min-w-full text-sm">
            <thead className="bg-slate-50 text-slate-600">
              <tr>
                <th className="px-4 py-3 text-left font-semibold">Produit</th>
                <th className="px-4 py-3 text-right font-semibold">À produire</th>
                <th className="px-4 py-3 text-right font-semibold">Produit</th>
                <th className="px-4 py-3 text-right font-semibold">Restant</th>
                <th className="px-4 py-3 text-right font-semibold"> </th>
              </tr>
            </thead>
            <tbody className="divide-y">
              {lignes.length === 0 ? (
                <tr>
                  <td className="px-4 py-6 text-slate-500" colSpan={5}>
                    Aucune ligne. (Les endpoints backend seront branchés à l’étape suivante.)
                  </td>
                </tr>
              ) : (
                lignes.map((l) => {
                  const negatif = l.restant < 0
                  const highlight = lastHighlightId === l.id
                  return (
                    <tr
                      key={l.id}
                      className={
                        highlight
                          ? 'bg-emerald-50'
                          : negatif
                            ? 'bg-red-50'
                            : ''
                      }
                    >
                      <td className="px-4 py-3 font-medium text-slate-900">{l.produit_nom}</td>
                      <td className="px-4 py-3 text-right tabular-nums">{l.a_produire}</td>
                      <td className="px-4 py-3 text-right tabular-nums">{l.produit}</td>
                      <td className={"px-4 py-3 text-right tabular-nums " + (negatif ? 'font-semibold text-red-700' : '')}>
                        {l.restant}
                      </td>
                      <td className="px-4 py-3 text-right">
                        <button
                          className="rounded-md border px-2 py-1 text-xs font-medium text-slate-800 hover:bg-slate-50"
                          aria-label="Modifier"
                          title="Modifier"
                        >
                          ✎
                        </button>
                      </td>
                    </tr>
                  )
                })
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  )
}
