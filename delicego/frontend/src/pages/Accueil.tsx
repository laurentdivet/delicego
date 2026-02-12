import { useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'

import { listerMagasins, listerMenus, passerCommande, type MagasinClient, type MenuClient, type ErreurApi } from '../api/client'
import { CommandeForm } from '../components/CommandeForm'
import { MenuList } from '../components/MenuList'
import { Panier } from '../components/Panier'
import type { LignePanier } from '../types'

export function Accueil() {
  const navigate = useNavigate()

  const [menus, setMenus] = useState<MenuClient[]>([])
  const [chargementMenus, setChargementMenus] = useState(false)
  const [erreurMenus, setErreurMenus] = useState<string | null>(null)

  const [magasins, setMagasins] = useState<MagasinClient[]>([])
  const [magasinId, setMagasinId] = useState('')

  const [quantites, setQuantites] = useState<Record<string, number>>({})
  const [erreurCommande, setErreurCommande] = useState<string | null>(null)

  useEffect(() => {
    async function charger() {
      setChargementMenus(true)
      setErreurMenus(null)
      try {
        const [dataMagasins, dataMenus] = await Promise.all([listerMagasins(), listerMenus()])
        setMagasins(dataMagasins)
        setMenus(dataMenus)
        if (!magasinId && dataMagasins.length > 0) {
          setMagasinId(dataMagasins[0].id)
        }
      } catch (err) {
        const e = err as ErreurApi
        setErreurMenus(e?.message || 'Impossible de charger les données.')
      } finally {
        setChargementMenus(false)
      }
    }

    charger()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const lignesPanier: LignePanier[] = useMemo(() => {
    const mapNom = new Map(menus.map((m) => [m.id, m.nom]))
    return Object.entries(quantites)
      .filter(([, q]) => q > 0)
      .map(([menu_id, quantite]) => ({
        menu_id,
        nom: mapNom.get(menu_id) || 'Menu',
        quantite,
      }))
      .sort((a, b) => a.nom.localeCompare(b.nom))
  }, [menus, quantites])

  function incrementer(menu_id: string) {
    setQuantites((q) => ({ ...q, [menu_id]: (q[menu_id] || 0) + 1 }))
  }

  function decrementer(menu_id: string) {
    setQuantites((q) => ({ ...q, [menu_id]: Math.max(0, (q[menu_id] || 0) - 1) }))
  }

  function supprimer(menu_id: string) {
    setQuantites((q) => {
      const copie = { ...q }
      delete copie[menu_id]
      return copie
    })
  }

  async function envoyerCommande({ commentaire }: { commentaire: string }) {
    setErreurCommande(null)

    const lignes = lignesPanier.map((l) => ({ menu_id: l.menu_id, quantite: l.quantite }))

    return passerCommande({
      magasin_id: magasinId,
      lignes,
      commentaire: commentaire || null,
    })
  }

  return (
    <main className="mx-auto max-w-5xl p-6">
      <header className="mb-6">
        <h1 className="text-2xl font-bold">DéliceGo – Commande en ligne</h1>
        <p className="text-sm text-slate-600">
          Interface client simple : elle consomme uniquement <code>/api/client</code>.
        </p>
      </header>

      {erreurCommande && (
        <div className="mb-4 rounded border border-red-200 bg-red-50 p-3 text-sm text-red-700">
          {erreurCommande}
        </div>
      )}

      <div className="mb-6 rounded-lg border bg-white p-4 shadow-sm">
        <label className="mb-1 block text-sm font-medium" htmlFor="magasinId">
          Magasin
        </label>
        <select
          id="magasinId"
          className="w-full rounded border p-2 text-sm"
          value={magasinId}
          onChange={(e) => setMagasinId(e.target.value)}
        >
          {magasins.length === 0 ? (
            <option value="">Aucun magasin</option>
          ) : (
            magasins.map((m) => (
              <option key={m.id} value={m.id}>
                {m.nom}
              </option>
            ))
          )}
        </select>
        <p className="mt-2 text-xs text-slate-600">Choisis le magasin (seed démo disponible via `backend/scripts/seed_demo.py`).</p>
      </div>

      <div className="grid gap-6 md:grid-cols-2">
        <MenuList
          menus={menus}
          quantites={quantites}
          surIncrementer={incrementer}
          surDecrementer={decrementer}
          chargement={chargementMenus}
          erreur={erreurMenus}
        />

        <div className="space-y-6">
          <Panier
            lignes={lignesPanier}
            surIncrementer={incrementer}
            surDecrementer={decrementer}
            surSupprimer={supprimer}
          />

          <CommandeForm
            magasinId={magasinId}
            lignes={lignesPanier}
            envoyerCommande={envoyerCommande}
            onErreur={setErreurCommande}
            onCommandeSucces={(rep) => {
              // Reset panier
              setQuantites({})
              navigate(`/confirmation?commande_client_id=${encodeURIComponent(rep.commande_client_id)}`)
            }}
          />
        </div>
      </div>
    </main>
  )
}
