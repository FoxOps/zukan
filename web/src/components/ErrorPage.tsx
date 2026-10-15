import { useTranslation } from 'react-i18next'
import { isRouteErrorResponse, Link, useRouteError } from 'react-router'
import { ApiError } from '../api/client'

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
  // Page code from an older version, removed by an update of the server.
  if (/dynamically imported module|module script failed|Loading chunk/i.test(message)) {
    return (
      <ErrorScreen
        title={t('A new version is available')}
        text={t('Reload the page to use it.')}
        onRetry={() => window.location.reload()}
        home={false}
      />
    )
  }
  if (error instanceof ApiError) return <ErrorScreen title={t('Something went wrong')} text={error.message} onRetry={() => window.location.reload()} />
  console.error(error)
  return (
    <ErrorScreen
      title={t('Something went wrong')}
      text={t('This page could not be shown. Reload it, and report the problem if it happens again.')}
      onRetry={() => window.location.reload()}
    />
  )
}
