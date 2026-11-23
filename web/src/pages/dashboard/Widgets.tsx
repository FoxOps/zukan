import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router'
import { api, call, type Schemas } from '../../api/client'
import type { Game } from '../../api/queries'
import { CardImage } from '../../components/CardImage'
import { Panel, PanelLink } from '../../components/Page'
import { ShownName } from '../../components/ShownName'
import { formatDateTime, formatMoney } from '../../lib/format'

type Item = Schemas['ItemOut']
type Mover = Schemas['MoverOut']

const cardLink = (item: Item) => `/cards/${item.card_id}/${item.printing_id}`

export function useTopItems() {
  return useQuery({
    queryKey: ['collection', 'top'],
    queryFn: () => call(api.GET('/api/collection', { params: { query: { sort: 'price_desc', page_size: 6 } } })),
  })
}

/** The copies worth the most (unit price × quantity), as pictures. */
export function TopCards() {
  const { t } = useTranslation()
  const top = useTopItems()
  const items = (top.data?.items ?? []).filter((i) => i.unit_price !== null)
  return (
    <Panel title={t('Most valuable cards')} aside={<PanelLink to="/collection?sort=price_desc">{t('View all')}</PanelLink>}>
        {top.isPending && <span className="loading loading-spinner" />}
        {top.isSuccess && items.length === 0 && <p className="text-base-content/70">{t('No priced cards yet.')}</p>}
        <div className="grid grid-cols-3 gap-4">
          {items.map((item) => (
            <Link key={item.id} to={cardLink(item)} className="group flex flex-col gap-1 text-xs">
              <CardImage
                thumb
                src={item.image}
                alt={item.name}
                landscape={item.orientation === 'landscape'}
                className="w-full rounded-[4.5%]"
              />
              <span className="truncate text-sm font-semibold group-hover:underline">
                <ShownName name={item.name} translation={item.translation} />
              </span>
              <span className="tabular-nums text-base-content/70">
                {formatMoney(item.unit_price, item.currency)}
                {item.quantity > 1 && ` × ${item.quantity}`}
              </span>
            </Link>
          ))}
        </div>
    </Panel>
  )
}

const PERIODS = [
  ['d1', '24h'],
  ['d7', '7d'],
  ['d30', '30d'],
] as const

function MoverList({ title, movers, up }: { title: string; movers: Mover[]; up: boolean }) {
  const { t } = useTranslation()
  return (
    <div className="flex flex-col gap-2">
      <h3 className="flex items-center gap-1 text-sm font-semibold">
        <span aria-hidden className={up ? 'text-success' : 'text-error'}>{up ? '↑' : '↓'}</span>
        {title}
      </h3>
      {movers.length === 0 && <p className="text-sm text-base-content/70">{t('No change.')}</p>}
      <ul className="flex flex-col gap-1">
        {movers.map(({ item, change }) => (
          <li key={item.id} className="flex items-center justify-between gap-2 text-sm">
            <Link to={cardLink(item)} className="link-hover min-w-0 truncate">
              <ShownName name={item.name} translation={item.translation} />
              <span className="ml-1 text-xs text-base-content/70">
                {item.set.code}
                {item.quantity > 1 && ` × ${item.quantity}`}
              </span>
            </Link>
            <span className="shrink-0 tabular-nums">
              {Number(change) > 0 ? '+' : ''}
              {formatMoney(change, item.currency)}
            </span>
          </li>
        ))}
      </ul>
    </div>
  )
}

/** Owned cards whose price moved most, by value of the copies held. */
export function Movers() {
  const { t } = useTranslation()
  const [period, setPeriod] = useState<(typeof PERIODS)[number][0]>('d7')
  const movers = useQuery({
    queryKey: ['collection', 'movers', period],
    queryFn: () => call(api.GET('/api/collection/movers', { params: { query: { period, limit: 5 } } })),
  })
  return (
    <Panel
      title={t('Price movers')}
      aside={
        <div className="join" role="group" aria-label={t('Period')}>
          {PERIODS.map(([key, label]) => (
            <button
              key={key}
              className={`join-item btn btn-sm min-h-9 ${period === key ? 'shadow-[inset_0_-3px_0_var(--color-primary)]' : ''}`}
              aria-pressed={period === key}
              onClick={() => setPeriod(key)}
            >
              {t(label)}
            </button>
          ))}
        </div>
      }
    >
        {movers.isPending && <span className="loading loading-spinner" />}
        {movers.data && (
          <div className="grid gap-6 sm:grid-cols-2">
            <MoverList title={t('Rising')} movers={movers.data.risers} up />
            <MoverList title={t('Falling')} movers={movers.data.fallers} up={false} />
          </div>
        )}
    </Panel>
  )
}

const STATUS: Record<string, string> = {
  running: 'badge-info',
  success: 'badge-success',
  failed: 'badge-error',
  cancelled: 'badge-warning',
}
const KINDS = ['catalog', 'prices', 'images'] as const

/** Administrators: latest run of each job per game, and quotas of limited APIs. */
export function SyncStatus({ games }: { games: Game[] }) {
  const { t } = useTranslation()
  const overview = useQuery({
    queryKey: ['admin', 'overview'],
    queryFn: () => call(api.GET('/api/admin/overview')),
    refetchInterval: 60_000,
  })
  const gameName = (id: string) => games.find((g) => g.id === id)?.name ?? id
  return (
    <Panel title={t('Data sync')} subtitle={t('Administrators only')} aside={<PanelLink to="/admin/jobs">{t('Details')}</PanelLink>}>
        {overview.isPending && <span className="loading loading-spinner" />}
        {overview.data && (
          <div className="overflow-x-auto" tabIndex={0} role="region" aria-label={t('Data sync')}>
            <table className="table table-sm">
              <thead>
                <tr>
                  <th />
                  {KINDS.map((k) => <th key={k}>{t(k)}</th>)}
                </tr>
              </thead>
              <tbody>
                {overview.data.games.map((g) => (
                  <tr key={g.game_id}>
                    <td className="font-medium">{gameName(g.game_id)}</td>
                    {KINDS.map((kind) => {
                      const run = g.runs.find((r) => r.kind === kind)
                      return (
                        <td key={kind} title={run?.error ?? undefined}>
                          {run ? (
                            <div className="flex flex-col items-start gap-0.5">
                              <span className={`badge badge-xs ${STATUS[run.status] ?? ''}`}>{t(run.status)}</span>
                              <span className="text-xs text-base-content/70">{formatDateTime(run.finished_at ?? run.started_at)}</span>
                            </div>
                          ) : (
                            <span className="text-base-content/40">–</span>
                          )}
                        </td>
                      )
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {overview.data && overview.data.quotas.length > 0 && (
          <ul className="mt-4 flex flex-col gap-2 border-t border-base-300 pt-4">
            {overview.data.quotas.map((q) => (
              <li key={q.source} className="text-sm">
                <div className="flex justify-between gap-2">
                  <span>{q.source}</span>
                  <span className="tabular-nums text-base-content/70">
                    {q.used} / {q.limit} {q.period === 'day' ? t('today') : t('this month')}
                  </span>
                </div>
                <progress className="progress progress-primary h-1.5 w-full" value={Math.min(q.used, q.limit)} max={Math.max(q.limit, 1)} />
              </li>
            ))}
          </ul>
        )}
    </Panel>
  )
}
