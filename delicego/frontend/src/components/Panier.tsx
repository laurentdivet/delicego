import type { LignePanier } from '../types'

type Props = {
  lignes: LignePanier[]
  surIncrementer: (menu_id: string) => void
  surDecrementer: (menu_id: string) => void
  surSupprimer: (menu_id: string) => void
}

export function Panier({ lignes, surIncrementer, surDecrementer, surSupprimer }: Props) {
  const totalArticles = lignes.reduce((acc, l) => acc + l.quantite, 0)

  return (
    <section className="rounded-lg border bg-white p-4 shadow-sm">
      <h2 className="mb-3 text-lg font-semibold">Panier</h2>

      {lignes.length === 0 ? (
        <p className="text-sm text-slate-600">Votre panier est vide.</p>
      ) : (
        <>
          <p className="mb-3 text-sm text-slate-600">{totalArticles} article(s)</p>
          <ul className="space-y-3">
            {lignes.map((l) => (
              <li key={l.menu_id} className="rounded border p-3">
                <div className="flex items-start justify-between gap-4">
                  <div>
                    <p className="font-medium">{l.nom}</p>
                    <p className="text-xs text-slate-600">Quantité : {l.quantite}</p>
                  </div>

                  <button
                    className="text-sm text-red-700 hover:underline"
                    onClick={() => surSupprimer(l.menu_id)}
                  >
                    Supprimer
                  </button>
                </div>

                <div className="mt-3 flex items-center gap-2">
                  <button
                    className="rounded border px-3 py-1 text-sm"
                    onClick={() => surDecrementer(l.menu_id)}
                    disabled={l.quantite <= 0}
                  >
                    –
                  </button>
                  <span className="w-8 text-center text-sm">{l.quantite}</span>
                  <button
                    className="rounded border px-3 py-1 text-sm"
                    onClick={() => surIncrementer(l.menu_id)}
                  >
                    +
                  </button>
                </div>
              </li>
            ))}
          </ul>
        </>
      )}
    </section>
  )
}
