import type { MenuClient } from '../api/client'

type Props = {
  menus: MenuClient[]
  quantites: Record<string, number>
  surIncrementer: (menu_id: string) => void
  surDecrementer: (menu_id: string) => void
  chargement?: boolean
  erreur?: string | null
}

export function MenuList({
  menus,
  quantites,
  surIncrementer,
  surDecrementer,
  chargement,
  erreur,
}: Props) {
  return (
    <section className="rounded-lg border bg-white p-4 shadow-sm">
      <h2 className="mb-3 text-lg font-semibold">Menus disponibles</h2>

      {chargement && <p className="text-sm text-slate-600">Chargement…</p>}
      {erreur && (
        <p className="rounded bg-red-50 p-2 text-sm text-red-700">{erreur}</p>
      )}

      {!chargement && !erreur && menus.length === 0 && (
        <p className="text-sm text-slate-600">Aucun menu disponible pour le moment.</p>
      )}

      <ul className="space-y-3">
        {menus.map((m) => {
          const qte = quantites[m.id] || 0
          const desactive = !m.actif || !m.disponible

          return (
            <li
              key={m.id}
              className="flex items-center justify-between gap-4 rounded border p-3"
            >
              <div>
                <p className="font-medium">
                  {m.nom}{' '}
                  {!m.disponible && (
                    <span className="ml-2 rounded bg-slate-100 px-2 py-0.5 text-xs font-medium text-slate-600">
                      Indisponible
                    </span>
                  )}
                </p>
                <p className="text-xs text-slate-600">
                  {m.prix.toFixed(2)} €
                  {m.description ? ` • ${m.description}` : ''}
                </p>
              </div>

              <div className="flex items-center gap-2">
                <button
                  className="rounded border px-3 py-1 text-sm disabled:opacity-50"
                  onClick={() => surDecrementer(m.id)}
                  disabled={desactive || qte <= 0}
                >
                  –
                </button>
                <span className="w-8 text-center text-sm">{qte}</span>
                <button
                  className="rounded border px-3 py-1 text-sm disabled:opacity-50"
                  onClick={() => surIncrementer(m.id)}
                  disabled={desactive}
                >
                  +
                </button>
              </div>
            </li>
          )
        })}
      </ul>
    </section>
  )
}
