// Client API minimal : le frontend ne contient aucune logique métier.

export type MenuClient = {
  id: string
  nom: string
  description?: string | null
  prix: number
  actif: boolean
  disponible: boolean
}

export type LigneCommandeClient = {
  menu_id: string
  quantite: number
}

export type RequeteCommandeClient = {
  magasin_id: string
  lignes: LigneCommandeClient[]
  commentaire?: string | null
}

export type ReponseCommandeClient = {
  commande_client_id: string
  statut: string
}

export type ErreurApi = {
  statut_http: number
  message: string
}

function construireUrl(path: string): string {
  // En dev : on privilégie le proxy Vite (/api -> backend) pour éviter les CORS.
  // En prod : on peut configurer VITE_API_BASE_URL et garder la même API.
  const base = import.meta.env.VITE_API_BASE_URL

  // Si l’URL est relative (ex: "/api"), on reste en relatif.
  if (!base || !base.startsWith('http')) {
    return path
  }

  // En dev (Vite), on préfère toujours le proxy (`/api`) pour éviter les soucis CORS,
  // quel que soit le port réel (5173, 5174, etc.).
  if (import.meta.env.DEV) {
    return path
  }

  return `${base}${path}`
}

async function lireErreur(reponse: Response): Promise<string> {
  try {
    const data = await reponse.json()
    if (data?.detail) return String(data.detail)
    return JSON.stringify(data)
  } catch {
    return await reponse.text()
  }
}

async function requeteJson<T>(
  path: string,
  options?: RequestInit,
): Promise<T> {
  const url = construireUrl(path)
  const reponse = await fetch(url, {
    ...options,
    headers: {
      'Content-Type': 'application/json',
      ...(options?.headers || {}),
    },
  })

  if (!reponse.ok) {
    const message = await lireErreur(reponse)
    const err: ErreurApi = { statut_http: reponse.status, message }
    throw err
  }

  return (await reponse.json()) as T
}

export async function listerMenus(): Promise<MenuClient[]> {
  return requeteJson<MenuClient[]>('/api/client/menus', { method: 'GET' })
}

export type MagasinClient = {
  id: string
  nom: string
}

export async function listerMagasins(): Promise<MagasinClient[]> {
  return requeteJson<MagasinClient[]>('/api/client/magasins', { method: 'GET' })
}

export async function passerCommande(
  requete: RequeteCommandeClient,
): Promise<ReponseCommandeClient> {
  return requeteJson<ReponseCommandeClient>('/api/client/commande', {
    method: 'POST',
    body: JSON.stringify(requete),
  })
}
