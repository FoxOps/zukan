import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useState, type FormEvent } from 'react'
import { api, call } from '../api/client'
import { useMe, useProviders } from '../api/queries'
import { useToast } from '../components/toast'

export default function Settings() {
  const me = useMe()
  const providers = useProviders()
  const toast = useToast()
  const client = useQueryClient()
  const [current, setCurrent] = useState('')
  const [next, setNext] = useState('')

  const password = useMutation({
    mutationFn: () =>
      call(api.POST('/api/auth/password', { body: { current_password: current || null, new_password: next } })),
    onSuccess: () => {
      toast('Password changed')
      setCurrent('')
      setNext('')
      return client.invalidateQueries({ queryKey: ['me'] })
    },
    onError: (e) => toast(e.message, 'error'),
  })
  const unlink = useMutation({
    mutationFn: (id: number) =>
      call(api.DELETE('/api/auth/identities/{identity_id}', { params: { path: { identity_id: id } } })),
    onSuccess: () => {
      toast('SSO account unlinked', 'info')
      return client.invalidateQueries({ queryKey: ['me'] })
    },
    onError: (e) => toast(e.message, 'error'),
  })

  if (!me.data) return null
  const user = me.data
  const sso = providers.data?.providers ?? []
  const linked = new Set(user.identities.map((i) => i.provider))
  const submit = (e: FormEvent) => {
    e.preventDefault()
    password.mutate()
  }

  return (
    <div className="flex max-w-2xl flex-col gap-6">
      <h1 className="text-2xl font-bold">Account</h1>

      <div className="card bg-base-200">
        <div className="card-body">
          <h2 className="card-title">{user.username}</h2>
          <p className="text-sm text-base-content/70">
            {user.email ?? 'No email'} · <span className="badge badge-sm">{user.role}</span>
          </p>
        </div>
      </div>

      <div className="card bg-base-200">
        <form className="card-body" onSubmit={submit}>
          <h2 className="card-title">{user.has_password ? 'Change password' : 'Set a password'}</h2>
          {user.has_password && (
            <label className="fieldset">
              <span className="fieldset-legend">Current password</span>
              <input
                type="password"
                autoComplete="current-password"
                required
                className="input"
                value={current}
                onChange={(e) => setCurrent(e.target.value)}
              />
            </label>
          )}
          <label className="fieldset">
            <span className="fieldset-legend">New password</span>
            <input
              type="password"
              autoComplete="new-password"
              minLength={8}
              required
              className="input"
              value={next}
              onChange={(e) => setNext(e.target.value)}
            />
            <span className="label">At least 8 characters</span>
          </label>
          <div className="card-actions">
            <button className="btn btn-primary" disabled={password.isPending}>
              Save password
            </button>
          </div>
        </form>
      </div>

      {sso.length > 0 && (
        <div className="card bg-base-200">
          <div className="card-body">
            <h2 className="card-title">Single sign-on</h2>
            <ul className="divide-y divide-base-300">
              {user.identities.map((i) => (
                <li key={i.id} className="flex items-center justify-between py-2">
                  <span>
                    {sso.find((p) => p.name === i.provider)?.display_name ?? i.provider}
                    {i.email && <span className="text-sm text-base-content/60"> · {i.email}</span>}
                  </span>
                  <button className="btn btn-ghost btn-sm" disabled={unlink.isPending} onClick={() => unlink.mutate(i.id)}>
                    Unlink
                  </button>
                </li>
              ))}
            </ul>
            <div className="flex flex-wrap gap-2">
              {sso
                .filter((p) => !linked.has(p.name))
                .map((p) => (
                  <a
                    key={p.name}
                    className="btn btn-outline btn-sm"
                    href={`/api/auth/oidc/${encodeURIComponent(p.name)}/login?link=true&next=/settings`}
                  >
                    Link {p.display_name}
                  </a>
                ))}
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
