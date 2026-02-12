type Props = {
  titre: string
  description?: string
}

export function Placeholder({ titre, description }: Props) {
  return (
    <div className="space-y-2">
      <h1 className="text-2xl font-semibold">{titre}</h1>
      <p className="text-sm text-slate-600">{description || 'Écran à venir.'}</p>
      <div className="rounded-lg border bg-white p-4 text-sm text-slate-600">
        <div className="font-medium">À venir</div>
        <div className="mt-1">
          Cet écran est prévu dans l’arborescence (inspiration Inpulse) mais n’est pas encore implémenté.
        </div>
      </div>
    </div>
  )
}
