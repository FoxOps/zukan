import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState, type FormEvent } from 'react'
import { useTranslation } from 'react-i18next'
import { Navigate } from 'react-router'
import { api, call, type Schemas } from '../../api/client'
import { useMe } from '../../api/queries'
import { useToast } from '../../components/toast'
import { Select } from '../../components/Select'

type User = Schemas['UserOut']
type Update = Schemas['UserUpdateIn']

export default function Users() {
  const { t } = useTranslation()
  const me = useMe()
  const toast = useToast()
  const client = useQueryClient()
  const users = useQuery({
    queryKey: ['users'],
    queryFn: () => call(api.GET('/api/users')),
    enabled: me.data?.role === 'admin',
  })
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [email, setEmail] = useState('')
  const [deleting, setDeleting] = useState<number | null>(null)
  const refresh = () => client.invalidateQueries({ queryKey: ['users'] })

  const create = useMutation({
    mutationFn: () =>
      call(
        api.POST('/api/users', {
          body: { username, password: password || null, email: email || null, role: 'user' },
        }),
      ),
    onSuccess: () => {
      toast(t('User {{name}} created', { name: username }))
      setUsername('')
      setPassword('')
      setEmail('')
      return refresh()
    },
    onError: (e) => toast(e.message, 'error'),
  })
  const update = useMutation({
    mutationFn: ({ id, body }: { id: number; body: Update }) =>
      call(api.PATCH('/api/users/{user_id}', { params: { path: { user_id: id } }, body })),
    onSuccess: () => {
      toast(t('User updated'))
      return refresh()
    },
    onError: (e) => toast(e.message, 'error'),
  })
  const remove = useMutation({
    mutationFn: (id: number) => call(api.DELETE('/api/users/{user_id}', { params: { path: { user_id: id } } })),
    onSuccess: () => {
      toast(t('User deleted'), 'info')
      setDeleting(null)
      return refresh()
    },
    onError: (e) => toast(e.message, 'error'),
  })

  if (me.data?.role !== 'admin') return <Navigate to="/" replace />

  const submit = (e: FormEvent) => {
    e.preventDefault()
    create.mutate()
  }
  const resetPassword = (user: User) => {
    const value = window.prompt(t('New password for {{name}} (8+ characters)', { name: user.username }))
    if (value) update.mutate({ id: user.id, body: { password: value } })
  }

  return (
    <div className="flex flex-col gap-6">
      <h1 className="text-2xl font-bold">{t('Users')}</h1>
      <div className="overflow-x-auto rounded-box border border-base-300">
        <table className="table">
          <thead>
            <tr>
              <th>{t('User')}</th>
              <th>{t('Role')}</th>
              <th>{t('Login')}</th>
              <th>{t('Status')}</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {users.data?.map((u) => {
              const self = u.id === me.data?.id
              return (
                <tr key={u.id}>
                  <td>
                    <div className="font-medium">{u.username}</div>
                    <div className="text-xs text-base-content/60">{u.email}</div>
                  </td>
                  <td>
                    <Select
                      className="select-sm w-28"
                      value={u.role}
                      disabled={self}
                      onChange={(v) => update.mutate({ id: u.id, body: { role: v as User['role'] } })}
                      options={[
                        { value: 'user', label: t('user') },
                        { value: 'admin', label: t('admin') },
                      ]}
                    />
                  </td>
                  <td className="text-sm">{u.has_password ? t('Password') : t('SSO only')}</td>
                  <td>
                    <input
                      type="checkbox"
                      className="toggle toggle-success toggle-sm"
                      checked={!u.disabled}
                      disabled={self}
                      title={u.disabled ? t('Disabled') : t('Active')}
                      onChange={(e) => update.mutate({ id: u.id, body: { disabled: !e.target.checked } })}
                    />
                  </td>
                  <td className="flex justify-end gap-1">
                    <button className="btn btn-ghost btn-xs" onClick={() => resetPassword(u)}>
                      {t('Set password')}
                    </button>
                    {!self &&
                      (deleting === u.id ? (
                        <button className="btn btn-error btn-xs" onClick={() => remove.mutate(u.id)}>
                          {t('Delete with collection?')}
                        </button>
                      ) : (
                        <button className="btn btn-ghost btn-xs text-error" onClick={() => setDeleting(u.id)}>
                          {t('Delete')}
                        </button>
                      ))}
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>

      <div className="card max-w-xl bg-base-200">
        <form className="card-body" onSubmit={submit}>
          <h2 className="card-title">{t('New user')}</h2>
          <input className="input w-full" placeholder={t('Username')} required pattern="[A-Za-z0-9._@\-]+" value={username} onChange={(e) => setUsername(e.target.value)} />
          <input className="input w-full" type="email" placeholder={t('Email (optional)')} value={email} onChange={(e) => setEmail(e.target.value)} />
          <input className="input w-full" type="password" placeholder={t('Password (empty = SSO only)')} minLength={8} autoComplete="new-password" value={password} onChange={(e) => setPassword(e.target.value)} />
          <div className="card-actions">
            <button className="btn btn-primary" disabled={create.isPending}>
              {t('Create')}
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}
