import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router'
import { api, call, type Schemas } from '../api/client'
import { useGames, useMe, useShownGames } from '../api/queries'
import { ConditionBadge, FinishBadge, LangFlag } from '../components/Badges'
import { useInvalidateStock } from '../api/stock'
import { Icon } from '../components/Icon'
import { EmptyState, Metric, PageHeader, Panel, PanelLink } from '../components/Page'
import { PriceChart } from '../components/PriceChart'
import { Select } from '../components/Select'
import { useToast } from '../components/toast'
import { formatDateTime, formatMoney, formatShare } from '../lib/format'
import { ShownName } from '../components/ShownName'
import { useTopItems } from './dashboard/queries'
import { Movers, SyncStatus, TopCards } from './dashboard/Widgets'

const RANGES = [30, 90, 365]

type Point = { date: string; value: string }
// Days before the first known value carry no information (none: nothing to draw).
/** Points of the last `days` days (the history's own window: today and the days before). */
const lastDays = (points: Point[], days: number) => {
  const last = points.at(-1)
  if (!last) return points
  const start = new Date(`${last.date}T00:00:00Z`)
  start.setUTCDate(start.getUTCDate() - (days - 1))
  const from = start.toISOString().slice(0, 10)
  return points.filter((p) => p.date >= from)
}

const known = (points: Point[]) => {
  const first = points.findIndex((p) => Number(p.value) > 0)
  return first < 0 ? [] : points.slice(first)
}

export default function Dashboard() {
  const { t } = useTranslation()
  const { data: games = [] } = useGames()
  const { shown } = useShownGames()
  const me = useMe()
  const [days, setDays] = useState(90)
  const [game, setGame] = useState('')
  const toast = useToast()
  const invalidate = useInvalidateStock()
  const client = useQueryClient()

  const value = useQuery({ queryKey: ['value'], queryFn: () => call(api.GET('/api/collection/value')) })
  const history = useQuery({
    queryKey: ['value', 'history', days, game],
    queryFn: () => call(api.GET('/api/collection/value/history', { params: { query: { days, game: game || undefined } } })),
  })
  // Change of the whole collection over 30 days, for the value metric: the last 30 days of
  // the chart's history when it covers them (all games, 30 days or more), else asked apart.
  const fromChart = game === '' && days >= 30
  const month = useQuery({
    queryKey: ['value', 'history', 30, ''],
    queryFn: () => call(api.GET('/api/collection/value/history', { params: { query: { days: 30 } } })),
    enabled: !fromChart,
  })
  const monthData = fromChart && history.data ? { ...history.data, points: lastDays(history.data.points, 30) } : month.data
  const top = useTopItems()
  const transactions = useQuery({
    queryKey: ['transactions'],
    queryFn: () => call(api.GET('/api/collection/transactions', { params: { query: { limit: 15 } } })),
  })
  const undo = useMutation({
    mutationFn: (id: number) =>
      call(api.POST('/api/collection/transactions/{transaction_id}/undo', { params: { path: { transaction_id: id } } })),
    // Struck out at once: the row does not wait for the value, history and movers of the
    // page to load again (they follow in the background).
    onMutate: async (id) => {
      await client.cancelQueries({ queryKey: ['transactions'], exact: true })
      const before = client.getQueryData<Schemas['TransactionOut'][]>(['transactions'])
      client.setQueryData<Schemas['TransactionOut'][]>(['transactions'], (old) => old?.map((tr) => (tr.id === id ? { ...tr, undone: true } : tr)))
      return { before }
    },
    onSuccess: () => {
      toast(t('Change undone'), 'info')
      void invalidate()
    },
    onError: (e, _id, context) => {
      if (context?.before) client.setQueryData(['transactions'], context.before)
      toast(e.message, 'error')
    },
  })

  const gameName = (id: string) => games.find((g) => g.id === id)?.name ?? id
  const v = value.data
  const isAdmin = me.data?.role === 'admin'
  // A new account: one panel saying what to do, no empty charts.
  const empty = v?.quantity === 0 && transactions.data?.length === 0
  const priced = v?.games.reduce((n, g) => n + g.priced, 0) ?? 0
  const unpriced = v?.games.reduce((n, g) => n + g.unpriced, 0) ?? 0
  const monthPoints = known(monthData?.points ?? [])
  const monthChange =
    monthPoints.length > 1 && monthData?.currency === v?.currency
      ? Number(monthPoints[monthPoints.length - 1].value) - Number(monthPoints[0].value)
      : null
  const addCards = (
    <Link to="/catalog" className="btn btn-primary min-h-11 gap-2">
      <Icon name="plus" />
      {t('Add cards')}
    </Link>
  )

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        eyebrow={t('Your collection')}
        title={t('Your collection, at a glance.')}
        subtitle={t('Your cards, your games, and what changed lately.')}
        action={!empty && addCards}
      />

      {value.isError && <div className="alert alert-error">{value.error.message}</div>}
      {value.isPending && <span className="loading loading-dots loading-lg mx-auto" aria-label={t('Loading')} />}

      {empty && (
        <EmptyState
          title={t('Start with your first card.')}
          actions={
            <>
              <Link to="/catalog" className="btn btn-primary min-h-11">{t('Browse the catalog')}</Link>
              <Link to="/import" className="btn min-h-11">{t('Import a collection')}</Link>
            </>
          }
        >
          {t('Find a card in the catalog and choose its printing, finish, language and condition. Already have a list? Import your CSV or Zukan ZIP.')}
        </EmptyState>
      )}

      {v && !empty && (
        <>
          <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-[1.45fr_1fr_1fr]">
            <Metric lead className="md:col-span-2 xl:col-span-1" label={`${t('Collection value')} · ${v.currency}`} value={formatMoney(v.total, v.currency)}>
              {monthChange !== null && monthChange !== 0 && (
                <span className={`flex items-center gap-1 ${monthChange > 0 ? 'text-success' : 'text-error'}`}>
                  {monthChange > 0 ? '↑ +' : '↓ '}
                  {formatMoney(monthChange, v.currency)} {t('over 30 days')}
                </span>
              )}
              {/* Games priced in another currency: never added up. */}
              {v.totals
                .filter((x) => x.currency !== v.currency)
                .map((x) => (
                  <span key={x.currency}>+ {formatMoney(x.total, x.currency)} ({t('other currency, not added')})</span>
                ))}
            </Metric>
            <Metric label={t('Cards in your collection')} value={v.quantity}>
              <span>
                {top.data && `${t('{{count}} items', { count: top.data.total })} · `}
                {t('{{count}} games', { count: v.games.length })}
              </span>
            </Metric>
            <Metric label={t('Cards with a price')} value={priced + unpriced ? formatShare(priced / (priced + unpriced)) : '—'}>
              {unpriced > 0 ? (
                <Link className="link" to="/collection?noprice=1">
                  {t('Review {{count}} cards without price', { count: unpriced })}
                </Link>
              ) : (
                <span>{t('Every card has a price.')}</span>
              )}
            </Metric>
          </div>

          {/* Two columns that each keep their own height: no panel stretched next to a longer one. */}
          <div className="grid items-start gap-5 xl:grid-cols-[minmax(0,1.6fr)_minmax(280px,1fr)]">
            <div className="flex min-w-0 flex-col gap-5">
              <TopCards />
              <Panel
                title={t('Value over time')}
                subtitle={t("Current holdings priced with each day's market prices.")}
                aside={
                  <>
                    <Select
                      className="select-sm w-40"
                      value={game}
                      onChange={setGame}
                      aria-label={t('Game')}
                      options={[{ value: '', label: t('All games') }, ...shown.map((g) => ({ value: g.id, label: g.name }))]}
                    />
                    <div className="join" role="group" aria-label={t('Period')}>
                      {RANGES.map((r) => (
                        <button
                          key={r}
                          className={`join-item btn btn-sm min-h-9 ${days === r ? 'shadow-[inset_0_-3px_0_var(--color-primary)]' : ''}`}
                          aria-pressed={days === r}
                          onClick={() => setDays(r)}
                        >
                          {t('{{n}} d', { n: r })}
                        </button>
                      ))}
                    </div>
                  </>
                }
              >
                <PriceChart
                  data={known(history.data?.points ?? []).map((p) => ({ date: p.date, [t('Value')]: Number(p.value) }))}
                  series={[t('Value')]}
                  height={260}
                  currency={history.data?.currency}
                />
                <div className="mt-2 flex justify-end">
                  <PanelLink to="/finance">{t('Finance')}</PanelLink>
                </div>
              </Panel>
              <Movers />
            </div>
            <div className="flex min-w-0 flex-col gap-5">
              <Panel title={t('Your games')} aside={<PanelLink to="/settings">{t('Manage')}</PanelLink>}>
                <ul className="divide-y divide-base-300">
                  {v.games.map((g) => (
                    <li key={g.game_id} className="flex items-center gap-3 py-3">
                      <span className="grid h-9 w-9 shrink-0 place-items-center rounded-xl bg-base-200 font-semibold" aria-hidden>
                        {gameName(g.game_id).slice(0, 1)}
                      </span>
                      <div className="min-w-0 flex-1">
                        <Link to={`/collection?game=${encodeURIComponent(g.game_id)}`} className="link-hover font-semibold">
                          {gameName(g.game_id)}
                        </Link>
                        <div className="text-xs text-base-content/70">
                          {t('{{count}} cards', { count: g.quantity })}
                          {g.unpriced > 0 && (
                            <>
                              {' · '}
                              <Link className="link" to={`/collection?game=${encodeURIComponent(g.game_id)}&noprice=1`}>
                                {t('{{count}} without price', { count: g.unpriced })}
                              </Link>
                            </>
                          )}
                        </div>
                      </div>
                      <span className="font-semibold tabular-nums">{formatMoney(g.total, g.currency)}</span>
                    </li>
                  ))}
                </ul>
              </Panel>
              <Panel title={t('Recent changes')} aside={<PanelLink to="/collection?sort=updated">{t('Collection')}</PanelLink>}>
                {transactions.data?.length === 0 && (
                  <p className="text-base-content/70">
                    {t('Nothing yet.')} <Link className="link" to="/catalog">{t('Add cards from the catalog')}</Link>{' '}
                    {t('or import a CSV.')}
                  </p>
                )}
                <ul className="divide-y divide-base-300">
                  {transactions.data?.map((tr) => (
                    <li key={tr.id} className={`flex items-center gap-3 py-2.5 ${tr.undone ? 'opacity-60' : ''}`}>
                      <span
                        className={`grid h-9 min-w-10 shrink-0 place-items-center rounded-xl px-1 font-semibold tabular-nums ${tr.delta > 0 ? 'bg-success/15 text-success' : 'bg-error/15 text-error'}`}
                      >
                        {tr.delta > 0 ? `+${tr.delta}` : `−${-tr.delta}`}
                      </span>
                      <div className="min-w-0 flex-1">
                        <div className={`font-semibold ${tr.undone ? 'line-through' : ''}`}>
                          <ShownName name={tr.name} translation={tr.translation} />
                        </div>
                        <div className="flex flex-wrap items-center gap-1 text-xs text-base-content/70">
                          <span>{tr.set_code}</span>
                          <FinishBadge game={games.find((g) => g.id === tr.game_id)} finish={tr.finish} size="badge-xs" />
                          <ConditionBadge condition={tr.condition} size="badge-xs" />
                          <LangFlag lang={tr.language} className="h-3" />
                          <span>
                            · {t(tr.source)} · {formatDateTime(tr.created_at)}
                          </span>
                          {tr.undone && <span>· {t('Undone')}</span>}
                        </div>
                      </div>
                      {!tr.undone && (
                        <button className="btn btn-ghost btn-sm min-h-9" disabled={undo.isPending && undo.variables === tr.id} onClick={() => undo.mutate(tr.id)}>
                          {t('Undo')}
                        </button>
                      )}
                    </li>
                  ))}
                </ul>
              </Panel>
            </div>
          </div>
        </>
      )}
      {isAdmin && <SyncStatus games={games} />}
    </div>
  )
}
