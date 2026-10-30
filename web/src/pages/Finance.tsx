import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router'
import { api, call, type Schemas } from '../api/client'
import { useGames, type Game } from '../api/queries'
import { ConditionBadge, FinishBadge, LangFlag } from '../components/Badges'
import { CardImage } from '../components/CardImage'
import { GameTabs } from '../components/Filters'
import { Pagination } from '../components/Pagination'
import { PriceChart } from '../components/PriceChart'
import { ShownName } from '../components/ShownName'
import { conditionName, finishName, formatMoney, languageName } from '../lib/format'
import { useUrlState } from '../lib/hooks'
import { Movers } from './dashboard/Widgets'

type Share = Schemas['ShareOut']
type Report = Schemas['FinanceOut']

const RANGES = [30, 90, 365]
// Breakdown entries shown at once; longer lists get pages.
const BREAKDOWN_PAGE = 10
const PERIOD_LABELS: Record<number, string> = { 1: '1 day', 7: '7 days', 30: '30 days', 90: '90 days', 365: '1 year' }

function percent(value: number) {
  return new Intl.NumberFormat(undefined, { style: 'percent', maximumFractionDigits: 1, signDisplay: 'exceptZero' }).format(value)
}

/** Change of the value over one period: amount and percentage, with an arrow so the
 * direction never depends on color alone. */
function ChangeTile({ change, currency }: { change: Report['changes'][number]; currency: string }) {
  const { t } = useTranslation()
  const label = t(PERIOD_LABELS[change.days] ?? `${change.days} d`)
  if (change.past === null || change.past === undefined) {
    return (
      <div className="stat">
        <div className="stat-title">{label}</div>
        <div className="stat-value text-lg text-base-content/40">—</div>
        <div className="stat-desc">{t('No price history that far back')}</div>
      </div>
    )
  }
  const past = Number(change.past)
  const diff = Number(change.now) - past
  const up = diff > 0
  const flat = Math.abs(diff) < 0.005
  return (
    <div className="stat">
      <div className="stat-title">{label}</div>
      <div className={`stat-value text-lg ${flat ? '' : up ? 'text-success' : 'text-error'}`}>
        {flat ? '=' : up ? '▲' : '▼'} {formatMoney(Math.abs(diff), currency)}
      </div>
      <div className="stat-desc">
        {past > 0 ? percent(diff / past) : ''} · {t('from {{value}}', { value: formatMoney(past, currency) })}
      </div>
    </div>
  )
}

/** One horizontal bar per entry, longest first: value, share of the total and copies. */
function Breakdown({
  title,
  shares,
  total,
  currency,
  label = (s) => s.label,
}: {
  title: string
  shares: Share[]
  total: number
  currency: string
  label?: (share: Share) => string
}) {
  const { t } = useTranslation()
  const [page, setPage] = useState(1)
  if (shares.length === 0) return null
  // Bars keep the scale of the whole list, so pages compare with each other.
  const max = Math.max(...shares.map((s) => Number(s.value)), 0)
  const pages = Math.ceil(shares.length / BREAKDOWN_PAGE)
  const current = Math.min(page, pages)
  const shown = shares.slice((current - 1) * BREAKDOWN_PAGE, current * BREAKDOWN_PAGE)
  return (
    <div className="card bg-base-200">
      <div className="card-body gap-3">
        <h2 className="card-title text-base">{title}</h2>
        <ul className="flex flex-col gap-2">
          {shown.map((s) => {
            const value = Number(s.value)
            const name = label(s)
            return (
              <li key={s.key} title={`${name}: ${formatMoney(value, currency)} · ${t('{{count}} cards', { count: s.quantity })}`}>
                <div className="flex items-baseline justify-between gap-2 text-sm">
                  <span className="min-w-0 truncate">{name}</span>
                  <span className="shrink-0 tabular-nums">
                    <span className="font-medium">{formatMoney(value, currency)}</span>
                    <span className="ml-2 text-xs text-base-content/60">{total > 0 ? percent(value / total).replace('+', '') : '—'}</span>
                  </span>
                </div>
                <div className="mt-1 h-2 w-full rounded-full bg-base-300">
                  <div className="h-2 rounded-full bg-primary" style={{ width: `${max > 0 ? Math.max((value / max) * 100, value > 0 ? 1 : 0) : 0}%` }} />
                </div>
                <div className="text-xs text-base-content/50">{t('{{count}} cards', { count: s.quantity })}</div>
              </li>
            )
          })}
        </ul>
        <Pagination page={current} pageSize={BREAKDOWN_PAGE} total={shares.length} onChange={setPage} />
      </div>
    </div>
  )
}

function TopItems({ report, games }: { report: Report; games: Game[] }) {
  const { t } = useTranslation()
  if (report.top.length === 0) return null
  return (
    <div className="card bg-base-200">
      <div className="card-body">
        <h2 className="card-title">{t('Most valuable cards')}</h2>
        {report.top_share !== null && report.top_share !== undefined && (
          <p className="text-sm text-base-content/70">
            {t('The {{count}} most valuable hold {{share}} of the value.', {
              count: report.top.length,
              share: percent(report.top_share).replace('+', ''),
            })}
          </p>
        )}
        <div className="overflow-x-auto">
          <table className="table table-sm">
            <thead>
              <tr>
                <th className="w-10" />
                <th>{t('Card')}</th>
                <th>{t('Version')}</th>
                <th className="text-right">{t('Price')}</th>
                <th className="text-right">{t('Quantity')}</th>
                <th className="text-right">{t('Value')}</th>
              </tr>
            </thead>
            <tbody>
              {report.top.map(({ item, unit, value }) => {
                const game = games.find((g) => g.id === item.game_id)
                return (
                  <tr key={item.id}>
                    <td>
                      <Link to={`/cards/${item.card_id}/${item.printing_id}`} className="block w-9" tabIndex={-1} aria-hidden>
                        <CardImage thumb src={item.image} alt="" landscape={item.orientation === 'landscape'} />
                      </Link>
                    </td>
                    <td>
                      <Link to={`/cards/${item.card_id}/${item.printing_id}`} className="link-hover font-medium">
                        <ShownName name={item.name} translation={item.translation} />
                      </Link>
                    </td>
                    <td className="text-xs">
                      <div className="whitespace-nowrap">{item.set.code} {item.collector_number}</div>
                      <div className="mt-1 flex flex-wrap items-center gap-1">
                        <FinishBadge game={game} finish={item.finish} />
                        <ConditionBadge condition={item.condition} />
                        <LangFlag lang={item.language} />
                      </div>
                    </td>
                    <td className="text-right tabular-nums">{formatMoney(unit, report.currency)}</td>
                    <td className="text-right tabular-nums">{item.quantity}</td>
                    <td className="text-right font-medium tabular-nums">{formatMoney(value, report.currency)}</td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  )
}

export default function Finance() {
  const { t } = useTranslation()
  const { data: games = [] } = useGames()
  const url = useUrlState()
  const game = url.get('game')
  const [days, setDays] = useState(90)
  const report = useQuery({
    queryKey: ['value', 'finance', game],
    queryFn: () => call(api.GET('/api/collection/finance', { params: { query: { game: game || undefined } } })),
  })
  const gameOf = games.find((g) => g.id === game)
  const gameName = (id: string) => games.find((g) => g.id === id)?.name ?? id

  const r = report.data
  const total = Number(r?.value ?? 0)
  const points = (r?.history ?? []).slice(-days)
  // Days before the first known value carry no information.
  const shown = points.slice(Math.max(0, points.findIndex((p) => Number(p.value) > 0)))

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-2xl font-bold">{t('Finance')}</h1>
        <GameTabs value={game} onChange={(id) => url.set({ game: id })} />
      </div>

      {report.isPending && <span className="loading loading-spinner loading-lg" />}
      {report.isError && <div className="alert alert-error">{report.error.message}</div>}

      {r && (
        <>
          {r.quantity === 0 ? (
            <p className="text-base-content/60">
              {t('Nothing yet.')} <Link className="link" to="/catalog">{t('Add cards from the catalog')}</Link>
            </p>
          ) : (
            <div className="stats stats-vertical w-full bg-base-200 shadow sm:stats-horizontal">
              <div className="stat">
                <div className="stat-title">{gameOf ? t('{{game}} value', { game: gameOf.name }) : t('Collection value')}</div>
                <div className="stat-value">{formatMoney(r.value, r.currency)}</div>
                <div className="stat-desc">
                  {t('{{count}} cards', { count: r.quantity })} · {t('{{count}} versions', { count: r.printings })}
                </div>
              </div>
              <div className="stat">
                <div className="stat-title">{t('Average card')}</div>
                <div className="stat-value text-2xl">{formatMoney(r.average, r.currency)}</div>
                <div className="stat-desc">{t('Median: {{value}}', { value: formatMoney(r.median, r.currency) })}</div>
              </div>
              <div className="stat">
                <div className="stat-title">{t('Priced cards')}</div>
                <div className="stat-value text-2xl">{r.quantity ? percent(r.priced / r.quantity).replace('+', '') : '—'}</div>
                <div className="stat-desc">{r.unpriced > 0 ? t('{{count}} without price', { count: r.unpriced }) : t('All cards have a price')}</div>
              </div>
            </div>
          )}
          {r.other_currencies.length > 0 && (
            <div role="note" className="alert alert-info alert-soft text-sm">
              {t('Not counted here, priced in another currency: {{games}}. Pick the game to see its figures.', {
                games: r.other_currencies.map(gameName).join(', '),
              })}
            </div>
          )}

          {r.quantity > 0 && (
            <>
              <div className="stats stats-vertical w-full bg-base-200 shadow sm:stats-horizontal">
                {r.changes.map((c) => (
                  <ChangeTile key={c.days} change={c} currency={r.currency} />
                ))}
              </div>

              <div className="card bg-base-200">
                <div className="card-body">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <h2 className="card-title">{t('Value over time')}</h2>
                    <div className="join">
                      {RANGES.map((d) => (
                        <button key={d} className={`join-item btn btn-sm ${days === d ? 'btn-active' : ''}`} onClick={() => setDays(d)}>
                          {t('{{n}} d', { n: d })}
                        </button>
                      ))}
                    </div>
                  </div>
                  <PriceChart
                    data={shown.map((p) => ({ date: p.date, [t('Value')]: Number(p.value) }))}
                    series={[t('Value')]}
                    height={260}
                    currency={r.currency}
                  />
                  <p className="text-xs text-base-content/60">{t("Current holdings priced with each day's market prices.")}</p>
                </div>
              </div>

              <div className="grid gap-4 lg:grid-cols-2">
                {!game && <Breakdown title={t('By game')} shares={r.by_game} total={total} currency={r.currency} label={(s) => gameName(s.key)} />}
                <Breakdown title={`${t('By card price')} (${r.currency})`} shares={r.by_band} total={total} currency={r.currency} label={(s) => s.label} />
                <Breakdown title={t('By set')} shares={r.by_set} total={total} currency={r.currency} />
                <Breakdown
                  title={t('By rarity')}
                  shares={r.by_rarity}
                  total={total}
                  currency={r.currency}
                  // Keys are "<game>:<rarity>": the game named when several are shown.
                  label={(s) => {
                    const [gameId, ...rest] = s.key.split(':')
                    return game ? rest.join(':') : `${gameName(gameId)} · ${rest.join(':')}`
                  }}
                />
                <Breakdown title={t('By condition')} shares={r.by_condition} total={total} currency={r.currency} label={(s) => conditionName(s.key)} />
                <Breakdown title={t('By language')} shares={r.by_language} total={total} currency={r.currency} label={(s) => languageName(s.key)} />
                <Breakdown
                  title={t('By finish')}
                  shares={r.by_finish}
                  total={total}
                  currency={r.currency}
                  label={(s) => finishName(gameOf ?? games.find((g) => g.finishes.some((f) => f.code === s.key)), s.key)}
                />
              </div>

              <TopItems report={r} games={games} />
              <Movers />
            </>
          )}
        </>
      )}
    </div>
  )
}
