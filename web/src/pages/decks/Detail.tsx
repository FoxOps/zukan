import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { type CSSProperties, useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link, Navigate, useNavigate, useParams } from 'react-router'
import { api, call, type Schemas } from '../../api/client'
import { useDeck, useDeckFormats, useGame, useMe } from '../../api/queries'
import { ConditionBadge, FinishBadge, LangFlag } from '../../components/Badges'
import { CardImage } from '../../components/CardImage'
import { ShownName } from '../../components/ShownName'
import { Select } from '../../components/Select'
import { useToast } from '../../components/toast'
import { DeckCount } from './common'
import { useFormatName } from './formats'
import { ImportDialog } from './Import'
import { Validation } from './issues'

type Detail = Schemas['DeckDetailOut']
type Entry = Schemas['DeckEntryOut']
type Section = Schemas['DeckCardIn']['section']

// Card type groups, in the server's order (`api.decks.GROUPS`).
const GROUPS = ['Creature', 'Planeswalker', 'Battle', 'Instant', 'Sorcery', 'Artifact', 'Enchantment', 'Land', 'Other']
const STATUS = {
  missing: { badge: 'badge-error', label: 'Missing' },
  owned: { badge: 'badge-info', label: 'Owned' },
  allocated: { badge: 'badge-success', label: 'Allocated' },
} as const
const LEGAL_BADGE: Record<string, string | null> = { legal: null, unknown: null, banned: 'Banned', not_legal: 'Not legal', restricted: 'Restricted' }

function useDeckMutation<T>(deckId: number, fn: (body: T) => Promise<Detail>) {
  const client = useQueryClient()
  const toast = useToast()
  return useMutation({
    mutationFn: fn,
    onSuccess: (detail) => {
      client.setQueryData(['decks', deckId], detail)
      void client.invalidateQueries({ queryKey: ['decks'], exact: true })
    },
    onError: (e) => toast(e.message, 'error'),
  })
}

/** Search the Magic catalog and add a card to a section (one copy, or one more). */
function AddCard({ deck, entries, onAdd, commander }: { deck: Schemas['DeckOut']; entries: Entry[]; onAdd: (cardId: number, section: Section, quantity: number) => void; commander: string | null }) {
  const { t } = useTranslation()
  const [text, setText] = useState('')
  const [q, setQ] = useState('')
  const [open, setOpen] = useState(false)
  const [section, setSection] = useState<Section>('main')
  const box = useRef<HTMLDivElement>(null)
  const timer = useRef<ReturnType<typeof setTimeout>>(undefined)
  const results = useQuery({
    queryKey: ['card-search', deck.game_id, q],
    enabled: q.trim().length >= 2,
    placeholderData: keepPreviousData,
    queryFn: () => call(api.GET('/api/cards', { params: { query: { q, game: deck.game_id, page_size: 10 } } })),
  })
  const cards = q.trim().length >= 2 ? (results.data?.items ?? []) : []
  useEffect(() => {
    const outside = (e: MouseEvent) => {
      if (!box.current?.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener('mousedown', outside)
    return () => document.removeEventListener('mousedown', outside)
  }, [])
  const add = (card: Schemas['CardSummaryOut']) => {
    const current = entries.find((e) => e.card_id === card.id)?.quantities[section] ?? 0
    onAdd(card.id, section, current + 1)
  }

  return (
    <div className="flex flex-wrap items-center gap-2">
      <div ref={box} className="relative w-full sm:w-96">
        <label className="input w-full">
          <svg viewBox="0 0 24 24" className="h-4 w-4 fill-none stroke-current stroke-2 opacity-60" aria-hidden>
            <circle cx="11" cy="11" r="7" />
            <path d="m20 20-3.5-3.5" />
          </svg>
          <input
            type="text"
            placeholder={t('Search the catalog to add a card')}
            value={text}
            onChange={(e) => {
              setText(e.target.value)
              setOpen(true)
              clearTimeout(timer.current)
              const next = e.target.value
              timer.current = setTimeout(() => setQ(next), 250)
            }}
            onFocus={() => setOpen(true)}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && cards[0]) {
                e.preventDefault()
                add(cards[0])
              } else if (e.key === 'Escape') setOpen(false)
            }}
          />
          {results.isFetching && <span className="loading loading-spinner loading-xs" />}
        </label>
        {open && q.trim().length >= 2 && (
          <ul className="absolute z-30 mt-1 max-h-96 w-full overflow-y-auto rounded-box border border-base-300 bg-base-100 shadow-lg">
            {cards.length === 0 && <li className="px-3 py-3 text-sm text-base-content/60">{results.isFetching ? t('Searching…') : t('No cards found')}</li>}
            {cards.map((card) => {
              const inDeck = entries.find((e) => e.card_id === card.id)
              return (
                <li key={card.id}>
                  <button type="button" className="flex w-full items-center gap-2 px-3 py-1.5 text-left hover:bg-base-200" onClick={() => add(card)}>
                    <span className="block w-8 shrink-0">
                      <CardImage thumb src={card.image} alt="" landscape={card.orientation === 'landscape'} />
                    </span>
                    <span className="min-w-0 flex-1 truncate text-sm">
                      <ShownName name={card.name} translation={card.translation} />
                    </span>
                    {inDeck && <span className="badge badge-sm badge-ghost">× {inDeck.requested}</span>}
                    <span className="badge badge-sm badge-primary">+1</span>
                  </button>
                </li>
              )
            })}
          </ul>
        )}
      </div>
      <Select
        className="w-40"
        value={section}
        onChange={(v) => setSection(v as Section)}
        aria-label={t('Section')}
        options={[
          ...(commander ? [{ value: 'commander', label: commander }] : []),
          { value: 'main', label: t('Main deck') },
          { value: 'sideboard', label: t('Sideboard') },
        ]}
      />
    </div>
  )
}

/** The user's copies of a card (every printing): allocate or release them one by one. */
function CopiesDialog({ deckId, entry, onClose }: { deckId: number; entry: Entry | null; onClose: () => void }) {
  const { t } = useTranslation()
  const { data: detail } = useDeck(deckId)
  const game = useGame(detail?.deck.game_id)
  const client = useQueryClient()
  const items = useQuery({
    queryKey: ['deck-items', deckId, entry?.card_id],
    enabled: !!entry,
    queryFn: () => call(api.GET('/api/decks/{deck_id}/cards/{card_id}/items', { params: { path: { deck_id: deckId, card_id: entry!.card_id } } })),
  })
  const change = useDeckMutation(deckId, ({ path, itemId }: { path: 'allocate' | 'release'; itemId: number }) =>
    call(
      api.POST(path === 'allocate' ? '/api/decks/{deck_id}/allocate' : '/api/decks/{deck_id}/release', {
        params: { path: { deck_id: deckId } },
        body: { card_id: entry!.card_id, quantity: 1, item_id: itemId },
      }),
    ),
  )
  const run = (path: 'allocate' | 'release', itemId: number) =>
    change.mutate({ path, itemId }, { onSettled: () => client.invalidateQueries({ queryKey: ['deck-items', deckId] }) })
  const current = detail?.entries.find((e) => e.card_id === entry?.card_id) ?? entry

  return (
    <dialog className={`modal ${entry ? 'modal-open' : ''}`} onClose={onClose}>
      {entry && current && (
        <div className="modal-box max-w-2xl animate-in fade-in zoom-in-95 duration-200">
          <h3 className="text-lg font-bold">{t('Copies of {{name}}', { name: current.name })}</h3>
          <p className="py-1 text-sm text-base-content/70">
            {t('This deck asks for {{requested}}, {{allocated}} allocated here.', { requested: current.requested, allocated: current.allocated })}{' '}
            {t('Allocating sets a copy aside for this deck: your collection keeps it, other decks no longer see it as available.')}
          </p>
          {items.isPending ? (
            <span className="loading loading-spinner m-auto block" />
          ) : (items.data ?? []).length === 0 ? (
            <p className="py-4 text-center text-sm text-base-content/60">{t('You own no copy of this card.')}</p>
          ) : (
            <ul className="mt-2 flex flex-col gap-2">
              {(items.data ?? []).map((item) => (
                <li key={item.id} className="flex flex-wrap items-center gap-2 rounded-box bg-base-200 px-3 py-2">
                  <span className="font-mono text-xs">
                    {item.set_code} {item.collector_number}
                  </span>
                  <FinishBadge game={game} finish={item.finish} />
                  <ConditionBadge condition={item.condition} />
                  <LangFlag lang={item.language} />
                  <span className="text-xs text-base-content/70">
                    {t('{{owned}} owned · {{here}} here · {{elsewhere}} in other decks · {{free}} free', {
                      owned: item.quantity,
                      here: item.allocated,
                      elsewhere: item.allocated_elsewhere,
                      free: item.free,
                    })}
                  </span>
                  <span className="ml-auto flex gap-1">
                    <button className="btn btn-ghost btn-xs" disabled={item.allocated === 0 || change.isPending} onClick={() => run('release', item.id)}>
                      {t('Release')}
                    </button>
                    <button
                      className="btn btn-primary btn-xs"
                      disabled={item.free === 0 || current.allocated >= current.requested || change.isPending}
                      onClick={() => run('allocate', item.id)}
                    >
                      {t('Allocate')}
                    </button>
                  </span>
                </li>
              ))}
            </ul>
          )}
          <div className="modal-action">
            <button className="btn" onClick={onClose}>
              {t('Close')}
            </button>
          </div>
        </div>
      )}
      <form method="dialog" className="modal-backdrop">
        <button onClick={onClose}>{t('Close')}</button>
      </form>
    </dialog>
  )
}

/** A row's "⋯" menu, opened as a popover anchored to its button: in the top layer, so
 * the scrolling table around it never clips it. */
function RowMenu({ id, actions }: { id: string; actions: { label: string; run: () => void; danger?: boolean }[] }) {
  const { t } = useTranslation()
  const menu = useRef<HTMLUListElement>(null)
  const popover = `deck-menu-${id}`
  const anchor = `--deck-menu-${id}`
  return (
    <>
      <button type="button" className="btn btn-ghost btn-xs" popoverTarget={popover} style={{ anchorName: anchor } as CSSProperties} aria-label={t('More')}>
        ⋯
      </button>
      <ul ref={menu} popover="auto" id={popover} className="dropdown dropdown-end menu w-56 rounded-box bg-base-100 p-2 shadow" style={{ positionAnchor: anchor } as CSSProperties}>
        {actions.map((a) => (
          <li key={a.label}>
            <button
              type="button"
              className={a.danger ? 'text-error' : undefined}
              onClick={() => {
                menu.current?.hidePopover()
                a.run()
              }}
            >
              {a.label}
            </button>
          </li>
        ))}
      </ul>
    </>
  )
}

/** Requested / owned / available / allocated here, and the card's state. */
function Stock({ entry }: { entry: Entry }) {
  const { t } = useTranslation()
  const status = STATUS[entry.status]
  return (
    <div className="flex flex-wrap items-center justify-end gap-1 text-xs">
      <span className={`badge badge-sm ${status.badge}`}>
        {t(status.label)}
        {entry.status === 'missing' && ` ${entry.missing}`}
      </span>
      <span className="tooltip" data-tip={t('Owned in your collection')}>
        <span className="badge badge-sm badge-ghost">
          {t('Owned')} {entry.owned}
        </span>
      </span>
      <span className="tooltip" data-tip={t('Owned copies no deck holds')}>
        <span className="badge badge-sm badge-ghost">
          {t('Available')} {entry.available}
        </span>
      </span>
      <span className="tooltip" data-tip={t('{{n}} allocated to other decks', { n: entry.allocated_elsewhere })}>
        <span className={`badge badge-sm ${entry.allocated >= entry.requested ? 'badge-success' : 'badge-ghost'}`}>
          {t('Here')} {entry.allocated} / {entry.requested}
        </span>
      </span>
    </div>
  )
}

/** One deck: its cards by type with their copies, the format check, editing,
 * text import and copies allocated from the collection. */
export default function DeckDetail() {
  const { t } = useTranslation()
  const { deckId: param } = useParams()
  const deckId = Number(param)
  const { data: me } = useMe()
  const query = useDeck(deckId)
  const { data: gameFormats = [] } = useDeckFormats()
  const formatName = useFormatName()
  const client = useQueryClient()
  const toast = useToast()
  const navigate = useNavigate()
  const [renaming, setRenaming] = useState<string | null>(null)
  const [importing, setImporting] = useState(false)
  const [deleting, setDeleting] = useState(false)
  const [copies, setCopies] = useState<Entry | null>(null)

  const update = useDeckMutation(deckId, (body: Schemas['DeckUpdateIn']) => call(api.PATCH('/api/decks/{deck_id}', { params: { path: { deck_id: deckId } }, body })))
  const setCard = useDeckMutation(deckId, (body: Schemas['DeckCardIn']) => call(api.PUT('/api/decks/{deck_id}/cards', { params: { path: { deck_id: deckId } }, body })))
  const allocate = useDeckMutation(deckId, ({ path, cardId }: { path: 'allocate' | 'release'; cardId: number }) =>
    call(
      api.POST(path === 'allocate' ? '/api/decks/{deck_id}/allocate' : '/api/decks/{deck_id}/release', {
        params: { path: { deck_id: deckId } },
        body: { card_id: cardId, quantity: 1 },
      }),
    ),
  )
  const remove = useMutation({
    mutationFn: () => call(api.DELETE('/api/decks/{deck_id}', { params: { path: { deck_id: deckId } } })),
    onSuccess: async () => {
      await client.invalidateQueries({ queryKey: ['decks'] })
      navigate('/decks')
    },
    onError: (e) => toast(e.message, 'error'),
  })

  if (me && !me.modules?.includes('decks')) return <Navigate to="/settings" replace />
  if (query.isPending) return <span className="loading loading-spinner loading-lg m-auto block" />
  if (!query.data) return null
  const { deck, entries, validation } = query.data
  const format = gameFormats.flatMap((g) => g.formats).find((f) => f.id === deck.format)
  const commanderFormat = !!format?.commander
  const oathbreaker = format?.leader === 'oathbreaker'
  const leaders = oathbreaker ? t('Oathbreaker and signature spell') : t('Commander')
  const put = (cardId: number, section: Section, quantity: number) => setCard.mutate({ card_id: cardId, section, quantity })
  // Copies moved between sections: added first, so the allocated copies stay (lowering
  // the deck's total first would release them).
  const move = async (e: Entry, from: Section, to: Section, count: number) => {
    await setCard.mutateAsync({ card_id: e.card_id, section: to, quantity: (e.quantities[to] ?? 0) + count })
    setCard.mutate({ card_id: e.card_id, section: from, quantity: (e.quantities[from] ?? 0) - count })
  }

  // Rows per section; main deck rows grouped by card type.
  const inSection = (section: Section) => entries.filter((e) => (e.quantities[section] ?? 0) > 0)
  const blocks: { key: string; title: string; section: Section; rows: Entry[] }[] = [
    { key: 'commander', title: leaders, section: 'commander' as Section, rows: inSection('commander') },
    ...GROUPS.map((g) => ({ key: g, title: t(g), section: 'main' as Section, rows: inSection('main').filter((e) => e.group === g) })),
    { key: 'sideboard', title: t('Sideboard'), section: 'sideboard' as Section, rows: inSection('sideboard') },
  ].filter((b) => b.rows.length > 0)
  const totals = { allocated: entries.reduce((n, e) => n + e.allocated, 0), requested: entries.reduce((n, e) => n + e.requested, 0), missing: entries.reduce((n, e) => n + e.missing, 0) }

  return (
    <div className="flex flex-col gap-4">
      <Link to="/decks" className="link-hover w-fit text-sm text-base-content/70">
        ← {t('Decks')}
      </Link>
      <div className="card bg-base-200">
        <div className="card-body gap-3 lg:flex-row lg:items-center">
          <div className="min-w-0 flex-1">
            {renaming === null ? (
              <h1 className="text-2xl font-bold leading-tight">
                {deck.name}{' '}
                <button className="btn btn-ghost btn-xs align-middle" onClick={() => setRenaming(deck.name)}>
                  {t('Rename')}
                </button>
              </h1>
            ) : (
              <form
                className="join"
                onSubmit={(e) => {
                  e.preventDefault()
                  if (renaming.trim()) update.mutate({ name: renaming.trim() }, { onSuccess: () => setRenaming(null) })
                }}
              >
                <input className="input join-item" value={renaming} maxLength={100} autoFocus onChange={(e) => setRenaming(e.target.value)} aria-label={t('Name')} />
                <button type="submit" className="btn btn-primary join-item" disabled={!renaming.trim()}>
                  {t('Save')}
                </button>
                <button type="button" className="btn join-item" onClick={() => setRenaming(null)}>
                  {t('Cancel')}
                </button>
              </form>
            )}
            <div className="mt-1 flex flex-wrap items-center gap-2 text-sm text-base-content/60">
              <span>Magic: The Gathering · {formatName(deck.format)}</span>
              <DeckCount deck={deck} />
            </div>
            <div className="mt-1 text-xs text-base-content/60">
              {t('{{allocated}} of {{requested}} copies allocated, {{missing}} missing from your collection', totals)}
            </div>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <Select
              className="w-36"
              value={deck.format}
              disabled={update.isPending}
              onChange={(v) => update.mutate({ format: v as 'standard' })}
              aria-label={t('Format')}
              options={(gameFormats.find((g) => g.game_id === deck.game_id)?.formats ?? []).map((f) => ({ value: f.id, label: f.name }))}
            />
            <button className="btn btn-sm" onClick={() => setImporting(true)}>
              {t('Import a decklist')}
            </button>
            <button className="btn btn-ghost btn-sm text-error" onClick={() => setDeleting(true)}>
              {t('Delete')}
            </button>
          </div>
        </div>
      </div>

      <AddCard deck={deck} entries={entries} onAdd={put} commander={commanderFormat ? leaders : null} />

      <div className="grid gap-4 xl:grid-cols-[1fr_22rem]">
        <div className="flex flex-col gap-4">
          {blocks.length === 0 && (
            <div className="card bg-base-200">
              <div className="card-body items-center text-center text-sm text-base-content/70">{t('No card yet: search the catalog above or import a decklist.')}</div>
            </div>
          )}
          {blocks.map((block) => (
            <div key={block.key} className="overflow-x-auto rounded-box border border-base-300">
              <table className="table table-sm">
                <thead>
                  <tr>
                    <th colSpan={4}>
                      {block.title} ({block.rows.reduce((n, e) => n + (e.quantities[block.section] ?? 0), 0)})
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {block.rows.map((e) => {
                    const quantity = e.quantities[block.section] ?? 0
                    const legal = LEGAL_BADGE[e.legal]
                    const busy = setCard.isPending || allocate.isPending
                    return (
                      <tr key={`${block.key}-${e.card_id}`} className="hover:bg-base-200">
                        <td className="w-28">
                          <div className="join">
                            <button className="btn btn-xs join-item" disabled={busy} onClick={() => put(e.card_id, block.section, quantity - 1)} aria-label={t('One less')}>
                              −
                            </button>
                            <input
                              key={quantity}
                              className="input input-xs join-item w-10 text-center"
                              defaultValue={quantity}
                              inputMode="numeric"
                              aria-label={t('Quantity')}
                              onBlur={(ev) => {
                                const next = Number(ev.target.value)
                                if (Number.isInteger(next) && next >= 0 && next !== quantity) put(e.card_id, block.section, next)
                              }}
                              onKeyDown={(ev) => ev.key === 'Enter' && (ev.target as HTMLInputElement).blur()}
                            />
                            <button className="btn btn-xs join-item" disabled={busy} onClick={() => put(e.card_id, block.section, quantity + 1)} aria-label={t('One more')}>
                              +
                            </button>
                          </div>
                        </td>
                        <td>
                          <div className="flex items-center gap-2">
                            <Link to={`/cards/${e.card_id}`} className="block w-8 shrink-0" tabIndex={-1} aria-hidden>
                              <CardImage thumb src={e.image} alt={e.name} />
                            </Link>
                            <div className="min-w-0">
                              <Link to={`/cards/${e.card_id}`} className="link-hover font-medium">
                                <ShownName name={e.name} translation={e.translation} />
                              </Link>
                              <div className="flex flex-wrap items-center gap-1 text-xs text-base-content/60">
                                {e.mana_cost && <span className="font-mono">{e.mana_cost}</span>}
                                {legal && <span className="badge badge-xs badge-error">{t(legal)}</span>}
                                {e.legal === 'unknown' && (
                                  <span className="badge badge-xs badge-ghost" title={t('Legality not known yet')}>
                                    ?
                                  </span>
                                )}
                              </div>
                            </div>
                          </div>
                        </td>
                        <td>
                          <Stock entry={e} />
                        </td>
                        <td className="w-1 whitespace-nowrap text-right">
                          <div className="flex justify-end gap-1">
                            <button
                              className="btn btn-primary btn-xs"
                              disabled={busy || e.available === 0 || e.allocated >= e.requested}
                              // Several printings / finishes / conditions / languages free: the user picks one.
                              onClick={() => (e.free_items > 1 ? setCopies(e) : allocate.mutate({ path: 'allocate', cardId: e.card_id }))}
                              title={e.free_items > 1 ? t('Choose which owned copy to set aside for this deck') : t('Set one owned copy aside for this deck')}
                            >
                              {t('Allocate')}
                              {e.free_items > 1 && '…'}
                            </button>
                            <button
                              className="btn btn-ghost btn-xs"
                              disabled={busy || e.allocated === 0}
                              onClick={() => allocate.mutate({ path: 'release', cardId: e.card_id })}
                              title={t('Give one allocated copy back')}
                            >
                              {t('Release')}
                            </button>
                            <RowMenu
                              id={`${block.key}-${e.card_id}`}
                              actions={[
                                { label: t('Choose copies…'), run: () => setCopies(e) },
                                ...(commanderFormat && block.section !== 'commander'
                                  ? [{ label: oathbreaker ? t('Move to oathbreaker / signature spell') : t('Make commander'), run: () => move(e, block.section, 'commander', 1) }]
                                  : []),
                                ...(block.section !== 'sideboard' ? [{ label: t('Move to sideboard'), run: () => move(e, block.section, 'sideboard', quantity) }] : []),
                                ...(block.section !== 'main' ? [{ label: t('Move to main deck'), run: () => move(e, block.section, 'main', quantity) }] : []),
                                { label: t('Remove'), run: () => put(e.card_id, block.section, 0), danger: true },
                              ]}
                            />
                          </div>
                        </td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>
          ))}
        </div>
        <div>
          <Validation validation={validation} />
        </div>
      </div>

      <ImportDialog deckId={deckId} open={importing} onClose={() => setImporting(false)} />
      <CopiesDialog deckId={deckId} entry={copies} onClose={() => setCopies(null)} />

      <dialog className={`modal ${deleting ? 'modal-open' : ''}`} onClose={() => setDeleting(false)}>
        {deleting && (
          <div className="modal-box">
            <h3 className="text-lg font-bold">{t('Delete {{name}}?', { name: deck.name })}</h3>
            <p className="py-2 text-sm">{t('Its allocated copies become available again; your collection is not changed.')}</p>
            <div className="modal-action">
              <button className="btn btn-ghost" onClick={() => setDeleting(false)}>
                {t('Cancel')}
              </button>
              <button className="btn btn-error" disabled={remove.isPending} onClick={() => remove.mutate()}>
                {t('Delete')}
              </button>
            </div>
          </div>
        )}
        <form method="dialog" className="modal-backdrop">
          <button onClick={() => setDeleting(false)}>{t('Close')}</button>
        </form>
      </dialog>
    </div>
  )
}
