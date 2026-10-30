import { keepPreviousData, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useNavigate } from 'react-router'
import { api, call, type Schemas } from '../api/client'
import { useGames } from '../api/queries'
import { cardLink } from '../pages/catalog/types'
import { PriceRange } from '../pages/catalog/PriceRange'
import { TYPE_TO_SEARCH } from '../lib/typeToSearch'
import { CardImage } from './CardImage'
import { ShownName } from './ShownName'
import { StockDialog, type StockTarget } from './StockDialog'

type Card = Schemas['CardSummaryOut']

const RESULTS = 10

/** Search the catalog from a card's page: a list of matches under the field, to open a
 * card or add copies of it without going back to the catalog. */
export function CatalogSearch({ game }: { game: string }) {
  const { t } = useTranslation()
  const navigate = useNavigate()
  const client = useQueryClient()
  const { data: games = [] } = useGames()
  const [text, setText] = useState('')
  const [q, setQ] = useState('')
  const [allGames, setAllGames] = useState(false)
  const [open, setOpen] = useState(false)
  const [active, setActive] = useState(0)
  const [target, setTarget] = useState<{ target: StockTarget; versions: StockTarget[]; game: string } | null>(null)
  const box = useRef<HTMLDivElement>(null)
  const timer = useRef<ReturnType<typeof setTimeout>>(undefined)
  const scope = allGames ? '' : game

  const results = useQuery({
    queryKey: ['card-search', scope, q],
    enabled: q.trim().length >= 2,
    placeholderData: keepPreviousData,
    queryFn: () =>
      call(
        api.GET('/api/cards', {
          params: { query: { q, game: scope || undefined, page_size: RESULTS } },
        }),
      ),
  })
  const cards = q.trim().length >= 2 ? (results.data?.items ?? []) : []

  useEffect(() => {
    const outside = (e: MouseEvent) => {
      if (!box.current?.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener('mousedown', outside)
    return () => document.removeEventListener('mousedown', outside)
  }, [])

  const type = (next: string) => {
    setText(next)
    setOpen(true)
    setActive(0)
    clearTimeout(timer.current)
    timer.current = setTimeout(() => setQ(next), 250)
  }
  const clear = () => {
    clearTimeout(timer.current)
    setText('')
    setQ('')
    setOpen(false)
  }
  const go = (card: Card) => {
    clear()
    navigate(cardLink(card))
  }
  // The card's versions, for the stock dialog (the shown one preselected).
  const add = async (card: Card) => {
    const full = await client.fetchQuery({
      queryKey: ['card', card.id],
      queryFn: () => call(api.GET('/api/cards/{card_id}', { params: { path: { card_id: card.id } } })),
    })
    const versions = full.printings.map((p) => ({
      printingId: p.id,
      title: `${p.name || full.name} - ${p.set.code} ${p.collector_number ?? ''}`,
      finishes: p.finishes,
      languages: p.languages,
      label: `${p.set.code} ${p.collector_number ?? ''} · ${p.set.name}${p.set.release_date ? ` (${p.set.release_date.slice(0, 4)})` : ''}`,
    }))
    const shown = versions.find((v) => v.printingId === card.printing_id) ?? versions[0]
    if (shown) {
      setOpen(false)
      setTarget({ target: shown, versions, game: card.game_id })
    }
  }

  return (
    <div ref={box} className="relative w-full sm:w-96">
      <label className="input w-full">
        <svg viewBox="0 0 24 24" className="h-4 w-4 fill-none stroke-current stroke-2 opacity-60" aria-hidden><circle cx="11" cy="11" r="7" /><path d="m20 20-3.5-3.5" /></svg>
        <input
          {...TYPE_TO_SEARCH}
          type="text"
          role="combobox"
          aria-expanded={open && cards.length > 0}
          aria-controls="catalog-search-results"
          enterKeyHint="search"
          placeholder={t('Search the catalog to add a card')}
          value={text}
          onChange={(e) => type(e.target.value)}
          onFocus={() => setOpen(true)}
          onKeyDown={(e) => {
            if (e.key === 'Escape') {
              if (open && cards.length) setOpen(false)
              else clear()
            } else if (e.key === 'ArrowDown' && cards.length) {
              e.preventDefault()
              setOpen(true)
              setActive((i) => (i + 1) % cards.length)
            } else if (e.key === 'ArrowUp' && cards.length) {
              e.preventDefault()
              setActive((i) => (i - 1 + cards.length) % cards.length)
            } else if (e.key === 'Enter' && open && cards[active]) {
              e.preventDefault()
              if (e.shiftKey) void add(cards[active])
              else go(cards[active])
            }
          }}
        />
        {results.isFetching && <span className="loading loading-spinner loading-xs" />}
        {text && (
          <button type="button" className="btn btn-circle btn-ghost btn-xs" onClick={clear} aria-label={t('Clear search')} title={t('Clear search')}>
            <svg viewBox="0 0 24 24" className="h-3.5 w-3.5 fill-none stroke-current stroke-2" aria-hidden><path d="M6 6l12 12M18 6 6 18" /></svg>
          </button>
        )}
      </label>
      {open && q.trim().length >= 2 && (
        <div className="absolute z-30 mt-1 w-full rounded-box border border-base-300 bg-base-100 shadow-lg">
          <label className="flex cursor-pointer items-center gap-2 border-b border-base-300 px-3 py-2 text-xs">
            <input type="checkbox" className="toggle toggle-xs" checked={allGames} onChange={(e) => setAllGames(e.target.checked)} />
            {t('All games')}
          </label>
          {cards.length === 0 ? (
            <div className="px-3 py-3 text-sm text-base-content/60">{results.isFetching ? t('Searching…') : t('No cards found')}</div>
          ) : (
            <ul id="catalog-search-results" role="listbox" className="max-h-[60vh] overflow-y-auto py-1">
              {cards.map((card, i) => {
                const cardGame = games.find((g) => g.id === card.game_id)
                return (
                  <li
                    key={card.id}
                    role="option"
                    aria-selected={i === active}
                    className={`flex items-center gap-3 px-3 py-1.5 ${i === active ? 'bg-base-200' : ''}`}
                    onMouseEnter={() => setActive(i)}
                  >
                    <button type="button" className="flex min-w-0 flex-1 items-center gap-3 text-left" onClick={() => go(card)}>
                      <span className="w-9 shrink-0">
                        <CardImage thumb src={card.image} alt="" landscape={card.orientation === 'landscape'} />
                      </span>
                      <span className="min-w-0 flex-1">
                        <span className="block truncate text-sm font-medium">
                          <ShownName name={card.name} translation={card.translation} />
                        </span>
                        <span className="block truncate text-xs text-base-content/60">
                          {allGames && `${cardGame?.name ?? card.game_id} · `}
                          {card.set ? `${card.set.code} ${card.collector_number ?? ''} · ${card.set.name}` : t('{{count}} printings', { count: card.printing_count })}
                        </span>
                      </span>
                      <span className="shrink-0 text-xs font-medium"><PriceRange card={card} /></span>
                    </button>
                    <button
                      type="button"
                      className="btn btn-circle btn-primary btn-xs shrink-0"
                      onClick={() => void add(card)}
                      aria-label={t('Add / remove copies')}
                      title={`${t('Add / remove copies')} (Shift+Enter)`}
                    >
                      +
                    </button>
                  </li>
                )
              })}
            </ul>
          )}
        </div>
      )}
      <StockDialog
        game={games.find((g) => g.id === target?.game)}
        target={target?.target ?? null}
        versions={target?.versions ?? []}
        onClose={() => setTarget(null)}
      />
    </div>
  )
}
