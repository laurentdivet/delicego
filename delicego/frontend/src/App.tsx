import { Navigate, Route, Routes } from 'react-router-dom'

import { ProtectedRoute } from './auth/ProtectedRoute'
import { AppLayout } from './layouts/AppLayout'
import { Login } from './pages/Login'
import { Accueil } from './pages/Accueil'
import { Achats } from './pages/Achats'
import { Cuisine } from './pages/Cuisine'
import { Confirmation } from './pages/Confirmation'
import { Dashboard } from './pages/Dashboard'
import { ImpactDashboard } from './pages/ImpactDashboard'
import { Placeholder } from './pages/Placeholder'
import { ProductionJour } from './pages/ProductionJour'
import { ProductionScan } from './pages/ProductionScan'

function boolEnv(v: unknown): boolean {
  return String(v || '').trim().toLowerCase() === '1' || String(v || '').trim().toLowerCase() === 'true'
}

function useInternalApi(): boolean {
  return boolEnv(import.meta.env.VITE_USE_INTERNAL_API)
}

function tokenInternePresent(): boolean {
  return Boolean((localStorage.getItem('INTERNAL_TOKEN') || '').trim())
}

export default function App() {
  const internal = useInternalApi()

  return (
    <Routes>
      {/* Mode API interne: si un token est déjà présent, /login devient inutile -> /impact */}
      <Route path="/login" element={internal && tokenInternePresent() ? <Navigate to="/impact" replace /> : <Login />} />

      <Route element={<AppLayout />}>
        <Route element={<ProtectedRoute />}>
          <Route path="/dashboard" element={<Dashboard />} />
          <Route path="/impact" element={<ImpactDashboard />} />
          <Route path="/cuisine" element={<Cuisine />} />
          <Route path="/achats" element={<Achats />} />
          <Route path="/" element={<Accueil />} />
          <Route path="/confirmation" element={<Confirmation />} />

          {/* Opérations (menu Inpulse-like) */}
          <Route path="/operations/production-jour" element={<ProductionJour />} />
          <Route path="/operations/production" element={<ProductionScan />} />
          <Route path="/operations/stocks" element={<Placeholder titre="Stocks" />} />
          <Route path="/operations/pertes" element={<Placeholder titre="Pertes" />} />
          <Route path="/operations/commandes" element={<Placeholder titre="Commandes" />} />
          <Route path="/operations/inventaires" element={<Placeholder titre="Inventaires" />} />
          <Route path="/operations/transferts" element={<Placeholder titre="Transferts" />} />

          {/* Analyses (menu Inpulse-like) */}
          <Route path="/analyses/par-vitrine" element={<Placeholder titre="Analyses – Par vitrine" />} />
          <Route path="/analyses/par-categorie" element={<Placeholder titre="Analyses – Par catégorie" />} />
          <Route path="/analyses/par-ingredient" element={<Placeholder titre="Analyses – Par ingrédient" />} />
          <Route path="/analyses/fournisseurs" element={<Placeholder titre="Analyses – Fournisseurs" />} />
          <Route path="/analyses/evolution-des-prix" element={<Placeholder titre="Analyses – Évolution des prix" />} />
          <Route path="/analyses/stocks-prevus" element={<Placeholder titre="Analyses – Stocks prévus" />} />
          <Route path="/analyses/stocks-passes" element={<Placeholder titre="Analyses – Stocks passés" />} />
          <Route path="/analyses/conso-ingredients" element={<Placeholder titre="Analyses – Conso ingrédients" />} />
        </Route>

        <Route path="*" element={<Navigate to={internal ? '/impact' : '/dashboard'} replace />} />
      </Route>
    </Routes>
  )
}
