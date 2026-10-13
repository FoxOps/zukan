import { useQuery } from '@tanstack/react-query'
import { useMemo, useState } from 'react'
import { Link, useParams } from 'react-router'
import { api, call, type Schemas } from '../api/client'
import { useGame } from '../api/queries'
import { Attributes } from '../components/Attributes'
import { hasVisibleAttributes } from '../lib/attributes'
import { CardImage } from '../components/CardImage'
import { ColorBadges } from '../components/ColorBadges'
import { PriceChart } from '../components/PriceChart'
import { StockDialog, type StockTarget } from '../components/StockDialog'
import { formatDate, formatMoney, languageName } from '../lib/format'

type PrintingOut = Schemas['PrintingOut']

function PriceHistory({ printing, finishName }: { printing: PrintingOut; finishName: (f: string) => string }) {
  const history = useQuery({
    queryKey: ['prices', printing.id],
    queryFn: () => call(api.GET('/api/printings/{printing_id}/prices', { params: { path: { printing_id: printing.id } } })),
  })
  const { data, series } = useMemo(() => {
    const byDate = new Map<string, Record<string, number | string | null>>()
    const names = new Set<string>()
    for (const point of history.data ?? []) {
      const name = finishName(point.finish)
      names.add(name)
      const row = byDate.get(point.date) ?? { date: point.date }
      row[name] = point.trend === null ? null : Number(point.trend)
      byDate.set(point.date, row)
    }
    return { data: [...byDate.values()] as { date: string }[], series: [...names] }
  }, [history.data, finishName])
  if (history.isPending) return <span className="loading loading-dots" />
  return <PriceChart data={data} series={series} />
}

export default function CardDetail() {
  const { cardId } = useParams()
  const card = useQuery({
    queryKey: ['card', Number(cardId)],
    queryFn: () => call(api.GET('/api/cards/{card_id}', { params: { path: { card_id: Number(cardId) } } })),
  })
  const game = useGame(card.data?.game_id)
  const [selectedId, setSelectedId] = useState<number | null>(null)
  const [target, setTarget] = useState<StockTarget | null>(null)

  if (card.isPending) return <span className="loading loading-spinner loading-lg" />
  if (card.isError) return <div className="alert alert-error">{card.error.message}</div>

  const c = card.data
  const selected = c.printings.find((p) => p.id === selectedId) ?? c.printings[0]
  const finishName = (code: string) => game?.finishes.find((f) => f.code === code)?.name ?? code
  const localNames = Object.entries(selected?.names ?? {}).filter(([, n]) => n !== c.name)
  const owned = c.printings.reduce((sum, p) => sum + p.owned.reduce((s, o) => s + o.quantity, 0), 0)
  const openStock = (p: PrintingOut) =>
    setTarget({
      printingId: p.id,
      title: `${c.name} — ${p.set.code} ${p.collector_number ?? ''}`,
      finishes: p.finishes,
      languages: p.languages,
    })

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
              Add / remove copies
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
              {owned > 0 && <span className="badge badge-success">{owned} owned</span>}
            </div>
          </div>
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
                  Price history — {selected.set.code} {selected.collector_number}
                </h2>
                <PriceHistory printing={selected} finishName={finishName} />
              </div>
            </div>
          )}
        </div>
      </div>

      <div className="overflow-x-auto rounded-box border border-base-300">
        <table className="table table-sm">
          <thead>
            <tr>
              <th>Set</th>
              <th>#</th>
              <th>Rarity</th>
              <th>Finishes</th>
              <th>Price</th>
              <th>Owned</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {c.printings.map((p) => (
              <tr
                key={p.id}
                className={`cursor-pointer hover:bg-base-200 ${p.id === selected?.id ? 'bg-base-200' : ''}`}
                onClick={() => setSelectedId(p.id)}
              >
                <td>
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
                    {p.finishes.map((f) => <span key={f} className="badge badge-ghost badge-sm">{finishName(f)}</span>)}
                  </div>
                </td>
                <td className="whitespace-nowrap">
                  {p.prices.length === 0 && '—'}
                  {p.prices.map((price) => (
                    <div key={price.finish} className="text-xs">
                      <span className="text-base-content/60">{finishName(price.finish)}</span>{' '}
                      <span className="font-medium">{formatMoney(price.trend)}</span>
                    </div>
                  ))}
                </td>
                <td>
                  {p.owned.map((o) => (
                    <div key={o.item_id} className="text-xs whitespace-nowrap">
                      <span className="font-semibold">{o.quantity}×</span> {finishName(o.finish)} {o.condition} {o.language}
                    </div>
                  ))}
                </td>
                <td>
                  <button
                    className="btn btn-xs btn-outline"
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
      <StockDialog game={game} target={target} onClose={() => setTarget(null)} />
    </div>
  )
}
