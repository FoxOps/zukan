import { useQuery } from '@tanstack/react-query'
import { useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link, useParams } from 'react-router'
import { api, call, type Schemas } from '../api/client'
import { useGame } from '../api/queries'
import { Attributes } from '../components/Attributes'
import { ConditionBadge, FinishBadge } from '../components/Badges'
import { CardImage } from '../components/CardImage'
import { ColorBadges } from '../components/ColorBadges'
import { PriceChart } from '../components/PriceChart'
import { StockDialog, type StockTarget } from '../components/StockDialog'
import { hasVisibleAttributes } from '../lib/attributes'
import { cardmarketUrl, finishName, formatDate, formatMoney, languageName } from '../lib/format'

type PrintingOut = Schemas['PrintingOut']

function PriceHistory({ printing, finishLabel }: { printing: PrintingOut; finishLabel: (f: string) => string }) {
  const history = useQuery({
    queryKey: ['prices', printing.id],
    queryFn: () => call(api.GET('/api/printings/{printing_id}/prices', { params: { path: { printing_id: printing.id } } })),
  })
  const { data, series } = useMemo(() => {
    const byDate = new Map<string, Record<string, number | string | null>>()
    const names = new Set<string>()
    for (const point of history.data ?? []) {
      const name = finishLabel(point.finish)
      names.add(name)
      const row = byDate.get(point.date) ?? { date: point.date }
      row[name] = point.trend === null ? null : Number(point.trend)
      byDate.set(point.date, row)
    }
    return { data: [...byDate.values()] as { date: string }[], series: [...names] }
  }, [history.data, finishLabel])
  if (history.isPending) return <span className="loading loading-dots" />
  return <PriceChart data={data} series={series} />
}

/** Lower case without accents, to filter sets the way the catalog search works. */
function normalize(text: string): string {
  return text.normalize('NFKD').replace(/\p{M}/gu, '').toLowerCase()
}

export default function CardDetail() {
  const { t } = useTranslation()
  const { cardId } = useParams()
  const card = useQuery({
    queryKey: ['card', Number(cardId)],
    queryFn: () => call(api.GET('/api/cards/{card_id}', { params: { path: { card_id: Number(cardId) } } })),
  })
  const game = useGame(card.data?.game_id)
  const [selectedId, setSelectedId] = useState<number | null>(null)
  const [target, setTarget] = useState<StockTarget | null>(null)
  const [setFilter, setSetFilter] = useState('')
  const finishLabel = useMemo(() => (code: string) => finishName(game, code), [game])

  if (card.isPending) return <span className="loading loading-spinner loading-lg" />
  if (card.isError) return <div className="alert alert-error">{card.error.message}</div>

  const c = card.data
  const selected = c.printings.find((p) => p.id === selectedId) ?? c.printings[0]
  const localNames = Object.entries(selected?.names ?? {}).filter(([, n]) => n !== c.name)
  const owned = c.printings.reduce((sum, p) => sum + p.owned.reduce((s, o) => s + o.quantity, 0), 0)
  // Cheapest and most expensive version of the card, over every printing and finish.
  const offers = c.printings.flatMap((p) => p.prices.map((price) => ({ printing: p, price, trend: Number(price.trend) })))
  const cheapest = offers.length ? offers.reduce((a, b) => (b.trend < a.trend ? b : a)) : null
  const dearest = offers.length ? offers.reduce((a, b) => (b.trend > a.trend ? b : a)) : null
  const lowestOffer = offers
    .filter((o) => o.price.low !== null)
    .reduce<(typeof offers)[number] | null>((a, b) => (a && Number(a.price.low) <= Number(b.price.low) ? a : b), null)
  const offerLabel = (o: (typeof offers)[number]) => `${o.printing.set.name} · ${finishLabel(o.price.finish)}`
  const openStock = (p: PrintingOut) =>
    setTarget({
      printingId: p.id,
      title: `${c.name} - ${p.set.code} ${p.collector_number ?? ''}`,
      finishes: p.finishes,
      languages: p.languages,
    })
  // The API lists owned printings first.
  const words = normalize(setFilter).split(/\s+/).filter(Boolean)
  const printings = words.length
    ? c.printings.filter((p) => {
        const text = normalize(`${p.set.name} ${p.set.code} ${p.collector_number ?? ''} ${p.set.release_date?.slice(0, 4) ?? ''}`)
        return words.every((w) => text.includes(w))
      })
    : c.printings

  return (
    <div className="flex flex-col gap-6">
      <div className="breadcrumbs text-sm">
        <ul>
          <li><Link to={`/catalog?game=${c.game_id}`}>{game?.name ?? c.game_id}</Link></li>
          <li>{c.name}</li>
        </ul>
      </div>

      <div className="grid gap-6 md:grid-cols-[minmax(0,320px)_1fr]">
        <div className="flex flex-col gap-3">
          {selected && (
            <CardImage
              key={selected.id}
              src={selected.image}
              back={(selected.attributes.back_image_url as string | undefined) ?? null}
              alt={c.name}
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
            <h1 className="text-3xl font-bold">{c.name}</h1>
            {localNames.length > 0 && (
              <div className="mt-1 flex flex-wrap gap-2 text-sm text-base-content/70">
                {localNames.map(([lang, name]) => (
                  <span key={lang} title={languageName(lang)}>
                    <span className="badge badge-ghost badge-sm mr-1">{lang}</span>
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
            <div className="stats stats-vertical bg-base-200 sm:stats-horizontal">
              <div className="stat py-3">
                <div className="stat-title">{t('Cheapest version')}</div>
                <div className="stat-value text-xl">{formatMoney(cheapest.trend)}</div>
                <div className="stat-desc">{offerLabel(cheapest)}</div>
              </div>
              <div className="stat py-3">
                <div className="stat-title">{t('Most expensive version')}</div>
                <div className="stat-value text-xl">{formatMoney(dearest.trend)}</div>
                <div className="stat-desc">{offerLabel(dearest)}</div>
              </div>
              {lowestOffer && (
                <div className="stat py-3">
                  <div className="stat-title">{t('Lowest offer')}</div>
                  <div className="stat-value text-xl">{formatMoney(lowestOffer.price.low)}</div>
                  <div className="stat-desc">{offerLabel(lowestOffer)}</div>
                </div>
              )}
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
                </h2>
                <PriceHistory printing={selected} finishLabel={finishLabel} />
              </div>
            </div>
          )}
        </div>
      </div>

      <div className="flex flex-col gap-2">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h2 className="text-lg font-semibold">{t('{{count}} printings', { count: c.printings.length })}</h2>
          {c.printings.length > 1 && (
            <label className="input input-sm w-full sm:w-72">
              <svg viewBox="0 0 24 24" className="h-4 w-4 fill-none stroke-current stroke-2 opacity-60"><circle cx="11" cy="11" r="7" /><path d="m20 20-3.5-3.5" /></svg>
              <input
                type="search"
                placeholder={t('Find a set (name, code, number, year)')}
                value={setFilter}
                onChange={(e) => setSetFilter(e.target.value)}
              />
            </label>
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
                  className={`cursor-pointer hover:bg-base-200 ${p.id === selected?.id ? 'bg-base-200' : p.owned.length ? 'bg-success/5' : ''}`}
                  onClick={() => setSelectedId(p.id)}
                >
                  <td className={p.owned.length ? 'border-l-4 border-success' : 'border-l-4 border-transparent'}>
                    <div className="font-medium">{p.set.name}</div>
                    <div className="text-xs text-base-content/60">
                      {p.set.code} · {formatDate(p.set.release_date)}
                      {p.set.lang && ` · ${languageName(p.set.lang)}`}
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
                    {p.prices.map((price) => (
                      <div key={price.finish} className="text-xs">
                        <span className="text-base-content/60">{finishLabel(price.finish)}</span>{' '}
                        <span className="font-medium" title={t('Cardmarket trend price')}>{formatMoney(price.trend)}</span>
                        {price.low !== null && (
                          <span className="text-base-content/60" title={t('Lowest offer on Cardmarket')}>
                            {' '}
                            ({t('from {{price}}', { price: formatMoney(price.low) })})
                          </span>
                        )}
                      </div>
                    ))}
                    {cardmarketUrl(game, p.cardmarket_id) && (
                      <a
                        className="link link-primary text-xs"
                        href={cardmarketUrl(game, p.cardmarket_id)!}
                        target="_blank"
                        rel="noreferrer noopener"
                        onClick={(e) => e.stopPropagation()}
                      >
                        Cardmarket ↗
                      </a>
                    )}
                  </td>
                  <td>
                    {p.owned.map((o) => (
                      <div key={o.item_id} className="flex items-center gap-1 whitespace-nowrap py-0.5 text-xs">
                        <span className="font-semibold">{o.quantity}×</span>
                        <FinishBadge game={game} finish={o.finish} size="badge-xs" />
                        <ConditionBadge condition={o.condition} size="badge-xs" />
                        <span title={languageName(o.language)}>{o.language}</span>
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
