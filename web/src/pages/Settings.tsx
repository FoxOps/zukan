import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useState, type FormEvent } from 'react'
import { useTranslation } from 'react-i18next'
import { api, call, type Schemas } from '../api/client'
import { useGames, useMe, useProviders } from '../api/queries'
import { useToast } from '../components/toast'
import { LANGUAGES, useChangeLanguage } from '../i18n'

type SettingsIn = Schemas['SettingsIn']

function Preferences({ me }: { me: Schemas['MeOut'] }) {
  const { t, i18n } = useTranslation()
  const changeLanguage = useChangeLanguage()
  const { data: games = [] } = useGames()
  const toast = useToast()
  const client = useQueryClient()
  const shown = me.catalog_games ?? games.map((g) => g.id)

  const save = useMutation({
    mutationFn: (body: SettingsIn) => call(api.PATCH('/api/auth/me', { body })),
    onSuccess: (data) => {
      client.setQueryData(['me'], data)
      return client.invalidateQueries({ queryKey: ['cards'] })
    },
    onError: (e) => toast(e.message, 'error'),
  })
  const toggleGame = (id: string, on: boolean) => {
    const next = on ? [...shown, id] : shown.filter((g) => g !== id)
    // Every game ticked: also show games installed later.
    save.mutate({ catalog_games: next.length === games.length ? null : next })
  }

  return (
    <div className="card bg-base-200">
      <div className="card-body gap-4">
        <h2 className="card-title">{t('Preferences')}</h2>
        <label className="fieldset">
          <span className="fieldset-legend">{t('Language')}</span>
          <select
            className="select w-56"
            value={i18n.resolvedLanguage}
            onChange={(e) => changeLanguage(e.target.value as (typeof LANGUAGES)[number]['code'])}
          >
            {LANGUAGES.map((l) => (
              <option key={l.code} value={l.code} lang={l.code}>
                {l.label}
              </option>
            ))}
          </select>
          <span className="label whitespace-normal">
            {t('Card images are shown in this language when available, else in English, else in Japanese.')}
          </span>
        </label>
        <fieldset className="fieldset">
          <legend className="fieldset-legend">{t('Games shown in the catalog')}</legend>
          {games.map((g) => (
            <label key={g.id} className="label cursor-pointer gap-2 text-base-content">
              <input
                type="checkbox"
                className="checkbox checkbox-sm"
                checked={shown.includes(g.id)}
                disabled={save.isPending}
                onChange={(e) => toggleGame(g.id, e.target.checked)}
              />
              {g.name}
            </label>
          ))}
        </fieldset>
      </div>
    </div>
  )
}

export default function Settings() {
  const { t } = useTranslation()
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
      toast(t('Password changed'))
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
      toast(t('SSO account unlinked'), 'info')
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
      <h1 className="text-2xl font-bold">{t('Settings')}</h1>

      <div className="card bg-base-200">
        <div className="card-body">
          <h2 className="card-title">{user.username}</h2>
          <p className="text-sm text-base-content/70">
            {user.email ?? t('No email')} · <span className="badge badge-sm">{t(user.role)}</span>
          </p>
        </div>
      </div>

      <Preferences me={user} />

      <div className="card bg-base-200">
        <form className="card-body" onSubmit={submit}>
          <h2 className="card-title">{user.has_password ? t('Change password') : t('Set a password')}</h2>
          {user.has_password && (
            <label className="fieldset">
              <span className="fieldset-legend">{t('Current password')}</span>
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
            <span className="fieldset-legend">{t('New password')}</span>
            <input
              type="password"
              autoComplete="new-password"
              minLength={8}
              required
              className="input"
              value={next}
              onChange={(e) => setNext(e.target.value)}
            />
            <span className="label">{t('At least 8 characters')}</span>
          </label>
          <div className="card-actions">
            <button className="btn btn-primary" disabled={password.isPending}>
              {t('Save password')}
            </button>
          </div>
        </form>
      </div>

      {sso.length > 0 && (
        <div className="card bg-base-200">
          <div className="card-body">
            <h2 className="card-title">{t('Single sign-on')}</h2>
            <ul className="divide-y divide-base-300">
              {user.identities.map((i) => (
                <li key={i.id} className="flex items-center justify-between py-2">
                  <span>
                    {sso.find((p) => p.name === i.provider)?.display_name ?? i.provider}
                    {i.email && <span className="text-sm text-base-content/60"> · {i.email}</span>}
                  </span>
                  <button className="btn btn-ghost btn-sm" disabled={unlink.isPending} onClick={() => unlink.mutate(i.id)}>
                    {t('Unlink')}
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
                    {t('Link {{provider}}', { provider: p.display_name })}
                  </a>
                ))}
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
