import { Link, useSearchParams } from 'react-router-dom'

export function Confirmation() {
  const [params] = useSearchParams()
  const commandeId = params.get('commande_client_id')

  return (
    <main className="mx-auto max-w-xl p-6">
      <div className="rounded-lg border bg-white p-6 shadow-sm">
        <h1 className="mb-2 text-2xl font-bold">Commande confirmée</h1>
        <p className="mb-4 text-sm text-slate-700">
          Merci ! Votre commande a bien été enregistrée.
        </p>

        <div className="rounded border bg-slate-50 p-3">
          <p className="text-xs text-slate-600">Identifiant commande</p>
          <p className="break-all font-mono text-sm">{commandeId || '—'}</p>
        </div>

        <div className="mt-6">
          <Link
            to="/"
            className="inline-flex rounded bg-slate-900 px-4 py-2 text-sm font-semibold text-white"
          >
            Nouvelle commande
          </Link>
        </div>
      </div>
    </main>
  )
}
