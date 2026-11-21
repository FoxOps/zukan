import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { isRouteErrorResponse, Link, useRouteError } from 'react-router'
import { ApiError } from '../api/client'
import { MaintenanceScreen } from './Maintenance'

/** A page-sized error in the app's theme, with what can be done about it. */
export function ErrorScreen({ title, text, onRetry, home = true }: { title: string; text?: string; onRetry?: () => void; home?: boolean }) {
  const { t } = useTranslation()
  return (
    <div className="hero min-h-[60vh] bg-base-100">
      <div className="hero-content text-center">
        <div className="card max-w-md bg-base-200 shadow-sm">
          <div className="card-body items-center gap-3">
            <h1 className="card-title text-2xl">{title}</h1>
            {text && <p className="text-base-content/70">{text}</p>}
            <div className="card-actions mt-2">
              {onRetry && (
                <button className="btn btn-primary" onClick={onRetry}>
                  {t('Try again')}
                </button>
              )}
              {home && (
                <Link to="/" className={`btn ${onRetry ? 'btn-ghost' : 'btn-primary'}`} reloadDocument>
                  {t('Back to dashboard')}
                </Link>
              )}
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}

/** Route error element: unknown pages, failed page loads and rendering errors. */
export default function ErrorPage() {
  const { t } = useTranslation()
  const error = useRouteError()
  if (isRouteErrorResponse(error) && error.status === 404) return <ErrorScreen title={t('Not found')} />
  const message = error instanceof Error ? error.message : ''
  if (/dynamically imported module|module script failed|Loading chunk/i.test(message)) return <PageCodeMissing />
  // Anything else (server restarting or failing, page error): the calm maintenance page,
  // details only in the console.
  if (!(error instanceof ApiError)) console.error(error)
  return <MaintenanceScreen />
}

/** Page code not loaded: the server is down (restart, update in progress), or answers
 * and removed it with an update (new version). */
function PageCodeMissing() {
  const { t } = useTranslation()
  const [reachable, setReachable] = useState<boolean | null>(null)
  useEffect(() => {
    fetch('/api/health', { cache: 'no-store' })
      .then((r) => setReachable(r.ok))
      .catch(() => setReachable(false))
  }, [])
  if (reachable === null) return <span className="loading loading-spinner loading-lg m-auto block" />
  if (!reachable) return <MaintenanceScreen />
  return (
    <ErrorScreen
      title={t('A new version is available')}
      text={t('Reload the page to use it.')}
      onRetry={() => window.location.reload()}
      home={false}
    />
  )
}
