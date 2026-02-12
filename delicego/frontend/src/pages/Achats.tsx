import { useState } from 'react'

import { genererBesoins } from '../api/interne'
import { listerMagasins, type MagasinClient } from '../api/client'

export function Achats() {
  const [magasins, setMagasins] = useState<MagasinClient[]>([])
  const [magasinId, setMagasinId] = useState('')
  const [dateCible, setDateCible] = useState('2025-01-01')
  const [horizon, setHorizon] = useState(7)

  const [loading, setLoading] = useState(false)
  const [resultat, setResultat] = useState<string[] | null>(null)
  const [erreur, setErreur] = useState<string | null>(null)

  async function chargerMagasins() {
    const ms = await listerMagasins()
    setMagasins(ms)
    if (!magasinId && ms.length > 0) setMagasinId(ms[0].id)
  }

  // lazy load
  if (magasins.length === 0) {
    // eslint-disable-next-line @typescript-eslint/no-floating-promises
    chargerMagasins()
  }

  async function lancer() {
    setLoading(true)
    setErreur(null)
    setResultat(null)
    try {
      if (!magasinId) throw new Error('Choisis un magasin')
      const rep = await genererBesoins(magasinId, dateCible, horizon)
      setResultat(rep.commandes_ids)
    } catch (e: unknown) {
      const err = e as { message?: string }
      setErreur(err?.message || 'Erreur achats')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold">Achats</h1>
        <p className="text-sm text-slate-500">Génération des besoins fournisseurs (brouillon) – inspiration Inpulse.</p>
      </div>

      {erreur && <div className="rounded border border-red-200 bg-red-50 p-3 text-sm text-red-700">{erreur}</div>}

      <div className="rounded-xl border bg-white p-4 shadow-sm">
        <div className="grid gap-4 md:grid-cols-4">
          <div>
            <label className="block text-xs font-medium text-slate-600">Magasin</label>
            <select
              className="mt-1 w-full rounded-md border bg-white px-3 py-2 text-sm"
              value={magasinId}
              onChange={(e) => setMagasinId(e.target.value)}
              aria-label="Magasin"
            >
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
              className="mt-1 w-full rounded-md border bg-white px-3 py-2 text-sm"
              value={dateCible}
              onChange={(e) => setDateCible(e.target.value)}
              aria-label="Date cible"
            />
          </div>

          <div>
            <label className="block text-xs font-medium text-slate-600">Horizon (jours)</label>
            <input
              type="number"
              min={1}
              className="mt-1 w-full rounded-md border bg-white px-3 py-2 text-sm"
              value={horizon}
              onChange={(e) => setHorizon(Number(e.target.value))}
              aria-label="Horizon"
            />
          </div>

          <div className="flex items-end">
            <button
              onClick={() => {
                // eslint-disable-next-line @typescript-eslint/no-floating-promises
                lancer()
              }}
              className="w-full rounded-md bg-emerald-600 px-4 py-2 text-sm font-semibold text-white hover:bg-emerald-700 disabled:opacity-50"
              disabled={loading}
            >
              {loading ? 'Génération…' : 'Générer besoins'}
            </button>
          </div>
        </div>

        {resultat && (
          <div className="mt-4 rounded-lg bg-slate-50 p-3 text-sm">
            <div className="font-medium">Commandes créées</div>
            <ul className="mt-2 list-disc pl-5">
              {resultat.map((id) => (
                <li key={id}>{id}</li>
              ))}
            </ul>
          </div>
        )}
      </div>

      <div className="rounded-xl border bg-white p-4 shadow-sm">
        <div className="text-sm font-semibold">Prochaine étape</div>
        <p className="mt-2 text-sm text-slate-600">
          On ajoutera l’UI type Inpulse pour éditer les lignes (quantité +/-), puis envoyer la commande et télécharger le PDF.
        </p>
      </div>
    </div>
  )
}
