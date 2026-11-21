import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { type CSSProperties, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link, Navigate, useNavigate, useParams } from 'react-router'
import { api, call, type Schemas } from '../../api/client'
import { useDeck, useDeckFormats, useGame, useMe } from '../../api/queries'
import { ViewToggle } from '../../components/ViewToggle'
import { gridIcon, listIcon, useView, type ViewChoice } from '../../lib/views'
import { ConditionBadge, FinishBadge, LangFlag } from '../../components/Badges'
import { CardImage } from '../../components/CardImage'
import { ShownName } from '../../components/ShownName'
import { SymbolText } from '../../components/SymbolText'
import { Select } from '../../components/Select'
import { useToast } from '../../components/toast'
import { AddCards } from './AddCards'
import { DeckCount } from './common'
import { ExportDialog } from './Export'
import { useFormatName } from './formats'
import { ImportDialog } from './Import'
import { FormatCheck } from './issues'

type Detail = Schemas['DeckDetailOut']
type Entry = Schemas['DeckEntryOut']
type Line = Schemas['DeckLineOut']
type Section = Schemas['DeckSectionOut']['id']
// One line of a card in a section: a printing asked for, or any.
type Row = { entry: Entry; line: Line }

// Cards as rows with their copies, or as pictures (like the collection).
const DECK_VIEWS: ViewChoice[] = [
  { id: 'list', label: 'List', icon: listIcon },
  { id: 'images', label: 'Images', icon: gridIcon },
]
const STATUS = {
  missing: { badge: 'badge-error', label: 'Missing' },
  owned: { badge: 'badge-info', label: 'Owned' },
  allocated: { badge: 'badge-success', label: 'Allocated' },
} as const
// Sections of one card: moving a line there moves one copy.
const SINGLE = new Set<Section>(['commander', 'companion', 'legend', 'champion', 'avatar'])
const LEGAL_BADGE: Record<string, string | null> = { legal: null, unknown: null, banned: 'Banned', not_legal: 'Not legal', restricted: 'Restricted' }

/** "Banned" / "Not legal" badge, "?" when legality is not known. */
function Legality({ entry }: { entry: Entry }) {
  const { t } = useTranslation()
  const legal = LEGAL_BADGE[entry.legal]
  if (legal) return <span className="badge badge-xs badge-error">{t(legal)}</span>
  if (entry.legal !== 'unknown') return null
  return (
    <span className="badge badge-xs badge-ghost" title={t('Legality not known yet')}>
      ?
    </span>
  )
}

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

/** The card's page, on the line's printing when it asks for one. */
const cardPage = ({ entry, line }: Row) => `/cards/${entry.card_id}${line.printing_id ? `/${line.printing_id}` : ''}`

/** "M10 146", or "Any printing": opens the printing chooser. */
function PrintingBadge({ line, onClick }: { line: Line; onClick: () => void }) {
  const { t } = useTranslation()
  return (
    <button
      type="button"
      className={`badge badge-sm cursor-pointer font-mono ${line.printing_id ? 'badge-outline' : 'badge-ghost'}`}
      onClick={onClick}
      title={line.set_name ? `${line.set_name} · ${t('Choose the printing')}` : t('Choose the printing')}
    >
      {line.printing_id ? `${line.set_code} ${line.collector_number ?? ''}`.trim() : t('Any printing')}
    </button>
  )
}

/** The card's printings, to ask for one in a deck line (all its copies, or one copy split
 * off into its own line), or any printing. */
function PrintingDialog({ deckId, gameId, row, split, onClose }: { deckId: number; gameId: string; row: Row | null; split: boolean; onClose: () => void }) {
  const { t } = useTranslation()
  const printings = useQuery({
    queryKey: ['deck-printings', deckId, row?.entry.card_id],
    enabled: !!row,
    queryFn: () => call(api.GET('/api/decks/{deck_id}/cards/{card_id}/printings', { params: { path: { deck_id: deckId, card_id: row!.entry.card_id } } })),
  })
  const move = useDeckMutation(deckId, (to: number | null) =>
    call(
      api.POST('/api/decks/{deck_id}/cards/move', {
        params: { path: { deck_id: deckId } },
        body: { card_id: row!.entry.card_id, section: row!.line.section, printing_id: row!.line.printing_id, to_printing_id: to, quantity: split ? 1 : null },
      }),
    ),
  )
  const choose = (to: number | null) => move.mutate(to, { onSuccess: onClose })
  const current = row?.line.printing_id ?? null

  return (
    <dialog className={`modal ${row ? 'modal-open' : ''}`} onClose={onClose}>
      {row && (
        <div className="modal-box max-w-3xl animate-in fade-in zoom-in-95 duration-200">
          <h3 className="text-lg font-bold">{split ? t('Split off one copy of {{name}}', { name: row.entry.name }) : t('Printing of {{name}}', { name: row.entry.name })}</h3>
          <p className="py-1 text-sm text-base-content/70">
            {split
              ? t('One copy gets its own line, asking for the printing chosen.')
              : t('The {{n}} copies of this line ask for the printing chosen; format rules count every printing of the card together.', { n: row.line.quantity })}
          </p>
          <button type="button" className={`btn btn-sm mt-2 ${current === null && !split ? 'btn-primary' : 'btn-ghost'}`} disabled={move.isPending || (current === null && !split)} onClick={() => choose(null)}>
            {t('Any printing')}
          </button>
          {printings.isPending ? (
            <span className="loading loading-spinner m-auto block" />
          ) : (
            <div className="mt-3 grid max-h-[60vh] grid-cols-3 gap-3 overflow-y-auto sm:grid-cols-4 md:grid-cols-5">
              {(printings.data ?? []).map((p) => (
                <button
                  key={p.id}
                  type="button"
                  className={`flex flex-col gap-1 rounded-box p-1 text-left transition hover:bg-base-200 ${p.id === current ? 'ring-2 ring-primary' : ''}`}
                  disabled={move.isPending || (p.id === current && !split)}
                  onClick={() => choose(p.id)}
                >
                  <CardImage thumb src={p.image} alt="" game={gameId} />
                  <span className="font-mono text-xs">
                    {p.set_code} {p.collector_number}
                  </span>
                  <span className="truncate text-xs text-base-content/70" title={p.set_name}>
                    {p.set_name}
                  </span>
                  {p.owned > 0 && <span className="badge badge-xs badge-info badge-soft">{t('Owned {{n}} · free {{free}}', { n: p.owned, free: p.available })}</span>}
                </button>
              ))}
            </div>
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
  // Printings the deck's lines ask for.
  const asked = new Set((current?.lines ?? []).map((l) => l.printing_id).filter((p) => p !== null))

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
                  <span className="block w-8 shrink-0">
                    <CardImage thumb src={item.image} alt="" game={detail?.deck.game_id} />
                  </span>
                  <span className="font-mono text-xs">
                    {item.set_code} {item.collector_number}
                  </span>
                  {asked.has(item.printing_id) && <span className="badge badge-xs badge-primary badge-soft">{t('Asked for')}</span>}
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
  const [printing, setPrinting] = useState<{ row: Row; split: boolean } | null>(null)
  const [exporting, setExporting] = useState(false)
  const [view, chooseView] = useView(DECK_VIEWS, 'tcg.deckView')
  const game = useGame(query.data?.deck.game_id)

  const update = useDeckMutation(deckId, (body: Schemas['DeckUpdateIn']) => call(api.PATCH('/api/decks/{deck_id}', { params: { path: { deck_id: deckId } }, body })))
  const setCard = useDeckMutation(deckId, (body: Omit<Schemas['DeckCardIn'], 'add'> & { add?: boolean }) =>
    call(api.PUT('/api/decks/{deck_id}/cards', { params: { path: { deck_id: deckId } }, body: { add: false, ...body } })),
  )
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
  const { deck, groups, entries, validation } = query.data
  const format = gameFormats.flatMap((g) => g.formats).find((f) => f.id === deck.format)
  const commanderFormat = !!format?.commander
  const oathbreaker = format?.leader === 'oathbreaker'
  const leaders = oathbreaker ? t('Oathbreaker and signature spell') : t('Commander')
  // The format's sections (Magic: commander only in commander formats), names translated.
  const sections = (format?.sections ?? [{ id: 'main' as Section, name: 'Main deck' }])
    .filter((s) => s.id !== 'commander' || commanderFormat)
    .map((s) => ({ id: s.id, name: s.id === 'commander' ? leaders : t(s.name) }))
  const sectionName = (id: Section) => sections.find((s) => s.id === id)?.name ?? id
  const put = (cardId: number, section: Section, printingId: number | null, quantity: number) =>
    setCard.mutate({ card_id: cardId, section, printing_id: printingId, quantity })
  // One more copy from the search, on the line of that printing (or any) in the section.
  // To the main deck: the server puts runes, sites, Extra Deck monsters... in theirs.
  const add = (cardId: number, section: Section, printingId: number | null) =>
    setCard.mutate({ card_id: cardId, section: section === 'main' ? null : section, printing_id: printingId, quantity: 1, add: true })
  // Copies of a line moved to another section (same printing): added first, so the
  // allocated copies stay (lowering the deck's total first would release them).
  const move = async ({ entry, line }: Row, to: Section, count: number) => {
    const target = entry.lines.find((l) => l.section === to && l.printing_id === line.printing_id)
    await setCard.mutateAsync({ card_id: entry.card_id, section: to, printing_id: line.printing_id, quantity: (target?.quantity ?? 0) + count })
    setCard.mutate({ card_id: entry.card_id, section: line.section, printing_id: line.printing_id, quantity: line.quantity - count })
  }

  // Rows (card lines) per section in the format's order; main deck rows grouped by card
  // type. Cards of a section the format lacks (format changed) are shown last.
  const inSection = (section: Section, group?: string) =>
    entries.filter((e) => group === undefined || e.group === group).flatMap((entry) => entry.lines.filter((l) => l.section === section).map((line) => ({ entry, line })))
  const used = [...new Set(entries.flatMap((e) => e.lines.map((l) => l.section)))]
  const shown = [...sections.map((s) => s.id), ...used.filter((id) => !sections.some((s) => s.id === id))]
  type Block = { key: string; title: string; section: Section; rows: Row[] }
  const blocks = shown
    .flatMap((section): Block[] =>
      section === 'main'
        ? groups.map((g) => ({ key: g, title: t(g), section, rows: inSection('main', g) }))
        : [{ key: section, title: sectionName(section), section, rows: inSection(section) }],
    )
    .filter((b) => b.rows.length > 0)
  const rowKey = (block: { key: string }, { entry, line }: Row) => `${block.key}-${entry.card_id}-${line.printing_id ?? 'any'}`
  // The card's first line in a block shows its copies; its other lines only theirs.
  const firstLine = (rows: Row[], row: Row) => rows.find((r) => r.entry.card_id === row.entry.card_id) === row
  const busy = setCard.isPending || allocate.isPending
  const stepper = ({ entry, line }: Row) => {
    const quantity = line.quantity
    const set = (next: number) => put(entry.card_id, line.section, line.printing_id, next)
    return (
      <div className="join">
        <button className="btn btn-xs join-item" disabled={busy} onClick={() => set(quantity - 1)} aria-label={t('One less')}>
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
            if (Number.isInteger(next) && next >= 0 && next !== quantity) set(next)
          }}
          onKeyDown={(ev) => ev.key === 'Enter' && (ev.target as HTMLInputElement).blur()}
        />
        <button className="btn btn-xs join-item" disabled={busy} onClick={() => set(quantity + 1)} aria-label={t('One more')}>
          +
        </button>
      </div>
    )
  }
  // Copies allocated to a line of a card split by printing ("2 / 3").
  const lineAllocated = ({ entry, line }: Row) =>
    entry.lines.length > 1 && (
      <span className={`badge badge-xs ${line.allocated >= line.quantity ? 'badge-success' : 'badge-ghost'}`} title={t('Copies allocated to this line')}>
        {line.allocated} / {line.quantity}
      </span>
    )
  const actions = (row: Row, block: { key: string; section: Section }) => {
    const { entry: e, line } = row
    return (
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
        <button className="btn btn-ghost btn-xs" disabled={busy || e.allocated === 0} onClick={() => allocate.mutate({ path: 'release', cardId: e.card_id })} title={t('Give one allocated copy back')}>
          {t('Release')}
        </button>
        <RowMenu
          id={rowKey(block, row)}
          actions={[
            { label: t('Choose copies…'), run: () => setCopies(e) },
            { label: t('Choose the printing…'), run: () => setPrinting({ row, split: false }) },
            ...(line.quantity > 1 ? [{ label: t('Split off one copy…'), run: () => setPrinting({ row, split: true }) }] : []),
            ...(commanderFormat && block.section !== 'commander'
              ? [{ label: oathbreaker ? t('Move to oathbreaker / signature spell') : t('Make commander'), run: () => move(row, 'commander', 1) }]
              : []),
            // Other sections: every copy moves, one for single-card sections (legend, champion, avatar).
            ...sections
              .filter((s) => s.id !== block.section && s.id !== 'commander')
              .map((s) => ({
                label: t('Move to {{section}}', { section: s.name }),
                run: () => move(row, s.id, SINGLE.has(s.id) ? 1 : line.quantity),
              })),
            { label: t('Remove'), run: () => put(e.card_id, block.section, line.printing_id, 0), danger: true },
          ]}
        />
      </div>
    )
  }
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
              <span>
                {game?.name ?? deck.game_id} · {formatName(deck.format)}
              </span>
              <DeckCount deck={deck} />
            </div>
            <div className="mt-1 text-xs text-base-content/60">
              {t('{{allocated}} of {{requested}} copies allocated, {{missing}} missing from your collection', totals)}
            </div>
            <FormatCheck validation={validation} />
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <Select
              className="w-52"
              value={deck.format}
              disabled={update.isPending}
              onChange={(v) => update.mutate({ format: v as Schemas['DeckUpdateIn']['format'] })}
              aria-label={t('Format')}
              options={(gameFormats.find((g) => g.game_id === deck.game_id)?.formats ?? []).map((f) => ({ value: f.id, label: f.name }))}
            />
            <button className="btn btn-sm" onClick={() => setImporting(true)}>
              {t('Import a decklist')}
            </button>
            <button className="btn btn-sm" onClick={() => setExporting(true)} disabled={entries.length === 0}>
              {t('Export')}
            </button>
            <button className="btn btn-ghost btn-sm text-error" onClick={() => setDeleting(true)}>
              {t('Delete')}
            </button>
          </div>
        </div>
      </div>

      <AddCards deck={deck} entries={entries} onAdd={add} sections={sections} busy={busy} view={view.id} />
      <div className="flex justify-end">
        <ViewToggle views={DECK_VIEWS} value={view.id} onChange={chooseView} />
      </div>

      <div className="flex flex-col gap-4">
        {blocks.length === 0 && (
          <div className="card bg-base-200">
            <div className="card-body items-center text-center text-sm text-base-content/70">{t('No card yet: search the catalog above or import a decklist.')}</div>
          </div>
        )}
        {blocks.map((block) => {
          const count = block.rows.reduce((n, r) => n + r.line.quantity, 0)
          if (view.id === 'images')
            return (
              <section key={block.key} className="flex flex-col gap-2">
                <h2 className="font-semibold">
                  {block.title} ({count})
                </h2>
                <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 md:grid-cols-4 2xl:grid-cols-5">
                  {block.rows.map((row) => {
                    const { entry: e, line } = row
                    const status = STATUS[e.status]
                    const link = cardPage(row)
                    return (
                      <div key={rowKey(block, row)} className="flex flex-col gap-1">
                        <Link to={link} className="group relative">
                          <CardImage thumb src={line.image ?? e.image} alt={e.name} game={deck.game_id} landscape={e.orientation === 'landscape'} faceClassName="transition-transform group-hover:-translate-y-1 group-hover:scale-[1.02]" />
                          <span className="badge badge-neutral absolute bottom-[3%] left-[3%] font-semibold shadow">×{line.quantity}</span>
                          <span className={`badge badge-sm absolute right-[3%] top-[3%] shadow ${status.badge}`}>
                            {t(status.label)}
                            {e.status === 'missing' && ` ${e.missing}`}
                          </span>
                        </Link>
                        <Link to={link} className="link-hover break-words text-sm font-medium">
                          <ShownName name={e.name} translation={e.translation} />
                        </Link>
                        <div className="flex flex-wrap items-center gap-1 text-xs text-base-content/60">
                          <PrintingBadge line={line} onClick={() => setPrinting({ row, split: false })} />
                          <span className="tooltip" data-tip={t('{{n}} allocated to other decks', { n: e.allocated_elsewhere })}>
                            <span className={`badge badge-sm ${e.allocated >= e.requested ? 'badge-success' : 'badge-ghost'}`}>
                              {t('Here')} {e.allocated} / {e.requested}
                            </span>
                          </span>
                          {lineAllocated(row)}
                          <Legality entry={e} />
                        </div>
                        <div className="flex flex-wrap items-center justify-between gap-1">
                          {stepper(row)}
                          {actions(row, block)}
                        </div>
                      </div>
                    )
                  })}
                </div>
              </section>
            )
          return (
            <div key={block.key} className="overflow-x-auto rounded-box border border-base-300">
              <table className="table table-sm">
                <thead>
                  <tr>
                    <th colSpan={4}>
                      {block.title} ({count})
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {block.rows.map((row) => {
                    const { entry: e, line } = row
                    const link = cardPage(row)
                    const first = firstLine(block.rows, row)
                    return (
                      <tr key={rowKey(block, row)} className={`hover:bg-base-200 ${first ? '' : 'border-t-0'}`}>
                        <td className="w-28">{stepper(row)}</td>
                        <td>
                          <div className="flex items-center gap-2">
                            <Link to={link} className="block w-8 shrink-0" tabIndex={-1} aria-hidden>
                              <CardImage thumb src={line.image ?? e.image} alt={e.name} game={deck.game_id} landscape={e.orientation === 'landscape'} />
                            </Link>
                            <div className="min-w-0">
                              <Link to={link} className={`link-hover font-medium ${first ? '' : 'text-base-content/60'}`}>
                                <ShownName name={e.name} translation={e.translation} />
                              </Link>
                              <div className="flex flex-wrap items-center gap-1 text-xs text-base-content/60">
                                <PrintingBadge line={line} onClick={() => setPrinting({ row, split: false })} />
                                {lineAllocated(row)}
                                {first && e.mana_cost && (
                                  <span className="whitespace-nowrap">
                                    <SymbolText game={game} text={e.mana_cost} />
                                  </span>
                                )}
                                {first && !e.mana_cost && e.type_line && deck.game_id !== 'mtg' && <span>{e.type_line}</span>}
                                {first && <Legality entry={e} />}
                              </div>
                            </div>
                          </div>
                        </td>
                        <td>{first && <Stock entry={e} />}</td>
                        <td className="w-1 whitespace-nowrap text-right">{actions(row, block)}</td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>
          )
        })}
      </div>

      <ImportDialog deckId={deckId} gameId={deck.game_id} sections={sections} open={importing} onClose={() => setImporting(false)} />
      <CopiesDialog deckId={deckId} entry={copies} onClose={() => setCopies(null)} />
      <PrintingDialog deckId={deckId} gameId={deck.game_id} row={printing?.row ?? null} split={printing?.split ?? false} onClose={() => setPrinting(null)} />
      <ExportDialog deck={deck} open={exporting} onClose={() => setExporting(false)} />

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
