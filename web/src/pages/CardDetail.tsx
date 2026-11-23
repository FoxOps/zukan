import { useQuery } from '@tanstack/react-query'
import { useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link, Navigate, useLocation, useNavigate, useParams } from 'react-router'
import { api, call } from '../api/client'
import { useGame, useMe } from '../api/queries'
import { Attributes } from '../components/Attributes'
import { LangFlag } from '../components/Badges'
import { CardImage } from '../components/CardImage'
import { CatalogSearch } from '../components/CatalogSearch'
import { Icon } from '../components/Icon'
import { Eyebrow, Metric, Panel } from '../components/Page'
import { RarityBadge } from '../components/RarityBadge'
import { ColorBadges } from '../components/ColorBadges'
import { StockDialog, type StockTarget } from '../components/StockDialog'
import { Select } from '../components/Select'
import { hasVisibleAttributes } from '../lib/attributes'
import { useUrlState } from '../lib/hooks'
import { finishName, formatMoney, languageName, normalize } from '../lib/format'
import { ShownName } from '../components/ShownName'
import { PriceHistory } from './card/PriceHistory'
import { PrintingsTable } from './card/PrintingsTable'
import { PRINTING_SORTS, regionNumbers, sortPrintings, type PrintingOut, type PrintingSort } from './card/printings'

export default function CardDetail() {
  const { t } = useTranslation()
  const { cardId, printingId } = useParams()
  const navigate = useNavigate()
  const location = useLocation()
  const card = useQuery({
    queryKey: ['card', Number(cardId)],
    meta: { inlineError: true },
    queryFn: () => call(api.GET('/api/cards/{card_id}', { params: { path: { card_id: Number(cardId) } } })),
    // Outdated data is being fetched again by the server: load the card again.
    refetchInterval: (query) => (query.state.data?.refreshing ? 5000 : false),
  })
  const game = useGame(card.data?.game_id)
  const me = useMe()
  const [target, setTarget] = useState<StockTarget | null>(null)
  const [setFilter, setSetFilter] = useState('')
  // Price source of the history chart (default: the main one).
  const [chartSourceId, setChartSourceId] = useState<string | null>(null)
  const url = useUrlState()
  const sortParam = url.get('sort')
  const tab = url.get('tab') || 'printings'
  // Own keys only: `__proto__`, `toString`... are no sort.
  const sort: PrintingSort = Object.hasOwn(PRINTING_SORTS, sortParam) ? (sortParam as PrintingSort) : 'owned'
  const finishLabel = useMemo(() => (code: string) => finishName(game, code), [game])

  if (card.isPending) return <span className="loading loading-spinner loading-lg" aria-label={t('Loading')} />
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
  // The card's names in every language of every printing, each spelling once.
  const localNames = Object.entries(c.names ?? {}).filter(
    ([, n], i, all) => n !== name && n !== translation && all.findIndex(([, other]) => other === n) === i,
  )
  const goTo = (p: PrintingOut) => {
    // Another printing has other finishes: only the sort order is kept.
    const keep = new URLSearchParams()
    for (const key of ['sort', 'tab']) if (url.get(key)) keep.set(key, url.get(key))
    navigate(`/cards/${c.id}/${p.id}${keep.size ? `?${keep}` : ''}`)
  }
  const owned = c.printings.reduce((sum, p) => sum + p.owned.reduce((s, o) => s + o.quantity, 0), 0)
  // The user's price sources this game has, main one first (the game's first source when
  // it has none of them).
  const wanted = me.data?.price_sources ?? []
  const gameSources = game?.price_sources ?? []
  const chosenSources = gameSources.filter((s) => wanted.includes(s.id)).sort((a, b) => wanted.indexOf(a.id) - wanted.indexOf(b.id))
  const sources = chosenSources.length ? chosenSources : gameSources.slice(0, 1)
  const mainSource = sources[0]
  const chartSource = sources.find((s) => s.id === chartSourceId) ?? mainSource
  const sourceName = (id: string) => gameSources.find((s) => s.id === id)?.name ?? id
  // Every version of the card from one source, over every printing and finish.
  const offersOf = (source: string | undefined) =>
    c.printings.flatMap((p) =>
      p.prices.filter((price) => price.source === source).map((price) => ({ printing: p, price, trend: Number(price.trend) })),
    )
  type Offer = ReturnType<typeof offersOf>[number]
  const offerLabel = (o: Offer) => `${o.printing.set.name} · ${finishLabel(o.price.finish)}`
  // This printing's finishes; the chosen one (default: its cheapest at the main source).
  const ownPrices = selected ? offersOf(mainSource?.id).filter((o) => o.printing.id === selected.id) : []
  const finishes = [...new Set([...(selected?.finishes ?? []), ...ownPrices.map((o) => o.price.finish)])]
  const cheapestOwn = ownPrices.length ? ownPrices.reduce((a, b) => (b.trend < a.trend ? b : a)) : null
  const finishParam = url.get('finish')
  const finish = finishes.includes(finishParam) ? finishParam : (cheapestOwn?.price.finish ?? finishes[0] ?? null)
  // Price summary per source: this version, cheapest and most expensive versions, lowest offer.
  const stats = sources
    .map((source) => {
      const offers = offersOf(source.id)
      if (!offers.length) return null
      return {
        source,
        money: (value: string | number | null) => formatMoney(value, source.currency),
        thisVersion: selected ? (offers.find((o) => o.printing.id === selected.id && o.price.finish === finish) ?? null) : null,
        cheapest: offers.reduce((a, b) => (b.trend < a.trend ? b : a)),
        dearest: offers.reduce((a, b) => (b.trend > a.trend ? b : a)),
        lowestOffer: offers
          .filter((o) => o.price.low !== null)
          .reduce<Offer | null>((a, b) => (a && Number(a.price.low) <= Number(b.price.low) ? a : b), null),
      }
    })
    .filter((x) => x !== null)
  const stockTarget = (p: PrintingOut): StockTarget => ({
    printingId: p.id,
    title: `${p.name || c.name} - ${p.set.code} ${p.collector_number ?? ''}`,
    finishes: p.finishes,
    languages: p.languages,
    label: `${p.set.code} ${p.collector_number ?? ''} · ${p.set.name}${p.set.release_date ? ` (${p.set.release_date.slice(0, 4)})` : ''}`,
  })
  const openStock = (p: PrintingOut) => setTarget(stockTarget(p))
  // The API lists owned printings first.
  const words = normalize(setFilter).split(/\s+/).filter(Boolean)
  const printings = sortPrintings(
    words.length
      ? c.printings.filter((p) => {
          const text = normalize(
            `${p.set.name} ${p.set.code} ${p.collector_number ?? ''} ${Object.values(regionNumbers(p)).join(' ')} ${p.set.release_date?.slice(0, 4) ?? ''}`,
          )
          return words.every((w) => text.includes(w))
        })
      : c.printings,
    sort,
    mainSource?.id,
  )


  const thisPrice = stats[0]?.thisVersion ?? null
  const tabs = [
    { id: 'printings', label: t('{{count}} printings', { count: c.printings.length }) },
    ...(stats.length > 0 || (selected && game?.has_prices) ? [{ id: 'prices', label: t('Prices') }] : []),
    { id: 'details', label: t('Card details') },
  ]
  const shownTab = tabs.some((x) => x.id === tab) ? tab : 'printings'

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <nav className="breadcrumbs text-sm" aria-label={t('Breadcrumb')}>
          <ul>
            <li><Link to="/catalog">{t('Catalog')}</Link></li>
            <li><Link to={`/catalog?game=${c.game_id}`}>{game?.name ?? c.game_id}</Link></li>
            <li aria-current="page">{name}</li>
          </ul>
        </nav>
        <CatalogSearch game={c.game_id} />
      </div>

      <div className="grid gap-8 md:grid-cols-[minmax(0,300px)_minmax(0,1fr)]">
        <div className="flex flex-col items-center gap-3 md:items-stretch">
          {selected && (
            <CardImage
              key={selected.id}
              src={selected.image}
              back={selected.back_image ?? null}
              alt={name}
              flipOnClick
              landscape={selected.orientation === 'landscape'}
              game={c.game_id}
              setCode={selected.set.code}
              number={selected.collector_number}
              className="w-full max-w-xs rounded-[4.5%] shadow-xl"
            />
          )}
          {selected?.back_image && <p className="text-xs text-base-content/70">{t('Click the card to see its back.')}</p>}
        </div>

        <div className="flex min-w-0 flex-col gap-5">
          <div>
            {selected && (
              <Eyebrow className="flex flex-wrap items-center gap-x-1.5">
                <span>{selected.set.code}</span>
                {selected.collector_number && <span>· {selected.collector_number}</span>}
                {selected.rarity && (
                  <>
                    <span>·</span>
                    <RarityBadge game={game} rarity={selected.rarity} code={selected.rarity_code} lang={selected.set.lang} />
                  </>
                )}
              </Eyebrow>
            )}
            <h1 className="mt-2 break-words text-3xl lg:text-4xl">
              <ShownName name={name} translation={translation} />
            </h1>
            {selected && <p className="mt-1 text-base-content/70">{selected.set.name}</p>}
            {localNames.length > 0 && (
              <div className="mt-2 flex flex-wrap gap-2 text-sm text-base-content/70">
                {localNames.map(([lang, name]) => (
                  <span key={lang} className="inline-flex items-center gap-1" title={languageName(lang)}>
                    <LangFlag lang={lang} />
                    {name}
                  </span>
                ))}
              </div>
            )}
            {c.colors.length > 0 && (
              <div className="mt-2">
                <ColorBadges game={game} colors={c.colors} />
              </div>
            )}
          </div>

          <div className="flex flex-wrap items-end justify-between gap-4 border-t border-base-300 pt-5">
            <div className="min-w-0">
              <div className="text-sm text-base-content/70">
                {t('This printing')}
                {finish && ` · ${finishLabel(finish)}`}
              </div>
              <div className="font-display text-4xl font-extrabold tabular-nums">
                {thisPrice ? stats[0].money(thisPrice.trend) : '—'}
              </div>
              {stats[0] && (
                <div className="text-xs text-base-content/70">
                  {stats[0].source.name}
                  {thisPrice && thisPrice.price.low !== null && ` · ${t('from {{price}}', { price: stats[0].money(thisPrice.price.low) })}`}
                </div>
              )}
            </div>
            {selected && (
              <button className="btn btn-primary min-h-11 gap-2 max-sm:w-full" onClick={() => openStock(selected)}>
                <Icon name="plus" />
                {t('Add / remove copies')}
              </button>
            )}
          </div>
          {finishes.length > 1 && stats.length > 0 && (
            <div className="flex flex-wrap items-center gap-2">
              <span className="text-sm text-base-content/70">{t('Finish')}</span>
              <div className="join flex-wrap">
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
          <div className="grid gap-3 sm:grid-cols-3">
            <Metric label={t('Owned copies')} value={owned} />
            <Metric label={t('Available printings')} value={c.printings.length} />
            <Metric label={t('Price sources')} value={<span className="text-xl">{sources.map((s) => s.currency).filter((x, i, all) => all.indexOf(x) === i).join(' · ') || '—'}</span>}>
              {sources.map((s) => s.name).join(', ')}
            </Metric>
          </div>

          <div role="tablist" aria-label={t('Card sections')} className="flex gap-1 overflow-x-auto border-b border-base-300">
            {tabs.map((x) => (
              <button
                key={x.id}
                role="tab"
                id={`tab-${x.id}`}
                aria-selected={shownTab === x.id}
                aria-controls={`panel-${x.id}`}
                className={`min-h-11 shrink-0 px-4 font-semibold ${shownTab === x.id ? 'shadow-[inset_0_-3px_0_var(--color-primary)]' : 'text-base-content/70 hover:text-base-content'}`}
                onClick={() => url.set({ tab: x.id === 'printings' ? null : x.id }, false)}
              >
                {x.label}
              </button>
            ))}
          </div>

          {shownTab === 'prices' && (
            <div role="tabpanel" id="panel-prices" aria-labelledby="tab-prices" className="flex flex-col gap-4">
              {stats.map(({ source, money, cheapest, dearest, lowestOffer }) => (
                <Panel key={source.id} title={stats.length > 1 ? source.name : t('Versions of this card')} subtitle={stats.length > 1 ? undefined : source.name}>
                  <div className="grid gap-3 sm:grid-cols-3">
                    <Metric label={t('Cheapest version')} value={<span className="text-xl">{money(cheapest.trend)}</span>}>{offerLabel(cheapest)}</Metric>
                    <Metric label={t('Most expensive version')} value={<span className="text-xl">{money(dearest.trend)}</span>}>{offerLabel(dearest)}</Metric>
                    {lowestOffer && (
                      <Metric label={t('Lowest offer')} value={<span className="text-xl">{money(lowestOffer.price.low)}</span>}>{offerLabel(lowestOffer)}</Metric>
                    )}
                  </div>
                </Panel>
              ))}
              {selected && game?.has_prices && (
                <Panel
                  title={t('Price history')}
                  subtitle={`${selected.set.code} ${selected.collector_number ?? ''}${finish ? ` · ${finishLabel(finish)}` : ''}${sources.length === 1 && chartSource ? ` · ${chartSource.name}` : ''}`}
                  aside={
                    sources.length > 1 && (
                      <div className="join">
                        {sources.map((source) => (
                          <button
                            key={source.id}
                            className={`btn btn-sm join-item ${source.id === chartSource?.id ? 'btn-primary' : ''}`}
                            aria-pressed={source.id === chartSource?.id}
                            onClick={() => setChartSourceId(source.id)}
                          >
                            {source.name}
                          </button>
                        ))}
                      </div>
                    )
                  }
                >
                  <PriceHistory printing={selected} finish={finish} finishLabel={finishLabel} source={chartSource} />
                </Panel>
              )}
            </div>
          )}

          {shownTab === 'details' && (
            <div role="tabpanel" id="panel-details" aria-labelledby="tab-details">
              <Panel title={t('Card information')}>
                <Attributes data={c.attributes} game={game} />
                {selected && hasVisibleAttributes(selected.attributes) && (
                  <>
                    <div className="divider my-1" />
                    <Attributes data={selected.attributes} game={game} />
                  </>
                )}
              </Panel>
            </div>
          )}
        </div>
      </div>

      {shownTab === 'printings' && (
        <section role="tabpanel" id="panel-printings" aria-labelledby="tab-printings" className="flex flex-col gap-3">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <h2 className="text-xl">{t('Choose a printing')}</h2>
            {c.printings.length > 1 && (
              <div className="flex w-full flex-wrap items-center gap-2 sm:w-auto">
                <Select
                  className="w-full sm:w-52"
                  aria-label={t('Sort')}
                  value={sort}
                  onChange={(v) => url.set({ sort: v === 'owned' ? null : v }, false)}
                  options={Object.entries(PRINTING_SORTS).map(([value, label]) => ({ value, label: t(label) }))}
                />
                <label className="input w-full sm:w-72">
                  <Icon name="search" className="h-4 w-4 opacity-70" />
                  <input
                    type="search"
                    aria-label={t('Find a set (name, code, number, year)')}
                    placeholder={t('Find a set (name, code, number, year)')}
                    value={setFilter}
                    onChange={(e) => setSetFilter(e.target.value)}
                  />
                </label>
              </div>
            )}
          </div>
          <PrintingsTable
            cardId={c.id}
            gameId={c.game_id}
            game={game}
            printings={printings}
            selectedId={selected?.id}
            sourceCount={sources.length}
            sourceName={sourceName}
            filter={setFilter}
            goTo={goTo}
            openStock={openStock}
          />
        </section>
      )}
      <StockDialog game={game} target={target} versions={target ? sortPrintings(c.printings, 'newest', undefined).map(stockTarget) : []} onClose={() => setTarget(null)} />
    </div>
  )
}
