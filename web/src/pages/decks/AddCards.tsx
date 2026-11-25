import { keepPreviousData, useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { api, call, type Schemas } from '../../api/client'
import { useGame } from '../../api/queries'
import { CardImage } from '../../components/CardImage'
import { AdvancedFilters, ColorFilter, SearchInput, SetSelect, type ColorMode } from '../../components/Filters'
import { Pagination } from '../../components/Pagination'
import { Select } from '../../components/Select'
import { ShownName } from '../../components/ShownName'

type Card = Schemas['CardSummaryOut']
type Entry = Schemas['DeckEntryOut']
type Section = Schemas['DeckSectionOut']['id']

const PAGE_SIZE = 24

/** Copies of a card in the deck ("× 3"), and the user's copies. */
function Counts({ card, entry }: { card: Card; entry?: Entry }) {
  const { t } = useTranslation()
  return (
    <>
      {entry && <span className="badge badge-sm badge-primary badge-soft">{t('{{n}} in deck', { n: entry.requested })}</span>}
      <span className={`badge badge-sm ${card.owned_copies ? 'badge-info badge-soft' : 'badge-ghost'}`}>{t('Owned {{n}}', { n: card.owned_copies ?? 0 })}</span>
    </>
  )
}

/** Search the deck game's catalog like the Catalog page (name in any language, set,
 * colors, game filters, owned cards only) and add cards to a section. With a set
 * chosen, the card's printing of that set is added; otherwise any printing. The main
 * deck takes each card to its own section (a rune to the rune deck, a site to the
 * atlas); with one section (Pokémon, Lorcana) there is no choice. Results follow the
 * deck page's list / images view. */
export function AddCards({
  deck,
  entries,
  onAdd,
  sections,
  busy,
  view,
}: {
  deck: Schemas['DeckOut']
  entries: Entry[]
  onAdd: (cardId: number, section: Section, printingId: number | null) => void
  // The format's sections and their shown names.
  sections: { id: Section; name: string }[]
  busy: boolean
  // The deck page's view: 'list' or 'images'.
  view: string
}) {
  const { t } = useTranslation()
  const game = useGame(deck.game_id)
  const [open, setOpen] = useState(entries.length === 0)
  const [q, setQ] = useState('')
  const [setId, setSetId] = useState('')
  const [colors, setColors] = useState<string[]>([])
  const [colorMode, setColorMode] = useState<ColorMode>('include')
  const [attrs, setAttrs] = useState<string[]>([])
  const [owned, setOwned] = useState(false)
  const [page, setPage] = useState(1)
  const [section, setSection] = useState<Section>('main')
  // Any change of the search goes back to its first page.
  const refine = <T,>(set: (value: T) => void) => (value: T) => {
    set(value)
    setPage(1)
  }
  const filtered = !!(q || setId || colors.length || attrs.length || owned)
  const results = useQuery({
    queryKey: ['deck-card-search', deck.game_id, q, setId, colors, colorMode, attrs, owned, page],
    enabled: open && filtered,
    placeholderData: keepPreviousData,
    queryFn: ({ signal }) =>
      call(
        api.GET('/api/cards', {
          signal,
          params: {
            query: {
              game: deck.game_id,
              q: q || undefined,
              set_id: setId ? Number(setId) : undefined,
              color: colors.length ? colors : undefined,
              color_mode: colors.length ? colorMode : undefined,
              attr: attrs.length ? attrs : undefined,
              owned: owned || undefined,
              sort: setId ? 'number' : undefined,
              page,
              page_size: PAGE_SIZE,
            },
          },
        }),
      ),
  })
  const cards = filtered ? (results.data?.items ?? []) : []
  const inDeck = (card: Card) => entries.find((e) => e.card_id === card.id)
  const add = (card: Card) => onAdd(card.id, section, setId && card.printing_id ? card.printing_id : null)
  const addButton = (card: Card) => (
    <button
      type="button"
      className="btn btn-primary btn-xs"
      disabled={busy}
      onClick={() => add(card)}
      title={setId && card.set ? t('Add the {{set}} printing', { set: card.set.code }) : t('Add one copy (any printing)')}
    >
      +1
    </button>
  )

  return (
    <div className="card rounded-[20px] border border-base-300 bg-base-100">
      <div className="card-body gap-3 p-4">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <button type="button" className="flex items-center gap-2 font-semibold" aria-expanded={open} onClick={() => setOpen((o) => !o)}>
            <span className={`transition-transform ${open ? 'rotate-90' : ''}`} aria-hidden>
              ▸
            </span>
            {t('Add cards')}
          </button>
          {open && sections.length > 1 && (
            <label className="flex items-center gap-2 text-sm">
              <span className="text-base-content/70">{t('Add to')}</span>
              <Select
                className="select-sm w-48"
                value={section}
                onChange={(v) => setSection(v as Section)}
                aria-label={t('Section')}
                options={sections.map((s) => ({ value: s.id, label: s.name }))}
              />
            </label>
          )}
        </div>
        {open && (
          <>
            <div className="flex flex-wrap items-center gap-3">
              <SearchInput value={q} onChange={refine(setQ)} placeholder={t('Name in any language')} />
              <SetSelect game={deck.game_id} value={setId} onChange={refine(setSetId)} />
              <label className="flex items-center gap-2 text-sm">
                <input type="checkbox" className="toggle toggle-sm toggle-primary" checked={owned} onChange={(e) => refine(setOwned)(e.target.checked)} />
                {t('Owned cards only')}
              </label>
            </div>
            <ColorFilter game={game} value={colors} onChange={refine(setColors)} mode={colorMode} onModeChange={refine(setColorMode)} />
            <AdvancedFilters game={game} value={attrs} onChange={refine(setAttrs)} />
            {setId && <p className="text-xs text-base-content/70">{t('A set is chosen: its printing of the card is added.')}</p>}
            {!filtered ? (
              <p className="text-sm text-base-content/70">{t('Search by name or choose filters to list cards.')}</p>
            ) : results.isError ? (
              <div className="alert alert-error">{results.error.message}</div>
            ) : results.data ? (
              <>
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <div className="flex items-center gap-3 text-sm text-base-content/70">
                    {t('{{count}} cards', { count: results.data.total })}
                    {results.isPlaceholderData && <span className="loading loading-spinner loading-xs" aria-label={t('Loading')} />}
                  </div>
                </div>
                {cards.length === 0 ? (
                  <p className="text-sm text-base-content/70">{t('No cards found')}</p>
                ) : view === 'images' ? (
                  <div className="grid grid-cols-3 gap-3 sm:grid-cols-4 md:grid-cols-6 2xl:grid-cols-8">
                    {cards.map((card) => (
                      <div key={card.id} className="flex flex-col gap-1">
                        {/* Not a <button>: the flip button of double-faced cards sits inside
                            (it stops its click, so turning the card adds nothing). */}
                        <div
                          role="button"
                          tabIndex={0}
                          aria-disabled={busy}
                          className="group relative cursor-pointer"
                          onClick={() => !busy && add(card)}
                          onKeyDown={(e) => {
                            if (e.target !== e.currentTarget || (e.key !== 'Enter' && e.key !== ' ')) return
                            e.preventDefault()
                            if (!busy) add(card)
                          }}
                          title={card.name}
                        >
                          <CardImage thumb src={card.image} back={card.back_image} alt={card.name} game={deck.game_id} landscape={card.orientation === 'landscape'} faceClassName="transition-transform group-hover:-translate-y-1 group-hover:scale-[1.02]" />
                          <span className="badge badge-primary badge-sm absolute right-[3%] top-[3%] shadow">+1</span>
                        </div>
                        <span className="truncate text-xs font-medium">
                          <ShownName name={card.name} translation={card.translation} />
                        </span>
                        <div className="flex flex-wrap gap-1">
                          <Counts card={card} entry={inDeck(card)} />
                        </div>
                      </div>
                    ))}
                  </div>
                ) : (
                  <ul className="flex flex-col divide-y divide-base-300 rounded-box bg-base-100">
                    {cards.map((card) => (
                      <li key={card.id} className="flex items-center gap-2 px-3 py-1.5">
                        <span className="block w-8 shrink-0">
                          <CardImage thumb="small" src={card.image} alt="" game={deck.game_id} landscape={card.orientation === 'landscape'} />
                        </span>
                        <span className="min-w-0 flex-1">
                          <span className="block truncate text-sm">
                            <ShownName name={card.name} translation={card.translation} />
                          </span>
                          {card.set && (
                            <span className="font-mono text-xs text-base-content/70">
                              {card.set.code} {card.collector_number}
                            </span>
                          )}
                        </span>
                        <span className="flex max-w-[45%] flex-wrap justify-end gap-1 sm:max-w-none">
                          <Counts card={card} entry={inDeck(card)} />
                        </span>
                        {addButton(card)}
                      </li>
                    ))}
                  </ul>
                )}
                <div className="flex justify-center">
                  <Pagination page={page} pageSize={PAGE_SIZE} total={results.data.total} onChange={setPage} />
                </div>
              </>
            ) : (
              <span className="loading loading-dots loading-md mx-auto" />
            )}
          </>
        )}
      </div>
    </div>
  )
}
