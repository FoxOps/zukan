import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useState, type FormEvent } from 'react'
import { useTranslation } from 'react-i18next'
import { api, call, type Schemas } from '../api/client'
import { gameGroups, useGames, useMe } from '../api/queries'
import { useToast } from '../components/toast'
import { Select } from '../components/Select'
import { LANGUAGES, useChangeLanguage } from '../i18n'

type SettingsIn = Schemas['SettingsIn']

function Preferences({ me }: { me: Schemas['MeOut'] }) {
  const { t, i18n } = useTranslation()
  const changeLanguage = useChangeLanguage()
  const { data: games = [] } = useGames()
  const toast = useToast()
  const client = useQueryClient()
  const shown = me.catalog_games ?? games.map((g) => g.id)
  // Every market any game has prices from.
  const sources = [...new Map(games.flatMap((g) => g.price_sources).map((s) => [s.id, s])).values()]

  const save = useMutation({
    mutationFn: (body: SettingsIn) => call(api.PATCH('/api/auth/me', { body })),
    onSuccess: (data) => {
      client.setQueryData(['me'], data)
      // Prices shown everywhere follow the price sources.
      return Promise.all(['cards', 'card', 'collection', 'value', 'prices'].map((key) => client.invalidateQueries({ queryKey: [key] })))
    },
    onError: (e) => toast(e.message, 'error'),
  })
  const toggleGame = (id: string, on: boolean) => {
    const next = on ? [...shown, id] : shown.filter((g) => g !== id)
    // Every game ticked: also show games installed later.
    save.mutate({ catalog_games: next.length === games.length ? null : next })
  }

  return (
    <>
      <div className="card bg-base-200">
        <div className="card-body gap-4">
          <h2 className="card-title">{t('Preferences')}</h2>
          <label className="fieldset">
            <span className="fieldset-legend">{t('Language')}</span>
            <Select
              className="w-full max-w-xs"
              value={i18n.resolvedLanguage ?? ''}
              onChange={(v) => changeLanguage(v as (typeof LANGUAGES)[number]['code'])}
              options={LANGUAGES.map((l) => ({ value: l.code, label: l.label, lang: l.code }))}
            />
            <span className="label whitespace-normal">
              {t('Card images are shown in this language when available, else in English, else in Japanese.')}
            </span>
          </label>
          <fieldset className="fieldset">
            <legend className="fieldset-legend">{t('Price sources')}</legend>
            {sources.map((s) => {
              const on = me.price_sources.includes(s.id)
              return (
                <label key={s.id} className="label cursor-pointer gap-2 text-base-content">
                  <input
                    type="checkbox"
                    className="checkbox checkbox-sm"
                    checked={on}
                    // At least one source stays shown.
                    disabled={save.isPending || (on && me.price_sources.length === 1)}
                    onChange={(e) =>
                      save.mutate({ price_sources: e.target.checked ? [...me.price_sources, s.id] : me.price_sources.filter((id) => id !== s.id) })
                    }
                  />
                  {s.name} ({s.currency})
                </label>
              )
            })}
            <span className="label whitespace-normal">{t('Prices of these markets are shown on card pages and in the app.')}</span>
          </fieldset>
          {me.price_sources.length > 1 && (
            <label className="fieldset">
              <span className="fieldset-legend">{t('Main price source')}</span>
              <Select
                className="w-full max-w-xs"
                value={me.price_source}
                disabled={save.isPending}
                onChange={(v) => save.mutate({ price_source: v })}
                options={sources.filter((s) => me.price_sources.includes(s.id)).map((s) => ({ value: s.id, label: `${s.name} (${s.currency})` }))}
              />
              <span className="label whitespace-normal">
                {t('Used for values, price ranges and sorting. Games without it use their own market; other currencies are never added up.')}
              </span>
            </label>
          )}
        </div>
      </div>

      {/* Two columns while this card spans the page width (lg), one in the three-card row (xl). */}
      <div className="card bg-base-200 lg:col-span-2 xl:col-span-1">
        <div className="card-body gap-4">
          <h2 className="card-title">{t('Games shown in the catalog')}</h2>
          <div className="fieldset block gap-x-8 py-0 sm:columns-2 xl:columns-1">
            {gameGroups(games).map((group) => (
              <div key={group.id} className="flex break-inside-avoid flex-col gap-1 pb-1">
                {group.games.length > 1 && <span className="label font-medium text-base-content">{group.name}</span>}
                {group.games.map((g) => (
                  <label key={g.id} className={`label cursor-pointer gap-2 text-base-content ${group.games.length > 1 ? 'pl-6' : ''}`}>
                    <input
                      type="checkbox"
                      className="checkbox checkbox-sm"
                      checked={shown.includes(g.id)}
                      disabled={save.isPending}
                      onChange={(e) => toggleGame(g.id, e.target.checked)}
                    />
                    {group.games.length > 1 ? t(g.region_label ?? g.name) : g.name}
                  </label>
                ))}
              </div>
            ))}
          </div>
        </div>
      </div>
    </>
  )
}

/** Own email address, behind a "Change" button; the password confirms the change. SSO
 * accounts show the identity provider's address, changed there. */
function EmailForm({ me }: { me: Schemas['MeOut'] }) {
  const { t } = useTranslation()
  const toast = useToast()
  const client = useQueryClient()
  const [editing, setEditing] = useState(false)
  const [email, setEmail] = useState('')
  const [current, setCurrent] = useState('')
  const save = useMutation({
    mutationFn: () =>
      call(api.POST('/api/auth/email', { body: { email: email.trim() || null, current_password: current || null } })),
    onSuccess: (updated) => {
      toast(t('Email changed'))
      client.setQueryData(['me'], updated)
      setEditing(false)
      setCurrent('')
    },
    onError: (e) => toast(e.message, 'error'),
  })
  if (me.sso) {
    return (
      <p className="flex flex-wrap items-center gap-2 text-sm text-base-content/70">
        {me.email ?? t('No email')}
        · <span className="badge badge-sm">{t(me.role)}</span>
      </p>
    )
  }
  if (!editing) {
    return (
      <p className="flex flex-wrap items-center gap-2 text-sm text-base-content/70">
        {me.email ?? t('No email')}
        <button
          className="btn btn-ghost btn-xs"
          onClick={() => {
            setEmail(me.email ?? '')
            setEditing(true)
          }}
        >
          {t('Change')}
        </button>
        · <span className="badge badge-sm">{t(me.role)}</span>
      </p>
    )
  }
  return (
    <form
      className="flex flex-col gap-2"
      onSubmit={(e) => {
        e.preventDefault()
        save.mutate()
      }}
    >
      <label className="fieldset py-0">
        <span className="fieldset-legend">{t('Email')}</span>
        <input type="email" autoComplete="email" className="input w-full max-w-sm" value={email} onChange={(e) => setEmail(e.target.value)} autoFocus />
        <span className="label">{t('Leave empty to remove it')}</span>
      </label>
      {me.has_password && (
        <label className="fieldset py-0">
          <span className="fieldset-legend">{t('Current password')}</span>
          <input type="password" autoComplete="current-password" required className="input w-full max-w-sm" value={current} onChange={(e) => setCurrent(e.target.value)} />
        </label>
      )}
      <div className="flex gap-2">
        <button className="btn btn-primary btn-sm" disabled={save.isPending}>{t('Save')}</button>
        <button type="button" className="btn btn-ghost btn-sm" onClick={() => setEditing(false)}>{t('Cancel')}</button>
      </div>
    </form>
  )
}

export default function Settings() {
  const { t } = useTranslation()
  const me = useMe()
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

  if (!me.data) return null
  const user = me.data
  const submit = (e: FormEvent) => {
    e.preventDefault()
    password.mutate()
  }

  return (
    <div className="flex flex-col gap-6">
      <h1 className="text-2xl font-bold">{t('Settings')}</h1>

      {/* Account, preferences and catalog games side by side on wide screens (same height). */}
      <div className="grid gap-6 lg:grid-cols-2 xl:grid-cols-3">
        <div className="card bg-base-200">
          <div className="card-body gap-4">
            <div>
              <h2 className="card-title">{user.username}</h2>
              <EmailForm me={user} />
            </div>
            {/* SSO accounts: email and password are edited at the identity provider. */}
            {user.sso ? (
              user.sso_account?.account_url && (
                <div className="card-actions">
                  <a href={user.sso_account.account_url} target="_blank" rel="noreferrer" className="btn btn-primary">
                    {t('Edit my profile')}
                  </a>
                </div>
              )
            ) : (
              <>
              <div className="divider my-0" />
              <form className="flex flex-col gap-2" onSubmit={submit}>
                <h3 className="font-semibold">{user.has_password ? t('Change password') : t('Set a password')}</h3>
                {user.has_password && (
                  <label className="fieldset py-0">
                    <span className="fieldset-legend">{t('Current password')}</span>
                    <input
                      type="password"
                      autoComplete="current-password"
                      required
                      className="input w-full max-w-xs"
                      value={current}
                      onChange={(e) => setCurrent(e.target.value)}
                    />
                  </label>
                )}
                <label className="fieldset py-0">
                  <span className="fieldset-legend">{t('New password')}</span>
                  <input
                    type="password"
                    autoComplete="new-password"
                    minLength={8}
                    required
                    className="input w-full max-w-xs"
                    value={next}
                    onChange={(e) => setNext(e.target.value)}
                  />
                  <span className="label">{t('At least 8 characters')}</span>
                </label>
                <div className="card-actions mt-2">
                  <button className="btn btn-primary" disabled={password.isPending}>
                    {t('Save password')}
                  </button>
                </div>
              </form>
              </>
            )}
          </div>
        </div>

        <Preferences me={user} />
      </div>
    </div>
  )
}

