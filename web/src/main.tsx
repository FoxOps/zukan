import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { StrictMode, type ComponentType } from 'react'
import { createRoot } from 'react-dom/client'
import { createBrowserRouter, RouterProvider } from 'react-router'
import { ApiError } from './api/client'
import { Layout } from './components/Layout'
import { ToastProvider } from './components/Toasts'
import './i18n'
import './index.css'
import Login from './pages/Login'
import NotFound from './pages/NotFound'

/** Route modules are loaded on first visit (charts and tables stay out of the login bundle). */
function page(load: () => Promise<{ default: ComponentType }>) {
  return async () => ({ Component: (await load()).default })
}

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      // Do not retry client errors (404, 403...), only transient failures.
      retry: (count, error) => !(error instanceof ApiError && error.status < 500) && count < 2,
      refetchOnWindowFocus: false,
    },
  },
})

const router = createBrowserRouter([
  { path: '/login', element: <Login /> },
  {
    element: <Layout />,
    HydrateFallback: () => <span className="loading loading-spinner loading-lg m-auto block" />,
    children: [
      { path: '/', lazy: page(() => import('./pages/Dashboard')) },
      { path: '/collection', lazy: page(() => import('./pages/Collection')) },
      { path: '/catalog', lazy: page(() => import('./pages/Catalog')) },
      { path: '/cards/:cardId', lazy: page(() => import('./pages/CardDetail')) },
      { path: '/import', lazy: page(() => import('./pages/ImportExport')) },
      { path: '/settings', lazy: page(() => import('./pages/Settings')) },
      { path: '/admin/users', lazy: page(() => import('./pages/admin/Users')) },
      { path: '/admin/jobs', lazy: page(() => import('./pages/admin/Jobs')) },
      { path: '/admin/checks', lazy: page(() => import('./pages/admin/Checks')) },
      { path: '*', element: <NotFound /> },
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
