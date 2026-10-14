import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Navigate } from 'react-router'
import { api, call } from '../../api/client'
import { useGames, useMe } from '../../api/queries'
import { useToast } from '../../components/toast'
import { Select } from '../../components/Select'
import { formatDateTime } from '../../lib/format'

const KINDS = ['catalog', 'prices', 'images', 'refresh'] as const
const STATUS: Record<string, string> = {
  running: 'badge-info',
  success: 'badge-success',
  failed: 'badge-error',
  cancelled: 'badge-warning',
}
// Report counters in display order, with their labels; others are internal.
const REPORT: Record<string, string> = {
  sets: 'sets',
  cards: 'cards',
  printings: 'printings',
  names: 'names',
  targets: 'owned printings',
  quotes: 'prices received',
  prices: 'prices',
  stored: 'stored',
  cached: 'already cached',
  skipped: 'skipped',
  missing: 'without source',
  refused: 'refused by source',
  failed: 'failed',
  icons: 'set icons',
  backs: 'card backs',
  pruned: 'old prices removed',
  pruned_prices: 'old prices removed',
  pruned_cards: 'empty cards removed',
  cross_checked: 'cross-checked',
  discrepancies: 'differences',
  checked: 'outdated cards',
  updated: 'updated',
  not_found: 'not found at the source',
}

function Report({ report }: { report: Record<string, unknown> }) {
  const { t } = useTranslation()
  const counters = Object.keys(REPORT)
    .filter((k) => typeof report[k] === 'number' && report[k] !== 0)
    .map((k) => `${t(REPORT[k])} ${(report[k] as number).toLocaleString()}`)
  return <>{counters.length ? counters.join(' · ') : t('Nothing to do')}</>
}

function duration(start: string, end: string | null): string {
  const seconds = Math.round(((end ? new Date(end) : new Date()).getTime() - new Date(start).getTime()) / 1000)
  return seconds < 120 ? `${seconds} s` : `${Math.round(seconds / 60)} min`
}

export default function Jobs() {
  const { t } = useTranslation()
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
      toast(t('{{kind}} job started for {{game}}', { kind: t(kind), game }), 'info')
      return client.invalidateQueries({ queryKey: ['jobs'] })
    },
    onError: (e) => toast(e.message, 'error'),
  })
  const importImages = useMutation({
    mutationFn: () =>
      call(api.POST('/api/admin/images/{game_id}/import', { params: { path: { game_id: imageGame } }, body: { folder } })),
    onSuccess: (r) => toast(t('{{stored}} images imported, {{missing}} printings without image', { stored: r.stored, missing: r.missing })),
    onError: (e) => toast(e.message, 'error'),
  })

  if (!admin) return <Navigate to="/" replace />

  const lastRun = (game: string, kind: string) => jobs.data?.find((j) => j.game_id === game && j.kind === kind)

  return (
    <div className="flex flex-col gap-6">
      <h1 className="text-2xl font-bold">{t('Data sync')}</h1>
      <p className="text-sm text-base-content/70">
        {t('The worker refreshes catalogs weekly, prices and images daily, and outdated cards every two days. A job started here runs at once, stopping an automatic run of the same job.')}
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
                    {/* A manual run takes over a running automatic one. */}
                    <button
                      className="btn btn-sm"
                      disabled={start.isPending || (run?.status === 'running' && run.trigger === 'manual')}
                      title={run?.status === 'running' && run.trigger === 'auto' ? t('Stops the automatic run and starts again now') : undefined}
                      onClick={() => start.mutate({ game: g.id, kind })}
                    >
                      {run?.status === 'running' && run.trigger === 'manual' ? <span className="loading loading-spinner loading-xs" /> : t('Run')}
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
            <Select className="w-56" value={imageGame} onChange={setImageGame} options={games.map((g) => ({ value: g.id, label: g.name }))} />
            <Select
              className="w-56"
              value={folder}
              onChange={setFolder}
              options={[{ value: '', label: t('Choose a folder') }, ...(folders.data ?? []).map((f) => ({ value: f, label: f }))]}
            />
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
                <td className="whitespace-nowrap">
                  <span className={`badge badge-sm ${STATUS[j.status]}`}>{t(j.status)}</span>{' '}
                  <span className="text-xs text-base-content/60">{t(j.trigger)}</span>
                </td>
                <td className="whitespace-nowrap">{formatDateTime(j.started_at)}</td>
                <td>{duration(j.started_at, j.finished_at)}</td>
                <td className="max-w-md text-xs">
                  {j.error ? (
                    <span className="text-error">{j.error}</span>
                  ) : j.status === 'running' ? null : (
                    <Report report={j.report} />
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
