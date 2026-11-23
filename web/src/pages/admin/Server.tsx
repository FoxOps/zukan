import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { AdminHeader } from '../../components/AdminHeader'
import { Navigate } from 'react-router'
import { api, call } from '../../api/client'
import { useMe } from '../../api/queries'
import { useToast } from '../../components/toast'
import { formatDateTime } from '../../lib/format'

/** Server administration: maintenance page for users while administrators work on the
 * server (heavy imports, catalog resets, upgrades). */
export default function Server() {
  const { t } = useTranslation()
  const { data: me } = useMe()
  const toast = useToast()
  const client = useQueryClient()
  const [confirming, setConfirming] = useState(false)
  const state = useQuery({
    queryKey: ['admin-maintenance'],
    queryFn: () => call(api.GET('/api/admin/maintenance')),
    enabled: me?.role === 'admin',
    refetchInterval: 15_000,
  })
  const turn = useMutation({
    mutationFn: (enabled: boolean) => call(api.PUT('/api/admin/maintenance', { body: { enabled } })),
    onSuccess: (data, enabled) => {
      client.setQueryData(['admin-maintenance'], data)
      setConfirming(false)
      toast(enabled ? t('Maintenance started') : t('Maintenance stopped'))
      return client.invalidateQueries({ queryKey: ['health'] })
    },
    onError: (e) => toast(e.message, 'error'),
  })

  if (me && me.role !== 'admin') return <Navigate to="/" replace />

  const maintenance = state.data?.maintenance ?? null
  const manual = maintenance?.reason === 'admin'

  return (
    <div className="flex flex-col gap-6">
      <AdminHeader title={t('Server')} />
      <div className="card rounded-[20px] border border-base-300 bg-base-100">
        <div className="card-body gap-3">
          <div className="flex flex-wrap items-start justify-between gap-2">
            <div>
              <h2 className="card-title">{t('Maintenance mode')}</h2>
              <p className="text-sm text-base-content/70">
                {t('Users see a maintenance page instead of Zukan (web and Android app); administrators keep access. Use it before heavy work on the server.')}
              </p>
            </div>
            {state.isPending ? (
              <span className="loading loading-spinner loading-sm" />
            ) : maintenance ? (
              <span className="badge badge-warning">{t('On')}</span>
            ) : (
              <span className="badge badge-ghost">{t('Off')}</span>
            )}
          </div>
          {maintenance && (
            <p className="text-sm">
              {manual
                ? t('Started by {{name}} on {{date}}.', { name: maintenance.by ?? '?', date: formatDateTime(maintenance.since) })
                : t('Started on {{date}} by the {{game}} catalog refresh: it stops by itself once the data sync is over.', {
                    date: formatDateTime(maintenance.since),
                    game: maintenance.game_id,
                  })}
            </p>
          )}
          <div className="card-actions justify-end">
            {manual ? (
              <button className="btn btn-primary" disabled={turn.isPending} onClick={() => turn.mutate(false)}>
                {turn.isPending && <span className="loading loading-spinner loading-sm" />}
                {t('Stop maintenance')}
              </button>
            ) : (
              <button className="btn btn-warning" disabled={turn.isPending || state.isPending} onClick={() => setConfirming(true)}>
                {t('Start maintenance')}
              </button>
            )}
          </div>
        </div>
      </div>

      <dialog className={`modal ${confirming ? 'modal-open' : ''}`} onClose={() => setConfirming(false)}>
        {confirming && (
          <div className="modal-box rounded-[20px]">
            <h3 className="text-2xl">{t('Start maintenance?')}</h3>
            <p className="py-2 text-sm">
              {t('Signed-in users are sent to the maintenance page at once and wait until you stop it, even after a server restart.')}
            </p>
            <div className="modal-action">
              <button className="btn btn-ghost" onClick={() => setConfirming(false)}>
                {t('Cancel')}
              </button>
              <button className="btn btn-warning" disabled={turn.isPending} onClick={() => turn.mutate(true)}>
                {turn.isPending && <span className="loading loading-spinner loading-sm" />}
                {t('Start maintenance')}
              </button>
            </div>
          </div>
        )}
        <form method="dialog" className="modal-backdrop">
          <button onClick={() => setConfirming(false)}>{t('Close')}</button>
        </form>
      </dialog>
    </div>
  )
}
