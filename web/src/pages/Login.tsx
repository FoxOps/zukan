import { useQueryClient } from '@tanstack/react-query'
import { useState, type FormEvent } from 'react'
import { useNavigate, useSearchParams } from 'react-router'
import { api, call } from '../api/client'
import { useProviders } from '../api/queries'

/** Only same-site paths, never `//host` (open redirect). */
function safeNext(next: string | null): string {
  return next && next.startsWith('/') && !next.startsWith('//') ? next : '/'
}

export default function Login() {
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
      await client.invalidateQueries({ queryKey: ['me'] })
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
          <h1 className="card-title text-2xl">
            Fudabako <span className="text-base font-normal text-base-content/50" lang="ja">札箱</span>
          </h1>
          {error && <div role="alert" className="alert alert-error alert-soft">{error}</div>}
          {local && (
            <form onSubmit={submit} className="flex flex-col gap-3">
              <label className="input w-full">
                <span className="label">User</span>
                <input autoComplete="username" required value={username} onChange={(e) => setUsername(e.target.value)} />
              </label>
              <label className="input w-full">
                <span className="label">Password</span>
                <input type="password" autoComplete="current-password" required value={password} onChange={(e) => setPassword(e.target.value)} />
              </label>
              <button className="btn btn-primary" disabled={busy}>
                {busy && <span className="loading loading-spinner loading-sm" />}Log in
              </button>
            </form>
          )}
          {local && sso.length > 0 && <div className="divider my-0">or</div>}
          {sso.map((p) => (
            <a
              key={p.name}
              className="btn btn-outline"
              href={`/api/auth/oidc/${encodeURIComponent(p.name)}/login?next=${encodeURIComponent(next)}`}
            >
              Sign in with {p.display_name}
            </a>
          ))}
        </div>
      </div>
    </div>
  )
}
