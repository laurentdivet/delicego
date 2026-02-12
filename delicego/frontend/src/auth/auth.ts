export type Session = {
  token: string
}

const STORAGE_KEY = 'delicego_token'
export const INTERNAL_TOKEN_KEY = 'INTERNAL_TOKEN'

export function lireSession(): Session | null {
  const token = localStorage.getItem(STORAGE_KEY)
  if (!token) return null
  return { token }
}

export function enregistrerToken(token: string): void {
  localStorage.setItem(STORAGE_KEY, token)
}

export function deconnecter(): void {
  localStorage.removeItem(STORAGE_KEY)
}

export function fournirToken(): string | null {
  return localStorage.getItem(STORAGE_KEY)
}

export function fournirTokenInterne(): string | null {
  return localStorage.getItem(INTERNAL_TOKEN_KEY)
}

export function enregistrerTokenInterne(token: string): void {
  localStorage.setItem(INTERNAL_TOKEN_KEY, token)
}

export function effacerTokenInterne(): void {
  localStorage.removeItem(INTERNAL_TOKEN_KEY)
}
