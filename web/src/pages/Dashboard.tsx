import { useMutation, useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { Link } from 'react-router'
import { api, call } from '../api/client'
import { useGames } from '../api/queries'
import { useInvalidateStock } from '../api/stock'
import { PriceChart } from '../components/PriceChart'
import { useToast } from '../components/toast'
import { formatDateTime, formatMoney } from '../lib/format'

const RANGES = [30, 90, 365]

export default function Dashboard() {
  const { data: games = [] } = useGames()
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
      toast('Change undone', 'info')
      return invalidate()
    },
    onError: (e) => toast(e.message, 'error'),
  })

  const gameName = (id: string) => games.find((g) => g.id === id)?.name ?? id

  return (
    <div className="flex flex-col gap-6">
      <h1 className="text-2xl font-bold">Dashboard</h1>

      <div className="stats stats-vertical w-full bg-base-200 shadow sm:stats-horizontal">
        <div className="stat">
          <div className="stat-title">Collection value</div>
          <div className="stat-value text-primary">{formatMoney(value.data?.total ?? 0)}</div>
          <div className="stat-desc">{value.data?.quantity ?? 0} cards</div>
        </div>
        {value.data?.games.map((g) => (
          <div key={g.game_id} className="stat">
            <div className="stat-title">{gameName(g.game_id)}</div>
            <div className="stat-value text-2xl">{formatMoney(g.total)}</div>
            <div className="stat-desc">
              {g.quantity} cards{g.unpriced > 0 && ` · ${g.unpriced} without price`}
            </div>
          </div>
        ))}
      </div>

      <div className="card bg-base-200">
        <div className="card-body">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <h2 className="card-title">Value over time</h2>
            <div className="flex flex-wrap gap-2">
              <select className="select select-sm w-40" value={game} onChange={(e) => setGame(e.target.value)}>
                <option value="">All games</option>
                {games.map((g) => <option key={g.id} value={g.id}>{g.name}</option>)}
              </select>
              <div className="join">
                {RANGES.map((r) => (
                  <button key={r} className={`join-item btn btn-sm ${days === r ? 'btn-active' : ''}`} onClick={() => setDays(r)}>
                    {r} d
                  </button>
                ))}
              </div>
            </div>
          </div>
          <PriceChart
            data={(history.data ?? [])
              // Days before the first known value carry no information.
              .slice(Math.max(0, (history.data ?? []).findIndex((p) => Number(p.value) > 0)))
              .map((p) => ({ date: p.date, Value: Number(p.value) }))}
            series={['Value']}
            height={260}
          />
          <p className="text-xs text-base-content/60">Current holdings priced with each day's market prices.</p>
        </div>
      </div>

      <div className="card bg-base-200">
        <div className="card-body">
          <h2 className="card-title">Recent changes</h2>
          {transactions.data?.length === 0 && (
            <p className="text-base-content/60">
              Nothing yet. <Link className="link" to="/catalog">Add cards from the catalog</Link> or import a CSV.
            </p>
          )}
          <ul className="divide-y divide-base-300">
            {transactions.data?.map((t) => (
              <li key={t.id} className={`flex items-center gap-3 py-2 ${t.undone ? 'opacity-50 line-through' : ''}`}>
                <span className={`badge w-12 justify-center ${t.delta > 0 ? 'badge-success' : 'badge-error'}`}>
                  {t.delta > 0 ? `+${t.delta}` : t.delta}
                </span>
                <div className="flex-1">
                  <div className="font-medium">{t.name}</div>
                  <div className="text-xs text-base-content/60">
                    {t.set_code} · {t.finish} · {t.condition} · {t.language} · {t.source} · {formatDateTime(t.created_at)}
                  </div>
                </div>
                {!t.undone && (
                  <button className="btn btn-ghost btn-xs" disabled={undo.isPending} onClick={() => undo.mutate(t.id)}>
                    Undo
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
