import { useState } from 'react'

import { NavLink, Outlet, useLocation } from 'react-router-dom'

function Item({ to, label, indent = false }: { to: string; label: string; indent?: boolean }) {
  return (
    <NavLink
      to={to}
      className={({ isActive }) =>
        [
          'flex items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium',
          indent ? 'pl-8' : '',
          isActive ? 'bg-emerald-500/15 text-emerald-300' : 'text-slate-200 hover:bg-white/5',
        ].join(' ')
      }
    >
      <span className="h-2 w-2 rounded-full bg-emerald-400" />
      {label}
    </NavLink>
  )
}

function Section({
  label,
  ouvert,
  onToggle,
  children,
}: {
  label: string
  ouvert: boolean
  onToggle: () => void
  children: React.ReactNode
}) {
  return (
    <div className="mt-2">
      <button
        type="button"
        onClick={onToggle}
        className="flex w-full items-center justify-between rounded-lg px-3 py-2 text-left text-sm font-semibold text-slate-100 hover:bg-white/5"
      >
        <span>{label}</span>
        <span className="text-slate-300">{ouvert ? '▾' : '▸'}</span>
      </button>
      {ouvert && <div className="mt-1 space-y-1">{children}</div>}
    </div>
  )
}

export function AppLayout() {
  const location = useLocation()

  const [opsOpen, setOpsOpen] = useState<boolean>(location.pathname.startsWith('/operations'))
  const [analysesOpen, setAnalysesOpen] = useState<boolean>(location.pathname.startsWith('/analyses'))

  return (
    <div className="min-h-screen bg-slate-50">
      <div className="flex min-h-screen">
        <aside className="w-56 bg-slate-900 text-white">
          <div className="border-b border-white/10 px-4 py-4">
            <div className="text-lg font-semibold tracking-tight">delicego</div>
            <div className="text-xs text-slate-400">inpulse-like UI (MVP)</div>
          </div>

          <nav className="p-3 space-y-1">
            {/* Sections existantes */}
            <Item to="/dashboard" label="Tableau de bord" />
            <Item to="/impact" label="Impact (pilotage)" />
            <Item to="/cuisine" label="Cuisine" />
            <Item to="/achats" label="Achats" />
            <Item to="/" label="Commande client" />

            {/* Nouvelles sections (accordéon) */}
            <Section label="Opérations" ouvert={opsOpen} onToggle={() => setOpsOpen((v) => !v)}>
              <Item to="/operations/production-jour" label="Production du jour" indent />
              <Item to="/operations/production" label="Production" indent />
              <Item to="/operations/stocks" label="Stocks" indent />
              <Item to="/operations/pertes" label="Pertes" indent />
              <Item to="/operations/commandes" label="Commandes" indent />
              <Item to="/operations/inventaires" label="Inventaires" indent />
              <Item to="/operations/transferts" label="Transferts" indent />
            </Section>

            <Section label="Analyses" ouvert={analysesOpen} onToggle={() => setAnalysesOpen((v) => !v)}>
              <Item to="/analyses/par-vitrine" label="Par vitrine" indent />
              <Item to="/analyses/par-categorie" label="Par catégorie" indent />
              <Item to="/analyses/par-ingredient" label="Par ingrédient" indent />
              <Item to="/analyses/fournisseurs" label="Fournisseurs" indent />
              <Item to="/analyses/evolution-des-prix" label="Évolution des prix" indent />
              <Item to="/analyses/stocks-prevus" label="Stocks prévus" indent />
              <Item to="/analyses/stocks-passes" label="Stocks passés" indent />
              <Item to="/analyses/conso-ingredients" label="Conso ingrédients" indent />
            </Section>
          </nav>
        </aside>

        <div className="flex-1">
          <header className="sticky top-0 z-10 border-b bg-white/70 px-6 py-4 backdrop-blur">
            <div className="flex items-center justify-between">
              <div>
                <div className="text-sm text-slate-500">DéliceGo</div>
                <div className="text-xl font-semibold">Console</div>
              </div>
              <div className="text-xs text-slate-500">Dev</div>
            </div>
          </header>

          <main className="px-6 py-6">
            <Outlet />
          </main>
        </div>
      </div>
    </div>
  )
}
