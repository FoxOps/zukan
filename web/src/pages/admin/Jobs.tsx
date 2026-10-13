import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { Navigate } from 'react-router'
import { api, call } from '../../api/client'
import { useGames, useMe } from '../../api/queries'
import { useToast } from '../../components/toast'
import { formatDateTime } from '../../lib/format'
import { t } from '../../i18n'

const KINDS = ['catalog', 'prices', 'images'] as const
const STATUS: Record<string, string> = {
  running: 'badge-info',
  success: 'badge-success',
  failed: 'badge-error',
}

function duration(start: string, end: string | null): string {
  const seconds = Math.round(((end ? new Date(end) : new Date()).getTime() - new Date(start).getTime()) / 1000)
  return seconds < 120 ? `${seconds} s` : `${Math.round(seconds / 60)} min`
}

export default function Jobs() {
  const me = useMe()
  const { data: games = [] } = useGames()
  const toast = useToast()
  const client = useQueryClient()
  const admin = me.data?.role === 'admin'
  const jobs = useQuery({
    queryKey: ['jobs'],
    queryFn: () => call(api.GET('/api/admin/jobs', { params: { query: { limit: 50 } } })),
    enabled: admin,
    // Poll while something runs.
    refetchInterval: (query) => (query.state.data?.some((j) => j.status === 'running') ? 3000 : false),
  })
  const folders = useQuery({
    queryKey: ['import-folders'],
    queryFn: () => call(api.GET('/api/admin/import-folders')),
    enabled: admin,
  })
  const [imageGame, setImageGame] = useState('sorcery')
  const [folder, setFolder] = useState('')

  const start = useMutation({
    mutationFn: ({ game, kind }: { game: string; kind: (typeof KINDS)[number] }) =>
      call(api.POST('/api/admin/jobs/{game_id}/{kind}', { params: { path: { game_id: game, kind } } })),
    onSuccess: (_, { game, kind }) => {
      toast(t('{kind} job started for {game}', { kind: t(kind), game }), 'info')
      return client.invalidateQueries({ queryKey: ['jobs'] })
    },
    onError: (e) => toast(e.message, 'error'),
  })
  const importImages = useMutation({
    mutationFn: () =>
      call(api.POST('/api/admin/images/{game_id}/import', { params: { path: { game_id: imageGame } }, body: { folder } })),
    onSuccess: (r) => toast(t('{stored} images imported, {missing} printings without image', { stored: r.stored, missing: r.missing })),
    onError: (e) => toast(e.message, 'error'),
  })

  if (!admin) return <Navigate to="/" replace />

  const lastRun = (game: string, kind: string) => jobs.data?.find((j) => j.game_id === game && j.kind === kind)

  return (
    <div className="flex flex-col gap-6">
      <h1 className="text-2xl font-bold">{t('Data sync')}</h1>
      <p className="text-sm text-base-content/70">
        {t('The worker refreshes catalogs weekly and prices and images daily. Start a job by hand here.')}
      </p>

      <div className="grid gap-4 md:grid-cols-3">
        {games.map((g) => (
          <div key={g.id} className="card bg-base-200">
            <div className="card-body gap-3">
              <h2 className="card-title">{g.name}</h2>
              {KINDS.filter((k) => k !== 'prices' || g.has_prices).map((kind) => {
                const run = lastRun(g.id, kind)
                return (
                  <div key={kind} className="flex items-center justify-between gap-2">
                    <div>
                      <div className="font-medium">{t(kind)}</div>
                      <div className="text-xs text-base-content/60">
                        {run ? (
                          <>
                            <span className={`badge badge-xs ${STATUS[run.status]}`}>{t(run.status)}</span>{' '}
                            {formatDateTime(run.started_at)}
                          </>
                        ) : (
                          t('never run')
                        )}
                      </div>
                    </div>
                    <button
                      className="btn btn-sm"
                      disabled={start.isPending || run?.status === 'running'}
                      onClick={() => start.mutate({ game: g.id, kind })}
                    >
                      {run?.status === 'running' ? <span className="loading loading-spinner loading-xs" /> : t('Run')}
                    </button>
                  </div>
                )
              })}
            </div>
          </div>
        ))}
      </div>

      <div className="card bg-base-200">
        <div className="card-body">
          <h2 className="card-title">{t('Import card images')}</h2>
          <p className="text-sm">
            {t("For images that cannot be downloaded: put the image folder in the server's import directory")}{' '}
            (<code>./import</code>), {t('then import it here.')}
          </p>
          <div className="flex flex-wrap gap-2">
            <select className="select w-56" value={imageGame} onChange={(e) => setImageGame(e.target.value)}>
              {games.map((g) => (
                <option key={g.id} value={g.id}>
                  {g.name}
                </option>
              ))}
            </select>
            <select className="select w-56" value={folder} onChange={(e) => setFolder(e.target.value)}>
              <option value="">{t('Choose a folder')}</option>
              {folders.data?.map((f) => (
                <option key={f} value={f}>
                  {f}
                </option>
              ))}
            </select>
            <button className="btn btn-primary" disabled={!folder || importImages.isPending} onClick={() => importImages.mutate()}>
              {importImages.isPending && <span className="loading loading-spinner loading-sm" />}
              {t('Import')}
            </button>
          </div>
        </div>
      </div>

      <div className="overflow-x-auto rounded-box border border-base-300">
        <table className="table table-sm">
          <thead>
            <tr>
              <th>{t('Game')}</th>
              <th>{t('Job')}</th>
              <th>{t('Status')}</th>
              <th>{t('Started')}</th>
              <th>{t('Duration')}</th>
              <th>{t('Result')}</th>
            </tr>
          </thead>
          <tbody>
            {jobs.data?.map((j) => (
              <tr key={j.id}>
                <td>{j.game_id}</td>
                <td>{t(j.kind)}</td>
                <td>
                  <span className={`badge badge-sm ${STATUS[j.status]}`}>{t(j.status)}</span>
                </td>
                <td className="whitespace-nowrap">{formatDateTime(j.started_at)}</td>
                <td>{duration(j.started_at, j.finished_at)}</td>
                <td className="max-w-md text-xs">
                  {j.error ? (
                    <span className="text-error">{j.error}</span>
                  ) : (
                    Object.entries(j.report)
                      .map(([k, v]) => `${k} ${v}`)
                      .join(' · ')
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}
