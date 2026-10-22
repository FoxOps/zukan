import { useQueryClient } from '@tanstack/react-query'
import { useState, type FormEvent } from 'react'
import { useTranslation } from 'react-i18next'
import { useNavigate, useSearchParams } from 'react-router'
import { api, call, markSignedIn } from '../api/client'
import { meQuery, useProviders } from '../api/queries'
import { LanguageMenu } from '../components/I18n'
import { Logo } from '../components/Logo'

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
  const local = providers.data?.local_login_enabled ?? true

  return (
    <div className="flex min-h-screen items-center justify-center bg-base-200 p-4">
      <div className="card w-full max-w-sm bg-base-100 shadow-xl animate-in fade-in slide-in-from-bottom-4 duration-500">
        <div className="card-body gap-4">
          <div className="flex items-start justify-between">
            <h1 className="flex flex-col gap-1">
              <Logo className="w-56" />
              <span className="text-sm font-normal text-base-content/60" lang="ja">図鑑</span>
            </h1>
            <LanguageMenu signedIn={false} />
          </div>
          {error && <div role="alert" className="alert alert-error alert-soft">{error}</div>}
          {local && (
            <form onSubmit={submit} className="flex flex-col gap-3">
              <label className="input w-full">
                <span className="label">{t('User')}</span>
                <input autoComplete="username" required value={username} onChange={(e) => setUsername(e.target.value)} />
              </label>
              <label className="input w-full">
                <span className="label">{t('Password')}</span>
                <input type="password" autoComplete="current-password" required value={password} onChange={(e) => setPassword(e.target.value)} />
              </label>
              <button className="btn btn-primary" disabled={busy}>
                {busy && <span className="loading loading-spinner loading-sm" />}
                {t('Log in')}
              </button>
            </form>
          )}
          {local && sso.length > 0 && <div className="divider my-0">{t('or')}</div>}
          {sso.map((p) => (
            <a
              key={p.name}
              className="btn btn-outline"
              href={`/api/auth/oidc/${encodeURIComponent(p.name)}/login?next=${encodeURIComponent(next)}`}
            >
              {t('Sign in with {{provider}}', { provider: p.display_name })}
            </a>
          ))}
        </div>
      </div>
    </div>
  )
}
