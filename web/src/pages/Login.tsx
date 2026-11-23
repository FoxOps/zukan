import { useQueryClient } from '@tanstack/react-query'
import { useEffect, useState, type FormEvent } from 'react'
import { useTranslation } from 'react-i18next'
import { useNavigate, useSearchParams } from 'react-router'
import { api, call, markSignedIn } from '../api/client'
import { meQuery, useProviders } from '../api/queries'
import { LanguageMenu } from '../components/I18n'
import { Logo } from '../components/Logo'
import { Eyebrow } from '../components/Page'

/** Only same-site paths, never `//host` (open redirect). */
function safeNext(next: string | null): string {
  return next && next.startsWith('/') && !next.startsWith('//') ? next : '/'
}

export default function Login() {
  const { t } = useTranslation()
  const [params] = useSearchParams()
  const next = safeNext(params.get('next'))
  const providers = useProviders()
  const navigate = useNavigate()
  const client = useQueryClient()
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(params.get('error'))
  const [busy, setBusy] = useState(false)

  const submit = async (e: FormEvent) => {
    e.preventDefault()
    setBusy(true)
    setError(null)
    try {
      await call(api.POST('/api/auth/login', { body: { username, password, mode: 'cookie' } }))
      markSignedIn()
      // Drop everything cached for the old session, then load `me` before the guard
      // reads it: no stale 401 can send the user back here.
      await client.cancelQueries()
      client.removeQueries()
      await client.fetchQuery(meQuery)
      navigate(next, { replace: true })
    } catch (err) {
      setError((err as Error).message)
    } finally {
      setBusy(false)
    }
  }

  const sso = providers.data?.providers ?? []
  // Unknown until the providers answer: no form meanwhile, so an SSO password is never
  // typed into it before the page turns out to be SSO only.
  const local = providers.data?.local_login_enabled ?? false
  const ssoHref = (name: string) =>
    `/api/auth/oidc/${encodeURIComponent(name)}/login?next=${encodeURIComponent(next)}`
  // Single sign-on only: straight to the identity provider. Not after an SSO error, nor
  // after logging out (the provider's session would sign the user in again at once).
  const only = !local && sso.length === 1 && !params.has('error') && !params.has('logged_out') ? sso[0] : null
  const redirectTo = only ? ssoHref(only.name) : null
  useEffect(() => {
    if (redirectTo) window.location.replace(redirectTo)
  }, [redirectTo])

  if (providers.isPending) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-base-200 p-4">
        <span className="loading loading-spinner loading-lg" aria-label={t('Loading')} />
      </div>
    )
  }

  if (only) {
    return (
      <div className="flex min-h-screen flex-col items-center justify-center gap-3 bg-base-200 p-4">
        <span className="loading loading-spinner loading-lg" />
        <p className="text-base-content/70">{t('Redirecting to {{provider}}…', { provider: only.display_name })}</p>
      </div>
    )
  }

  return (
    <div className="grid min-h-screen bg-base-200 lg:grid-cols-2">
      {/* Brand half: the cream signature on chocolate (large screens only). */}
      <div className="hidden flex-col justify-center gap-8 bg-neutral px-16 text-neutral-content lg:flex">
        <Logo onDark className="w-[200px]" />
        <div>
          <p className="font-display text-5xl font-extrabold leading-tight">
            {t('All your cards.')}
            <br />
            {t('One familiar place.')}
          </p>
          <p className="mt-4 max-w-md text-lg text-neutral-content/80">{t('Explore your games. Organize every printing. Keep your collection close.')}</p>
        </div>
      </div>
      <main className="flex items-center justify-center px-4 py-10">
        <div className="flex w-full max-w-sm flex-col gap-5">
          <div className="flex items-center justify-between gap-2">
            <Logo className="w-[180px] lg:hidden" />
            <div className="ml-auto">
              <LanguageMenu signedIn={false} />
            </div>
          </div>
          <div>
            <Eyebrow>{t('Welcome back')}</Eyebrow>
            <h1 className="mt-2 text-3xl">{t('Log in to Zukan')}</h1>
            <p className="mt-1 text-base-content/70">{t('Your collection is waiting.')}</p>
          </div>
          {error && <div role="alert" className="alert alert-error alert-soft">{error}</div>}
          {providers.isError && (
            <div role="alert" className="alert alert-error alert-soft">
              <span>{t('Could not load the sign-in options.')}</span>
              <button type="button" className="btn btn-sm" onClick={() => providers.refetch()}>
                {t('Try again')}
              </button>
            </div>
          )}
          {local && (
            <form onSubmit={submit} className="flex flex-col gap-4">
              <label className="flex flex-col gap-1.5">
                <span className="text-sm font-semibold">{t('User')}</span>
                <input className="input w-full" autoComplete="username" required value={username} onChange={(e) => setUsername(e.target.value)} />
              </label>
              <label className="flex flex-col gap-1.5">
                <span className="text-sm font-semibold">{t('Password')}</span>
                <input className="input w-full" type="password" autoComplete="current-password" required value={password} onChange={(e) => setPassword(e.target.value)} />
              </label>
              <button className="btn btn-primary min-h-11" disabled={busy}>
                {busy && <span className="loading loading-spinner loading-sm" />}
                {t('Log in')}
              </button>
            </form>
          )}
          {local && sso.length > 0 && <div className="divider my-0">{t('or')}</div>}
          {sso.map((p) => (
            <a key={p.name} className={`btn min-h-11 ${local ? '' : 'btn-primary'}`} href={ssoHref(p.name)}>
              {!local && sso.length === 1 ? t('Log in') : t('Sign in with {{provider}}', { provider: p.display_name })}
            </a>
          ))}
        </div>
      </main>
    </div>
  )
}
