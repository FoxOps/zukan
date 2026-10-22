import { useMutation, useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router'
import { api, call } from '../api/client'
import { useGames, useMe } from '../api/queries'
import { ConditionBadge, FinishBadge, LangFlag } from '../components/Badges'
import { useInvalidateStock } from '../api/stock'
import { PriceChart } from '../components/PriceChart'
import { Select } from '../components/Select'
import { useToast } from '../components/toast'
import { formatDateTime, formatMoney } from '../lib/format'
import { ShownName } from '../components/ShownName'
import { Movers, SyncStatus, TopCards } from './dashboard/Widgets'

const RANGES = [30, 90, 365]

export default function Dashboard() {
  const { t } = useTranslation()
  const { data: games = [] } = useGames()
  const me = useMe()
  const [days, setDays] = useState(90)
  const [game, setGame] = useState('')
  const toast = useToast()
  const invalidate = useInvalidateStock()

  const value = useQuery({ queryKey: ['value'], queryFn: () => call(api.GET('/api/collection/value')) })
  const history = useQuery({
    queryKey: ['value', 'history', days, game],
    queryFn: () => call(api.GET('/api/collection/value/history', { params: { query: { days, game: game || undefined } } })),
  })
  const transactions = useQuery({
    queryKey: ['transactions'],
    queryFn: () => call(api.GET('/api/collection/transactions', { params: { query: { limit: 15 } } })),
  })
  const undo = useMutation({
    mutationFn: (id: number) =>
      call(api.POST('/api/collection/transactions/{transaction_id}/undo', { params: { path: { transaction_id: id } } })),
    onSuccess: () => {
      toast(t('Change undone'), 'info')
      return invalidate()
    },
    onError: (e) => toast(e.message, 'error'),
  })

  const gameName = (id: string) => games.find((g) => g.id === id)?.name ?? id

  return (
    <div className="flex flex-col gap-6">
      <h1 className="text-2xl font-bold">{t('Dashboard')}</h1>

      <div className="stats stats-vertical w-full bg-base-200 shadow sm:stats-horizontal">
        <div className="stat">
          <div className="stat-title">{t('Collection value')}</div>
          <div className="stat-value">{formatMoney(value.data?.total ?? 0, value.data?.currency)}</div>
          <div className="stat-desc">
            {t('{{count}} cards', { count: value.data?.quantity ?? 0 })}
            {/* Games priced in another currency: never added up. */}
            {value.data?.totals
              .filter((x) => x.currency !== value.data.currency)
              .map((x) => ` · + ${formatMoney(x.total, x.currency)}`)}
          </div>
        </div>
        {value.data?.games.map((g) => (
          <div key={g.game_id} className="stat">
            <div className="stat-title">{gameName(g.game_id)}</div>
            <div className="stat-value text-2xl">{formatMoney(g.total, g.currency)}</div>
            <div className="stat-desc">
              {t('{{count}} cards', { count: g.quantity })}
              {g.unpriced > 0 && ` · ${t('{{count}} without price', { count: g.unpriced })}`}
            </div>
          </div>
        ))}
      </div>

      {/* One widget per line. */}
      <TopCards />
      <Movers />
      {me.data?.role === 'admin' && <SyncStatus games={games} />}

      <div className="card bg-base-200">
        <div className="card-body">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <h2 className="card-title">{t('Value over time')}</h2>
            <div className="flex flex-wrap gap-2">
              <Select
                className="select-sm w-40"
                value={game}
                onChange={setGame}
                options={[{ value: '', label: t('All games') }, ...games.map((g) => ({ value: g.id, label: g.name }))]}
              />
              <div className="join">
                {RANGES.map((r) => (
                  <button key={r} className={`join-item btn btn-sm ${days === r ? 'btn-active' : ''}`} onClick={() => setDays(r)}>
                    {t('{{n}} d', { n: r })}
                  </button>
                ))}
              </div>
            </div>
          </div>
          <PriceChart
            data={(history.data?.points ?? [])
              // Days before the first known value carry no information.
              .slice(Math.max(0, (history.data?.points ?? []).findIndex((p) => Number(p.value) > 0)))
              .map((p) => ({ date: p.date, [t('Value')]: Number(p.value) }))}
            series={[t('Value')]}
            height={260}
            currency={history.data?.currency}
          />
          <p className="text-xs text-base-content/60">{t("Current holdings priced with each day's market prices.")}</p>
        </div>
      </div>

      <div className="card bg-base-200">
        <div className="card-body">
          <h2 className="card-title">{t('Recent changes')}</h2>
          {transactions.data?.length === 0 && (
            <p className="text-base-content/60">
              {t('Nothing yet.')} <Link className="link" to="/catalog">{t('Add cards from the catalog')}</Link>{' '}
              {t('or import a CSV.')}
            </p>
          )}
          <ul className="divide-y divide-base-300">
            {transactions.data?.map((tr) => (
              <li key={tr.id} className={`flex items-center gap-3 py-2 ${tr.undone ? 'opacity-50 line-through' : ''}`}>
                <span className={`badge w-12 justify-center ${tr.delta > 0 ? 'badge-success' : 'badge-error'}`}>
                  {tr.delta > 0 ? `+${tr.delta}` : tr.delta}
                </span>
                <div className="flex-1">
                  <div className="font-medium">
                    <ShownName name={tr.name} translation={tr.translation} />
                  </div>
                  <div className="flex flex-wrap items-center gap-1 text-xs text-base-content/60">
                    <span>{tr.set_code}</span>
                    <FinishBadge game={games.find((g) => g.id === tr.game_id)} finish={tr.finish} size="badge-xs" />
                    <ConditionBadge condition={tr.condition} size="badge-xs" />
                    <LangFlag lang={tr.language} className="h-3" />
                    <span>
                      · {t(tr.source)} · {formatDateTime(tr.created_at)}
                    </span>
                  </div>
                </div>
                {!tr.undone && (
                  <button className="btn btn-ghost btn-xs" disabled={undo.isPending} onClick={() => undo.mutate(tr.id)}>
                    {t('Undo')}
                  </button>
                )}
              </li>
            ))}
          </ul>
        </div>
      </div>
    </div>
  )
}
