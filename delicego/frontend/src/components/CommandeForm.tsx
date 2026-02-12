import { useMemo, useState } from 'react'

import type { ErreurApi, ReponseCommandeClient } from '../api/client'
import type { LignePanier } from '../types'

type Props = {
  magasinId: string
  lignes: LignePanier[]
  onCommandeSucces: (reponse: ReponseCommandeClient) => void
  onErreur: (message: string) => void
  envoyerCommande: (params: { commentaire: string }) => Promise<ReponseCommandeClient>
}

export function CommandeForm({
  magasinId,
  lignes,
  onCommandeSucces,
  onErreur,
  envoyerCommande,
}: Props) {
  const [commentaire, setCommentaire] = useState('')
  const [envoi, setEnvoi] = useState(false)

  const desactive = useMemo(() => {
    return envoi || !magasinId || lignes.length === 0
  }, [envoi, magasinId, lignes.length])

  async function soumettre(e: React.FormEvent) {
    e.preventDefault()
    if (desactive) return

    setEnvoi(true)
    try {
      const rep = await envoyerCommande({ commentaire })
      onCommandeSucces(rep)
    } catch (err) {
      const eApi = err as ErreurApi
      if (eApi?.statut_http === 409) {
        onErreur(`Commande refusée : ${eApi.message || 'stock insuffisant.'}`)
      } else if (eApi?.statut_http === 400) {
        onErreur(`Données invalides : ${eApi.message || 'vérifiez votre commande.'}`)
      } else {
        onErreur('Une erreur serveur est survenue. Veuillez réessayer.')
      }
    } finally {
      setEnvoi(false)
    }
  }

  return (
    <section className="rounded-lg border bg-white p-4 shadow-sm">
      <h2 className="mb-3 text-lg font-semibold">Finaliser</h2>

      <form onSubmit={soumettre} className="space-y-3">
        <div>
          <label className="mb-1 block text-sm font-medium" htmlFor="commentaire">
            Commentaire (optionnel)
          </label>
          <textarea
            id="commentaire"
            className="w-full rounded border p-2 text-sm"
            rows={3}
            placeholder="Ex : Sans oignons"
            value={commentaire}
            onChange={(e) => setCommentaire(e.target.value)}
          />
        </div>

        <button
          type="submit"
          className="w-full rounded bg-slate-900 px-4 py-2 text-sm font-semibold text-white disabled:opacity-50"
          disabled={desactive}
        >
          {envoi ? 'Commande en cours…' : 'Commander'}
        </button>

        <p className="text-xs text-slate-600">
          Le backend reste la source de vérité. Ce frontend ne fait que consommer l’API.
        </p>
      </form>
    </section>
  )
}
