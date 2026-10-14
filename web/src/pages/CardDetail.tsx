import { useQuery } from '@tanstack/react-query'
import { useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link, Navigate, useLocation, useNavigate, useParams } from 'react-router'
import { api, call, type Schemas } from '../api/client'
import { useGame, useMe } from '../api/queries'
import { Attributes } from '../components/Attributes'
import { ConditionBadge, FinishBadge, LangFlag } from '../components/Badges'
import { CardImage } from '../components/CardImage'
import { ColorBadges } from '../components/ColorBadges'
import { PriceChart } from '../components/PriceChart'
import { StockDialog, type StockTarget } from '../components/StockDialog'
import { Select } from '../components/Select'
import { hasVisibleAttributes } from '../lib/attributes'
import { useUrlState } from '../lib/hooks'
import { finishName, formatDate, formatMoney, languageName, normalize } from '../lib/format'

type PrintingOut = Schemas['PrintingOut']

function PriceHistory({
  printing,
  finish,
  finishLabel,
  source,
}: {
  printing: PrintingOut
  // Only this finish's prices (all finishes when null).
  finish: string | null
  finishLabel: (f: string) => string
  source: { id: string; currency: string } | undefined
}) {
  const history = useQuery({
    queryKey: ['prices', printing.id],
    queryFn: () => call(api.GET('/api/printings/{printing_id}/prices', { params: { path: { printing_id: printing.id } } })),
  })
  const { data, series } = useMemo(() => {
    const byDate = new Map<string, Record<string, number | string | null>>()
    const names = new Set<string>()
    for (const point of history.data ?? []) {
      if (point.source !== source?.id || (finish !== null && point.finish !== finish)) continue
      const name = finishLabel(point.finish)
      names.add(name)
      const row = byDate.get(point.date) ?? { date: point.date }
      row[name] = point.trend === null ? null : Number(point.trend)
      byDate.set(point.date, row)
    }
    return { data: [...byDate.values()] as { date: string }[], series: [...names] }
  }, [history.data, finish, finishLabel, source])
  if (history.isPending) return <span className="loading loading-dots" />
  return <PriceChart data={data} series={series} currency={source?.currency} />
}

// Printing orders; the API order (owned first, then newest) is the default.
const PRINTING_SORTS = {
  owned: 'Owned first',
  newest: 'Newest sets',
  oldest: 'Oldest sets',
  set: 'Set name',
  number: 'Collector number',
  price_desc: 'Price: high to low',
  price_asc: 'Price: low to high',
} as const
type PrintingSort = keyof typeof PRINTING_SORTS

function lowestTrend(p: PrintingOut, source: string | undefined): number | null {
  const trends = p.prices.filter((x) => x.source === source && x.trend !== null).map((x) => Number(x.trend))
  return trends.length ? Math.min(...trends) : null
}

function sortPrintings(printings: PrintingOut[], sort: PrintingSort, source: string | undefined): PrintingOut[] {
  const date = (p: PrintingOut) => p.set.release_date ?? ''
  const number = (a: PrintingOut, b: PrintingOut) =>
    (a.collector_number ?? '').localeCompare(b.collector_number ?? '', undefined, { numeric: true })
  // Printings without a price stay last in both price orders.
  const price = (a: PrintingOut, b: PrintingOut, sign: number) => {
    const x = lowestTrend(a, source)
    const y = lowestTrend(b, source)
    if (x === null || y === null) return (x === null ? 1 : 0) - (y === null ? 1 : 0)
    return sign * (x - y)
  }
  const compare: Record<PrintingSort, ((a: PrintingOut, b: PrintingOut) => number) | null> = {
    owned: null,
    newest: (a, b) => date(b).localeCompare(date(a)) || number(a, b),
    oldest: (a, b) => date(a).localeCompare(date(b)) || number(a, b),
    set: (a, b) => a.set.name.localeCompare(b.set.name) || number(a, b),
    number: (a, b) => number(a, b) || a.set.name.localeCompare(b.set.name),
    price_desc: (a, b) => price(a, b, -1),
    price_asc: (a, b) => price(a, b, 1),
  }
  const fn = compare[sort]
  return fn ? [...printings].sort(fn) : printings
}

export default function CardDetail() {
  const { t } = useTranslation()
  const { cardId, printingId } = useParams()
  const navigate = useNavigate()
  const location = useLocation()
  const card = useQuery({
    queryKey: ['card', Number(cardId)],
    queryFn: () => call(api.GET('/api/cards/{card_id}', { params: { path: { card_id: Number(cardId) } } })),
    // Outdated data is being fetched again by the server: load the card again.
    refetchInterval: (query) => (query.state.data?.refreshing ? 5000 : false),
  })
  const game = useGame(card.data?.game_id)
  const me = useMe()
  const [target, setTarget] = useState<StockTarget | null>(null)
  const [setFilter, setSetFilter] = useState('')
  const url = useUrlState()
  const sortParam = url.get('sort')
  const sort: PrintingSort = sortParam in PRINTING_SORTS ? (sortParam as PrintingSort) : 'owned'
  const finishLabel = useMemo(() => (code: string) => finishName(game, code), [game])

  if (card.isPending) return <span className="loading loading-spinner loading-lg" />
  if (card.isError) return <div className="alert alert-error">{card.error.message}</div>

  const c = card.data
  // Each printing has its own page; the card's address opens the printing the catalog shows.
  if (printingId === undefined && c.default_printing_id !== null && c.default_printing_id !== undefined)
    return <Navigate replace to={`/cards/${c.id}/${c.default_printing_id}${location.search}`} />
  const selected = c.printings.find((p) => p.id === Number(printingId))
  if (!selected && printingId !== undefined)
    return <div className="alert alert-error">{t('This printing does not exist.')}</div>
  // Shown as printed in the printing's own set ("ビードル (Aspicot)").
  const name = selected?.name || c.name
  const translation = selected?.name ? selected.translation : c.translation
  const localNames = Object.entries(selected?.names ?? {}).filter(([, n]) => n !== name && n !== translation)
  const goTo = (p: PrintingOut) => {
    // Another printing has other finishes: only the sort order is kept.
    const sortParam = url.get('sort')
    navigate(`/cards/${c.id}/${p.id}${sortParam ? `?sort=${encodeURIComponent(sortParam)}` : ''}`)
  }
  const owned = c.printings.reduce((sum, p) => sum + p.owned.reduce((s, o) => s + o.quantity, 0), 0)
  // Prices of the user's source (the game's first source when it has not that one).
  const mainSource = game?.price_sources.find((s) => s.id === me.data?.price_source) ?? game?.price_sources[0]
  const sourceName = (id: string) => game?.price_sources.find((s) => s.id === id)?.name ?? id
  const money = (value: string | number | null) => formatMoney(value, mainSource?.currency)
  // Cheapest and most expensive version of the card, over every printing and finish.
  const offers = c.printings.flatMap((p) =>
    p.prices.filter((price) => price.source === mainSource?.id).map((price) => ({ printing: p, price, trend: Number(price.trend) })),
  )
  const cheapest = offers.length ? offers.reduce((a, b) => (b.trend < a.trend ? b : a)) : null
  const dearest = offers.length ? offers.reduce((a, b) => (b.trend > a.trend ? b : a)) : null
  const lowestOffer = offers
    .filter((o) => o.price.low !== null)
    .reduce<(typeof offers)[number] | null>((a, b) => (a && Number(a.price.low) <= Number(b.price.low) ? a : b), null)
  const offerLabel = (o: (typeof offers)[number]) => `${o.printing.set.name} · ${finishLabel(o.price.finish)}`
  // This printing in the chosen finish (default: its cheapest one).
  const ownPrices = selected ? offers.filter((o) => o.printing.id === selected.id) : []
  const finishes = [...new Set([...(selected?.finishes ?? []), ...ownPrices.map((o) => o.price.finish)])]
  const cheapestOwn = ownPrices.length ? ownPrices.reduce((a, b) => (b.trend < a.trend ? b : a)) : null
  const finishParam = url.get('finish')
  const finish = finishes.includes(finishParam) ? finishParam : (cheapestOwn?.price.finish ?? finishes[0] ?? null)
  const thisVersion = ownPrices.find((o) => o.price.finish === finish) ?? null
  const openStock = (p: PrintingOut) =>
    setTarget({
      printingId: p.id,
      title: `${p.name || c.name} - ${p.set.code} ${p.collector_number ?? ''}`,
      finishes: p.finishes,
      languages: p.languages,
    })
  // The API lists owned printings first.
  const words = normalize(setFilter).split(/\s+/).filter(Boolean)
  const printings = sortPrintings(
    words.length
      ? c.printings.filter((p) => {
          const text = normalize(`${p.set.name} ${p.set.code} ${p.collector_number ?? ''} ${p.set.release_date?.slice(0, 4) ?? ''}`)
          return words.every((w) => text.includes(w))
        })
      : c.printings,
    sort,
    mainSource?.id,
  )

  return (
    <div className="flex flex-col gap-6">
      <div className="breadcrumbs text-sm">
        <ul>
          <li><Link to={`/catalog?game=${c.game_id}`}>{game?.name ?? c.game_id}</Link></li>
          <li>{name}</li>
          {selected && (
            <li>
              {selected.set.code}
              {selected.collector_number && ` · ${selected.collector_number}`}
            </li>
          )}
        </ul>
      </div>

      <div className="grid gap-6 md:grid-cols-[minmax(0,320px)_1fr]">
        <div className="flex flex-col gap-3">
          {selected && (
            <CardImage
              key={selected.id}
              src={selected.image}
              back={selected.back_image ?? null}
              alt={name}
              className="w-full max-w-xs shadow-xl rounded-[4.5%]"
            />
          )}
          {selected && (
            <button className="btn btn-primary" onClick={() => openStock(selected)}>
              {t('Add / remove copies')}
            </button>
          )}
        </div>

        <div className="flex flex-col gap-4">
          <div>
            <h1 className="text-3xl font-bold">
              {name}
              {translation && <span className="font-normal text-base-content/60"> ({translation})</span>}
            </h1>
            {localNames.length > 0 && (
              <div className="mt-1 flex flex-wrap gap-2 text-sm text-base-content/70">
                {localNames.map(([lang, name]) => (
                  <span key={lang} className="inline-flex items-center gap-1" title={languageName(lang)}>
                    <LangFlag lang={lang} />
                    {name}
                  </span>
                ))}
              </div>
            )}
            <div className="mt-2 flex flex-wrap items-center gap-2">
              <ColorBadges game={game} colors={c.colors} />
              {owned > 0 && <span className="badge badge-success">{t('{{count}} owned', { count: owned })}</span>}
            </div>
          </div>
          {cheapest && dearest && (
            <div className="flex flex-col gap-2">
            {finishes.length > 1 && (
              <div className="flex flex-wrap items-center gap-2">
                <span className="text-sm text-base-content/60">{t('Finish')}</span>
                <div className="join">
                  {finishes.map((f) => (
                    <button
                      key={f}
                      className={`btn btn-sm join-item ${f === finish ? 'btn-primary' : ''}`}
                      aria-pressed={f === finish}
                      onClick={() => url.set({ finish: f }, false)}
                    >
                      {finishLabel(f)}
                    </button>
                  ))}
                </div>
              </div>
            )}
            <div className="stats stats-vertical bg-base-200 lg:stats-horizontal">
              <div className="stat bg-primary/10 py-3">
                <div className="stat-title">{t('This version')}</div>
                <div className="stat-value text-xl">{thisVersion ? money(thisVersion.trend) : '—'}</div>
                <div className="stat-desc">
                  {finish && finishLabel(finish)}
                  {thisVersion && thisVersion.price.low !== null && ` · ${t('from {{price}}', { price: money(thisVersion.price.low) })}`}
                </div>
              </div>
              <div className="stat py-3">
                <div className="stat-title">{t('Cheapest version')}</div>
                <div className="stat-value text-xl">{money(cheapest.trend)}</div>
                <div className="stat-desc">{offerLabel(cheapest)}</div>
              </div>
              <div className="stat py-3">
                <div className="stat-title">{t('Most expensive version')}</div>
                <div className="stat-value text-xl">{money(dearest.trend)}</div>
                <div className="stat-desc">{offerLabel(dearest)}</div>
              </div>
              {lowestOffer && (
                <div className="stat py-3">
                  <div className="stat-title">{t('Lowest offer')}</div>
                  <div className="stat-value text-xl">{money(lowestOffer.price.low)}</div>
                  <div className="stat-desc">{offerLabel(lowestOffer)}</div>
                </div>
              )}
            </div>
            </div>
          )}
          <div className="card bg-base-200">
            <div className="card-body p-4">
              <Attributes data={c.attributes} />
              {selected && hasVisibleAttributes(selected.attributes) && (
                <>
                  <div className="divider my-1" />
                  <Attributes data={selected.attributes} />
                </>
              )}
            </div>
          </div>
          {selected && game?.has_prices && (
            <div className="card bg-base-200">
              <div className="card-body p-4">
                <h2 className="card-title text-base">
                  {t('Price history')} - {selected.set.code} {selected.collector_number}
                  {finish && ` · ${finishLabel(finish)}`}
                  {mainSource && <span className="text-sm font-normal text-base-content/60">({mainSource.name})</span>}
                </h2>
                <PriceHistory printing={selected} finish={finish} finishLabel={finishLabel} source={mainSource} />
              </div>
            </div>
          )}
        </div>
      </div>

      <div className="flex flex-col gap-2">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h2 className="text-lg font-semibold">{t('{{count}} printings', { count: c.printings.length })}</h2>
          {c.printings.length > 1 && (
            <div className="flex w-full flex-wrap items-center gap-2 sm:w-auto">
            <Select
              className="select-sm w-full sm:w-48"
              aria-label={t('Sort')}
              value={sort}
              onChange={(v) => url.set({ sort: v === 'owned' ? null : v }, false)}
              options={Object.entries(PRINTING_SORTS).map(([value, label]) => ({ value, label: t(label) }))}
            />
            <label className="input input-sm w-full sm:w-72">
              <svg viewBox="0 0 24 24" className="h-4 w-4 fill-none stroke-current stroke-2 opacity-60"><circle cx="11" cy="11" r="7" /><path d="m20 20-3.5-3.5" /></svg>
              <input
                type="search"
                placeholder={t('Find a set (name, code, number, year)')}
                value={setFilter}
                onChange={(e) => setSetFilter(e.target.value)}
              />
            </label>
            </div>
          )}
        </div>
        <div className="overflow-x-auto rounded-box border border-base-300">
          <table className="table table-sm">
            <thead>
              <tr>
                <th>{t('Set')}</th>
                <th>#</th>
                <th>{t('Rarity')}</th>
                <th>{t('Finishes')}</th>
                <th>{t('Price')}</th>
                <th>{t('Owned')}</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {printings.length === 0 && (
                <tr>
                  <td colSpan={7} className="py-6 text-center text-base-content/60">{t('No set matches “{{q}}”.', { q: setFilter })}</td>
                </tr>
              )}
              {printings.map((p) => (
                <tr
                  key={p.id}
                  className={`cursor-pointer hover:bg-base-200 ${p.id === selected?.id ? 'bg-base-200 outline-2 -outline-offset-2 outline-primary' : p.owned.length ? 'bg-success/5' : ''}`}
                  aria-current={p.id === selected?.id ? 'page' : undefined}
                  onClick={() => goTo(p)}
                >
                  <td className={p.owned.length ? 'border-l-4 border-success' : 'border-l-4 border-transparent'}>
                    <div className="flex items-center gap-1.5 font-medium">
                      {p.set.icon && (
                        <img src={p.set.icon} alt="" loading="lazy" className="h-4 w-4 object-contain dark:rounded-sm dark:bg-white/85 dark:p-px" onError={(e) => (e.currentTarget.style.display = 'none')} />
                      )}
                      <Link
                        to={`/cards/${c.id}/${p.id}`}
                        className="link-hover"
                        onClick={(e) => {
                          e.preventDefault()
                          e.stopPropagation()
                          goTo(p)
                        }}
                      >
                        {p.set.name}
                      </Link>
                      {p.id === selected?.id && <span className="badge badge-primary badge-xs">{t('This page')}</span>}
                    </div>
                    <div className="text-xs text-base-content/60">
                      {p.set.code} · {formatDate(p.set.release_date)}
                      {p.set.lang && (
                        <>
                          {' · '}
                          <LangFlag lang={p.set.lang} className="h-3" />
                        </>
                      )}
                    </div>
                  </td>
                  <td>{p.collector_number}</td>
                  <td className="capitalize">{p.rarity}</td>
                  <td>
                    <div className="flex flex-wrap gap-1">
                      {p.finishes.map((f) => <FinishBadge key={f} game={game} finish={f} />)}
                    </div>
                  </td>
                  <td className="whitespace-nowrap">
                    {p.prices.length === 0 && '—'}
                    {p.prices.map((price, i) => (
                      <div key={`${price.source}-${price.finish}`} className="text-xs">
                        {/* Each source's prices under its name. */}
                        {(game?.price_sources.length ?? 0) > 1 && (i === 0 || p.prices[i - 1].source !== price.source) && (
                          <div className={`font-semibold text-base-content/70 ${i > 0 ? 'mt-1' : ''}`}>{sourceName(price.source)}</div>
                        )}
                        <span className="text-base-content/60">{finishLabel(price.finish)}</span>{' '}
                        <span className="font-medium" title={t('Trend price')}>{formatMoney(price.trend, price.currency)}</span>
                        {price.low !== null && (
                          <span className="text-base-content/60" title={t('Lowest offer')}>
                            {' '}
                            ({t('from {{price}}', { price: formatMoney(price.low, price.currency) })})
                          </span>
                        )}
                      </div>
                    ))}
                    <div className="flex flex-wrap gap-x-2">
                      {/* Only web pages: never javascript: or other schemes from data. */}
                      {p.links.filter((l) => /^https?:\/\//.test(l.url)).map((l) => (
                        <a
                          key={l.source}
                          className="link link-primary text-xs"
                          href={l.url}
                          target="_blank"
                          rel="noreferrer noopener"
                          onClick={(e) => e.stopPropagation()}
                        >
                          {l.name} ↗
                        </a>
                      ))}
                    </div>
                  </td>
                  <td>
                    {p.owned.map((o) => (
                      <div key={o.item_id} className="flex items-center gap-1 whitespace-nowrap py-0.5 text-xs">
                        <span className="font-semibold">{o.quantity}×</span>
                        <FinishBadge game={game} finish={o.finish} size="badge-xs" />
                        <ConditionBadge condition={o.condition} size="badge-xs" />
                        <LangFlag lang={o.language} className="h-3" />
                      </div>
                    ))}
                  </td>
                  <td>
                    <button
                      className="btn btn-xs btn-outline"
                      title={t('Add / remove copies')}
                      onClick={(e) => {
                        e.stopPropagation()
                        openStock(p)
                      }}
                    >
                      ±
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
      <StockDialog game={game} target={target} onClose={() => setTarget(null)} />
    </div>
  )
}
