type Niveau = 'vert' | 'orange' | 'rouge'

function classesNiveau(niveau?: Niveau) {
  if (niveau === 'vert') return 'border-emerald-200 bg-emerald-50 text-emerald-900'
  if (niveau === 'orange') return 'border-amber-200 bg-amber-50 text-amber-900'
  if (niveau === 'rouge') return 'border-red-200 bg-red-50 text-red-900'
  return 'border-slate-200 bg-white text-slate-900'
}

function badgeNiveau(niveau?: Niveau) {
  if (niveau === 'vert') return 'bg-emerald-600'
  if (niveau === 'orange') return 'bg-amber-600'
  if (niveau === 'rouge') return 'bg-red-600'
  return 'bg-slate-400'
}

function formatPct(pct: number) {
  const s = Intl.NumberFormat('fr-FR', { maximumFractionDigits: 1 }).format(pct)
  return `${pct > 0 ? '+' : ''}${s}%`
}

export function KpiCard(props: {
  titre: string
  valeur: string
  sousTitre?: string
  variationPct?: number | null
  niveau?: Niveau
}) {
  return (
    <div className={`rounded-xl border p-4 shadow-sm ${classesNiveau(props.niveau)}`}>
      <div className="flex items-start justify-between gap-3">
        <div>
          <div className="text-xs font-medium opacity-80">{props.titre}</div>
          <div className="mt-2 text-2xl font-semibold tabular-nums">{props.valeur}</div>
          {props.sousTitre && <div className="mt-1 text-xs opacity-80">{props.sousTitre}</div>}
        </div>

        <div className="flex flex-col items-end gap-2">
          <div className={`h-2 w-2 rounded-full ${badgeNiveau(props.niveau)}`} aria-hidden />
          {props.variationPct !== undefined && props.variationPct !== null && (
            <div className="text-xs tabular-nums opacity-80">{formatPct(props.variationPct)}</div>
          )}
        </div>
      </div>
    </div>
  )
}
