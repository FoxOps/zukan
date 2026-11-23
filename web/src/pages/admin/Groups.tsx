import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState, type FormEvent } from 'react'
import { useTranslation } from 'react-i18next'
import { AdminHeader } from '../../components/AdminHeader'
import { Navigate } from 'react-router'
import { api, call, type Schemas } from '../../api/client'
import { useMe, useProviders } from '../../api/queries'
import { useToast } from '../../components/toast'
import { Select } from '../../components/Select'
import { moduleInfo } from '../../lib/modules'

type Group = Schemas['GroupOut']
type Access = Schemas['ModuleAccessOut']

/** Identity provider groups typed as a comma-separated list. */
const parseIdp = (text: string) => [...new Set(text.split(',').map((s) => s.trim()).filter(Boolean))]

/** Who can use each optional module: nobody, everyone (each user turns it on), or the
 * members of some groups (on for them, administrators always). */
function ModuleAccess({ groups }: { groups: Group[] }) {
  const { t } = useTranslation()
  const toast = useToast()
  const client = useQueryClient()
  const access = useQuery({ queryKey: ['admin-modules'], queryFn: () => call(api.GET('/api/admin/modules')) })
  const save = useMutation({
    mutationFn: (body: Access) => call(api.PUT('/api/admin/modules', { body: [body] })),
    onSuccess: (data) => {
      client.setQueryData(['admin-modules'], data)
      return client.invalidateQueries({ queryKey: ['me'] })
    },
    onError: (e) => toast(e.message, 'error'),
  })
  const chosen = groups.filter((g) => !g.builtin)

  return (
    <div className="card rounded-[20px] border border-base-300 bg-base-100">
      <div className="card-body gap-4">
        <h2 className="card-title">{t('Module access')}</h2>
        <p className="text-sm text-base-content/70">
          {t('Open to everyone: each user turns the module on in their settings. Given to groups: on for their members, hidden for the others. Administrators can always use a module that is not off.')}
        </p>
        {access.data?.map((m) => {
          const info = moduleInfo(m.id)
          return (
            <div key={m.id} className="flex flex-col gap-2">
              <div className="flex flex-wrap items-center gap-3">
                <span className="w-32 font-medium">{t(info.name)}</span>
                <Select
                  className="select-sm w-48"
                  value={m.mode}
                  disabled={save.isPending}
                  aria-label={t(info.name)}
                  onChange={(mode) => save.mutate({ ...m, mode: mode as Access['mode'] })}
                  options={[
                    { value: 'off', label: t('Off') },
                    { value: 'everyone', label: t('Everyone') },
                    { value: 'groups', label: t('Groups') },
                  ]}
                />
              </div>
              {m.mode === 'groups' && (
                <div className="flex flex-wrap gap-3 pl-1 md:pl-35">
                  {chosen.length === 0 && <span className="text-xs text-base-content/70">{t('Create a group below first.')}</span>}
                  {chosen.map((g) => (
                    <label key={g.id} className="label cursor-pointer gap-2 text-sm text-base-content">
                      <input
                        type="checkbox"
                        className="checkbox checkbox-sm"
                        checked={m.groups.includes(g.id)}
                        disabled={save.isPending}
                        onChange={(e) =>
                          save.mutate({ ...m, groups: e.target.checked ? [...m.groups, g.id] : m.groups.filter((id) => id !== g.id) })
                        }
                      />
                      {g.name}
                    </label>
                  ))}
                </div>
              )}
            </div>
          )
        })}
      </div>
    </div>
  )
}

function GroupCard({ group, users, ssoEnabled }: { group: Group; users: Schemas['UserOut'][]; ssoEnabled: boolean }) {
  const { t } = useTranslation()
  const me = useMe()
  const toast = useToast()
  const client = useQueryClient()
  const [name, setName] = useState(group.name)
  const [idp, setIdp] = useState(group.idp_groups.join(', '))
  const [adding, setAdding] = useState('')
  const [deleting, setDeleting] = useState(false)
  const done = () =>
    Promise.all([
      client.invalidateQueries({ queryKey: ['groups'] }),
      client.invalidateQueries({ queryKey: ['users'] }),
      client.invalidateQueries({ queryKey: ['me'] }),
    ])
  const path = { params: { path: { group_id: group.id } } }
  const update = useMutation({
    mutationFn: (body: Schemas['GroupUpdateIn']) => call(api.PATCH('/api/admin/groups/{group_id}', { ...path, body })),
    onSuccess: () => {
      toast(t('Group updated'))
      return done()
    },
    onError: (e) => toast(e.message, 'error'),
  })
  const member = useMutation({
    mutationFn: ({ userId, add }: { userId: number; add: boolean }) => {
      const params = { params: { path: { group_id: group.id, user_id: userId } } }
      return call(
        add
          ? api.PUT('/api/admin/groups/{group_id}/members/{user_id}', params)
          : api.DELETE('/api/admin/groups/{group_id}/members/{user_id}', params),
      )
    },
    onSuccess: () => {
      setAdding('')
      return done()
    },
    onError: (e) => toast(e.message, 'error'),
  })
  const remove = useMutation({
    mutationFn: () => call(api.DELETE('/api/admin/groups/{group_id}', path)),
    onSuccess: () => {
      toast(t('Group deleted'), 'info')
      return Promise.all([done(), client.invalidateQueries({ queryKey: ['admin-modules'] })])
    },
    onError: (e) => toast(e.message, 'error'),
  })

  const linked = group.idp_groups.length > 0
  const memberIds = new Set(group.members.map((m) => m.id))
  // SSO accounts of a linked group come from the identity provider.
  const addable = users.filter((u) => !memberIds.has(u.id) && !(linked && u.sso))
  const save = (e: FormEvent) => {
    e.preventDefault()
    update.mutate({ ...(group.builtin ? {} : { name: name.trim() }), idp_groups: parseIdp(idp) })
  }

  return (
    <div className="card rounded-[20px] border border-base-300 bg-base-100">
      <div className="card-body gap-3">
        <form className="flex flex-col gap-2" onSubmit={save}>
          <div className="flex flex-wrap items-center gap-2">
            {group.builtin ? (
              <h2 className="card-title">
                {group.name} <span className="badge badge-sm badge-ghost">{t('built-in')}</span>
              </h2>
            ) : (
              <input className="input input-sm w-56 font-semibold" required maxLength={64} value={name} aria-label={t('Group name')} onChange={(e) => setName(e.target.value)} />
            )}
          </div>
          {group.builtin && <p className="text-xs text-base-content/70">{t('Its members are the administrators.')}</p>}
          <label className="fieldset">
            <span className="fieldset-legend">{t('Identity provider groups')}</span>
            <input
              className="input input-sm w-full"
              placeholder={t('e.g. zukan-binder, collectors')}
              value={idp}
              disabled={!ssoEnabled && !linked}
              onChange={(e) => setIdp(e.target.value)}
            />
            <span className="label text-xs whitespace-normal">
              {ssoEnabled
                ? t('SSO users in one of these groups are members, applied at their next sign-in. Empty: members are added by hand.')
                : t('Single sign-on is not set up: members are added by hand.')}
            </span>
          </label>
          <div>
            <button className="btn btn-sm" disabled={update.isPending}>
              {t('Save')}
            </button>
          </div>
        </form>

        <div className="flex flex-col gap-2 border-t border-base-300 pt-3">
          <span className="text-sm font-medium">{t('Members')}</span>
          {group.members.length === 0 && <span className="text-xs text-base-content/70">{t('No member yet.')}</span>}
          <div className="flex flex-wrap gap-2">
            {group.members.map((m) => {
              const locked = m.managed_by_sso || (!!group.builtin && m.id === me.data?.id)
              return (
                <span key={m.id} className={`badge gap-1 ${m.disabled ? 'badge-ghost opacity-60' : 'badge-neutral badge-soft'}`}>
                  {m.username}
                  {m.managed_by_sso && <span className="text-xs opacity-70">· {t('from SSO')}</span>}
                  {!locked && (
                    <button
                      type="button"
                      className="cursor-pointer opacity-70 hover:opacity-100"
                      aria-label={t('Remove {{name}}', { name: m.username })}
                      disabled={member.isPending}
                      onClick={() => member.mutate({ userId: m.id, add: false })}
                    >
                      ✕
                    </button>
                  )}
                </span>
              )
            })}
          </div>
          {addable.length > 0 && (
            <div className="flex flex-wrap items-center gap-2">
              <Select
                className="select-sm w-56"
                value={adding}
                aria-label={t('Add a member')}
                onChange={setAdding}
                options={[{ value: '', label: t('Add a member…') }, ...addable.map((u) => ({ value: String(u.id), label: u.username }))]}
              />
              <button className="btn btn-sm" disabled={!adding || member.isPending} onClick={() => member.mutate({ userId: Number(adding), add: true })}>
                {t('Add')}
              </button>
            </div>
          )}
        </div>

        {!group.builtin && (
          <div className="card-actions justify-end border-t border-base-300 pt-3">
            {deleting ? (
              <button className="btn btn-error btn-sm" disabled={remove.isPending} onClick={() => remove.mutate()}>
                {t('Delete this group?')}
              </button>
            ) : (
              <button className="btn btn-ghost btn-sm text-error" onClick={() => setDeleting(true)}>
                {t('Delete')}
              </button>
            )}
          </div>
        )}
      </div>
    </div>
  )
}

export default function Groups() {
  const { t } = useTranslation()
  const me = useMe()
  const providers = useProviders()
  const toast = useToast()
  const client = useQueryClient()
  const admin = me.data?.role === 'admin'
  const groups = useQuery({ queryKey: ['groups'], queryFn: () => call(api.GET('/api/admin/groups')), enabled: admin })
  const users = useQuery({ queryKey: ['users'], queryFn: () => call(api.GET('/api/users')), enabled: admin })
  const [name, setName] = useState('')
  const [idp, setIdp] = useState('')
  const ssoEnabled = (providers.data?.providers.length ?? 0) > 0
  const create = useMutation({
    mutationFn: () => call(api.POST('/api/admin/groups', { body: { name: name.trim(), idp_groups: parseIdp(idp) } })),
    onSuccess: () => {
      toast(t('Group {{name}} created', { name: name.trim() }))
      setName('')
      setIdp('')
      return Promise.all([client.invalidateQueries({ queryKey: ['groups'] }), client.invalidateQueries({ queryKey: ['users'] })])
    },
    onError: (e) => toast(e.message, 'error'),
  })

  if (!admin) return <Navigate to="/" replace />

  const submit = (e: FormEvent) => {
    e.preventDefault()
    create.mutate()
  }

  return (
    <div className="flex flex-col gap-6">
      <AdminHeader title={t('Groups')} />
      {groups.data && <ModuleAccess groups={groups.data} />}
      {groups.isPending && <span className="loading loading-spinner" />}
      <div className="grid gap-4 lg:grid-cols-2">
        {groups.data?.map((g) => (
          // Keyed on the saved values so the fields start again from them after a save.
          <GroupCard key={`${g.id}:${g.name}:${g.idp_groups.join(',')}`} group={g} users={users.data ?? []} ssoEnabled={ssoEnabled} />
        ))}
      </div>
      <div className="card max-w-xl bg-base-200">
        <form className="card-body" onSubmit={submit}>
          <h2 className="card-title">{t('New group')}</h2>
          <input className="input w-full" placeholder={t('Group name')} required maxLength={64} value={name} onChange={(e) => setName(e.target.value)} />
          {ssoEnabled && (
            <input className="input w-full" placeholder={t('Identity provider groups (optional, comma-separated)')} value={idp} onChange={(e) => setIdp(e.target.value)} />
          )}
          <div className="card-actions">
            <button className="btn btn-primary" disabled={create.isPending || !name.trim()}>
              {t('Create')}
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}
