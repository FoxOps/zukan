import { QueryCache, QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { StrictMode, type ComponentType } from 'react'
import { createRoot } from 'react-dom/client'
import { createBrowserRouter, RouterProvider } from 'react-router'
import { ApiError, serverDown } from './api/client'
import { Layout } from './components/Layout'
import ErrorPage from './components/ErrorPage'
import { ToastProvider } from './components/Toasts'
import { showError } from './components/toast'
import './i18n'
import './index.css'
import { applyTheme, savedDark } from './lib/theme'
import Login from './pages/Login'

// Before the first render, so the login page uses the saved theme too.
applyTheme(savedDark())

/** Route modules are loaded on first visit (charts and tables stay out of the login bundle). */
function page(load: () => Promise<{ default: ComponentType }>) {
  return async () => ({ Component: (await load()).default })
}

const queryClient = new QueryClient({
  // Failed loads are shown as toasts, except where the page shows them itself
  // (`meta.inlineError`), expired sessions (the login page opens) and a server down or in
  // maintenance (no answer, 502-504: the maintenance page opens once the health check
  // confirms it).
  queryCache: new QueryCache({
    onError: (error, query) => {
      if (serverDown(error)) {
        // The health check's own failure must not start it again (request loop); several
        // failures at once share one check (a running one is not restarted).
        if (query.queryKey[0] !== 'health') {
          void queryClient.invalidateQueries({ queryKey: ['health'] }, { cancelRefetch: false })
        }
        return
      }
      if (query.meta?.inlineError || (error instanceof ApiError && error.status === 401)) return
      showError(error.message)
    },
  }),
  defaultOptions: {
    queries: {
      // Do not retry client errors (404, 403...), only transient failures.
      retry: (count, error) =>
        !(error instanceof ApiError && (error.status < 500 || error.status === 503)) && count < 2,
      refetchOnWindowFocus: false,
    },
  },
})

const router = createBrowserRouter([
  { path: '/login', element: <Login />, errorElement: <ErrorPage /> },
  {
    element: <Layout />,
    errorElement: <ErrorPage />,
    HydrateFallback: () => <span className="loading loading-spinner loading-lg m-auto block" />,
    children: [
      { path: '/', lazy: page(() => import('./pages/Dashboard')) },
      { path: '/collection', lazy: page(() => import('./pages/Collection')) },
      { path: '/catalog', lazy: page(() => import('./pages/Catalog')) },
      { path: '/finance', lazy: page(() => import('./pages/Finance')) },
      { path: '/binder', lazy: page(() => import('./pages/Binder')) },
      { path: '/binder/:binderId', lazy: page(() => import('./pages/binder/Detail')) },
      { path: '/decks', lazy: page(() => import('./pages/Decks')) },
      { path: '/decks/:deckId', lazy: page(() => import('./pages/decks/Detail')) },
      { path: '/cards/:cardId', lazy: page(() => import('./pages/CardDetail')) },
      { path: '/cards/:cardId/:printingId', lazy: page(() => import('./pages/CardDetail')) },
      { path: '/import', lazy: page(() => import('./pages/ImportExport')) },
      { path: '/settings', lazy: page(() => import('./pages/Settings')) },
      { path: '/about', lazy: page(() => import('./pages/About')) },
      { path: '/admin/users', lazy: page(() => import('./pages/admin/Users')) },
      { path: '/admin/groups', lazy: page(() => import('./pages/admin/Groups')) },
      { path: '/admin/jobs', lazy: page(() => import('./pages/admin/Jobs')) },
      { path: '/admin/checks', lazy: page(() => import('./pages/admin/Checks')) },
      { path: '/admin/server', lazy: page(() => import('./pages/admin/Server')) },
      { path: '*', lazy: page(() => import('./pages/NotFound')) },
    ],
  },
])

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>

        <ToastProvider>
          <RouterProvider router={router} />
        </ToastProvider>

    </QueryClientProvider>
  </StrictMode>,
)
