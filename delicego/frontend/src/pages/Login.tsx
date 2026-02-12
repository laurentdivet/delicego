import { useMemo, useState } from 'react'

import { useNavigate } from 'react-router-dom'

function boolEnv(v: unknown): boolean {
  return String(v || '').trim().toLowerCase() === '1' || String(v || '').trim().toLowerCase() === 'true'
}

function useInternalApi(): boolean {
  return boolEnv(import.meta.env.VITE_USE_INTERNAL_API)
}

export function Login() {
  const navigate = useNavigate()

  const internal = useInternalApi()

  const [tokenInterne, setTokenInterne] = useState<string>(() => localStorage.getItem('INTERNAL_TOKEN') || '')
  const [erreur, setErreur] = useState<string | null>(null)
  const [chargement, setChargement] = useState(false)

  const tokenPresent = useMemo(() => Boolean(tokenInterne.trim()), [tokenInterne])

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault()
    setErreur(null)
    setChargement(true)

    try {
      // Mode “API interne”: aucun appel réseau. On stocke le token et on redirige.
      if (internal) {
        const t = tokenInterne.trim()
        if (!t) throw new Error('Token invalide ou absent')
        localStorage.setItem('INTERNAL_TOKEN', t)
        navigate('/impact', { replace: true })
        return
      }

      // Mode standard (JWT) non supporté pour le moment.
      throw new Error('Connexion JWT indisponible. Active VITE_USE_INTERNAL_API=1 pour utiliser un token interne.')
    } catch (err) {
      setErreur(err instanceof Error ? err.message : 'Erreur de connexion')
    } finally {
      setChargement(false)
    }
  }

  return (
    <div className="mx-auto max-w-md">
      <h1 className="text-2xl font-semibold text-slate-900">Connexion</h1>
      <p className="mt-1 text-sm text-slate-600">
        {internal ? (
          <>
            Accès interne (<span className="font-mono">Authorization: Bearer &lt;token&gt;</span>)
          </>
        ) : (
          <>Email + mot de passe (JWT)</>
        )}
      </p>

      <form onSubmit={onSubmit} className="mt-6 space-y-4 rounded-xl border bg-white p-5 shadow-sm">
        {internal ? (
          <div>
            <label className="text-sm font-medium text-slate-700">Token interne</label>
            <input
              placeholder="ton-token"
              className="mt-1 w-full rounded-lg border px-3 py-2 font-mono"
              value={tokenInterne}
              onChange={(e) => setTokenInterne(e.target.value)}
              autoComplete="off"
            />
            <div className="mt-1 text-xs text-slate-500">
              Ce token sera stocké en local (<span className="font-mono">localStorage.INTERNAL_TOKEN</span>) et envoyé automatiquement vers{' '}
              <span className="font-mono">/api/interne/*</span>.
            </div>
          </div>
        ) : (
          <div className="rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-900">
            Le backend n’implémente pas la connexion JWT. Lance le frontend avec{' '}
            <span className="font-mono">VITE_USE_INTERNAL_API=1</span> pour utiliser un token interne.
          </div>
        )}

        {erreur && <div className="rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">{erreur}</div>}

        <button
          type="submit"
          disabled={chargement}
          className="w-full rounded-lg bg-slate-900 px-4 py-2 text-sm font-semibold text-white disabled:opacity-60"
        >
          {chargement ? 'Enregistrement…' : internal ? 'Enregistrer' : 'Se connecter'}
        </button>

        {internal && (
          <div className="text-xs text-slate-500">
            Statut: {tokenPresent ? <span className="text-emerald-700">token présent</span> : <span className="text-amber-700">token manquant</span>}
          </div>
        )}
      </form>
    </div>
  )
}
