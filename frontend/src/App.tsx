import { QueryClient, QueryClientProvider, useQueryClient } from '@tanstack/react-query'
import { lazy, Suspense, useEffect, useState } from 'react'
import {
  BrowserRouter,
  Link,
  Navigate,
  Outlet,
  Route,
  Routes,
  useNavigate,
} from 'react-router-dom'
import { api } from './api'
import { AuthPage } from './pages/AuthPage'
import './App.css'

const ApplicationsPage = lazy(() =>
  import('./pages/ApplicationsPage').then((module) => ({ default: module.ApplicationsPage })),
)
const DashboardPage = lazy(() =>
  import('./pages/DashboardPage').then((module) => ({ default: module.DashboardPage })),
)
const ApplicationDetailPage = lazy(() =>
  import('./pages/ApplicationDetailPage').then((module) => ({
    default: module.ApplicationDetailPage,
  })),
)

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: 1,
      refetchOnWindowFocus: false,
    },
  },
})

function ProtectedLayout() {
  const navigate = useNavigate()
  const client = useQueryClient()
  // Always validate the server-side session on entry. The sessionStorage flag
  // is only a UI hint and must never bypass HttpOnly-cookie authentication.
  const [isAuthenticated, setIsAuthenticated] = useState<boolean | null>(null)

  useEffect(() => {
    if (isAuthenticated === null) {
      api.me().then(() => setIsAuthenticated(true)).catch(() => setIsAuthenticated(false))
    }
    const handleExpired = () => {
      setIsAuthenticated(false)
      client.clear()
      navigate('/login?expired=1', { replace: true })
    }
    window.addEventListener('auth:expired', handleExpired)
    return () => window.removeEventListener('auth:expired', handleExpired)
  }, [client, isAuthenticated, navigate])

  if (isAuthenticated === null) return <div className="loading-line">Checking your session…</div>
  if (!isAuthenticated) return <Navigate to="/login" replace />

  const logout = async () => {
    try {
      await api.logout()
    } finally {
      client.clear()
      setIsAuthenticated(false)
      navigate('/login', { replace: true })
    }
  }

  return (
    <div className="app-shell">
      <header className="topbar">
        <Link className="brand" to="/">
          <span className="brand-mark">A</span>
          <span>Applyboard</span>
        </Link>
        <nav className="main-nav" aria-label="Main navigation">
          <Link to="/">Dashboard</Link>
          <Link to="/applications">Applications</Link>
        </nav>
        <button className="button button-quiet" onClick={logout} type="button">
          Sign out
        </button>
      </header>
      <main className="page-content"><Outlet /></main>
    </div>
  )
}

function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <Routes>
          <Route path="/login" element={<AuthPage mode="login" />} />
          <Route path="/register" element={<AuthPage mode="register" />} />
          <Route element={<ProtectedLayout />}>
            <Route path="/" element={<Suspense fallback={<div className="loading-line">Loading dashboard…</div>}><DashboardPage /></Suspense>} />
            <Route path="/applications" element={<Suspense fallback={<div className="loading-line">Loading applications…</div>}><ApplicationsPage /></Suspense>} />
            <Route path="/applications/:applicationId" element={<Suspense fallback={<div className="loading-line">Loading application…</div>}><ApplicationDetailPage /></Suspense>} />
          </Route>
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </BrowserRouter>
    </QueryClientProvider>
  )
}

export default App
