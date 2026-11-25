import { useMutation } from '@tanstack/react-query'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link, useNavigate } from 'react-router'
import { api, call } from '../api/client'
import { useShownGames } from '../api/queries'
import { useShoppingCache, useShoppingLists, type ShoppingList } from '../api/shopping'
import { Icon } from '../components/Icon'
import { EmptyState, PageHeader } from '../components/Page'
import { Select } from '../components/Select'
import { useToast } from '../components/toast'
import { formatDate } from '../lib/format'

/** Where a list comes from: a deck, a followed set, or the user's own list. */
export function SourceBadge({ list }: { list: ShoppingList }) {
  const { t } = useTranslation()
  if (list.source === 'deck') return <span className="badge badge-sm badge-primary badge-soft">{t('Deck')}</span>
  if (list.source === 'binder') return <span className="badge badge-sm badge-info badge-soft">{t('Followed set')}</span>
  return <span className="badge badge-sm badge-ghost">{t('Own list')}</span>
}

/** New standalone list: a name and its game (empty until cards are added). */
function CreateDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  const { t } = useTranslation()
  const toast = useToast()
  const navigate = useNavigate()
  const cache = useShoppingCache()
  const { shown: games } = useShownGames()
  const [name, setName] = useState('')
  const [chosenGame, setGame] = useState<string | null>(null)
  const gameId = chosenGame ?? (games.find((g) => g.id === 'mtg') ?? games[0])?.id ?? ''
  const create = useMutation({
    mutationFn: () => call(api.POST('/api/shopping-lists', { body: { name: name.trim(), game_id: gameId } })),
    onSuccess: async (detail) => {
      await cache(detail)
      onClose()
      setName('')
      navigate(`/shopping/${detail.id}`)
    },
    onError: (e) => toast(e.message, 'error'),
  })
  return (
    <dialog className={`modal ${open ? 'modal-open' : ''}`} onClose={onClose}>
      {open && (
        <form
          className="modal-box rounded-[20px] animate-in fade-in zoom-in-95 duration-200"
          onSubmit={(e) => {
            e.preventDefault()
            if (name.trim() && gameId) create.mutate()
          }}
        >
          <h3 className="text-2xl">{t('New shopping list')}</h3>
          <div className="mt-4 grid gap-3 sm:grid-cols-2">
            <label className="fieldset py-0">
              <span className="fieldset-legend">{t('Name')}</span>
              <input className="input w-full" value={name} maxLength={100} autoFocus onChange={(e) => setName(e.target.value)} />
            </label>
            <label className="fieldset py-0">
              <span className="fieldset-legend">{t('Game')}</span>
              <Select className="w-full" value={gameId} onChange={setGame} aria-label={t('Game')} options={games.map((g) => ({ value: g.id, label: g.name }))} />
            </label>
          </div>
          <div className="modal-action">
            <button type="button" className="btn btn-ghost" onClick={onClose}>
              {t('Cancel')}
            </button>
            <button type="submit" className="btn btn-primary" disabled={!name.trim() || !gameId || create.isPending}>
              {create.isPending && <span className="loading loading-spinner loading-sm" />}
              {t('Create')}
            </button>
          </div>
        </form>
      )}
      <form method="dialog" className="modal-backdrop">
        <button onClick={onClose}>{t('Close')}</button>
      </form>
    </dialog>
  )
}

/** Every shopping list of the user: their own lists, and those of decks and followed
 * sets. Ticked in the Android app too. */
export default function ShoppingPage() {
  const { t } = useTranslation()
  const lists = useShoppingLists()
  const { games } = useShownGames()
  const [creating, setCreating] = useState(false)
  const all = lists.data ?? []
  const gameName = (id: string) => games.find((g) => g.id === id)?.name ?? id
  const newButton = (
    <button className="btn btn-primary min-h-11 gap-2" onClick={() => setCreating(true)}>
      <Icon name="plus" />
      {t('New list')}
    </button>
  )
  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        eyebrow={t('Your collection')}
        title={t('Shopping list')}
        subtitle={t('Cards to buy: your own lists, and those made from a deck or a followed set. Tick copies here or in the Android app.')}
        action={all.length > 0 && newButton}
      />
      {lists.isPending ? (
        <span className="loading loading-spinner loading-lg m-auto block" />
      ) : lists.isError ? (
        <div className="alert alert-error">{lists.error.message}</div>
      ) : all.length === 0 ? (
        <EmptyState title={t('No shopping list yet.')} actions={newButton}>
          {t('Create a list and add cards from the catalog, or use Create list on a deck or a followed set.')}
        </EmptyState>
      ) : (
        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
          {all.map((l) => (
            <Link key={l.id} to={`/shopping/${l.id}`} className="card rounded-2xl border border-base-300 bg-base-100 transition-colors hover:border-base-content/40">
              <div className="card-body gap-2">
                <div className="flex items-start justify-between gap-2">
                  <h2 className="text-lg leading-tight">{l.name}</h2>
                  <SourceBadge list={l} />
                </div>
                <div className="text-xs text-base-content/70">
                  {gameName(l.game_id)} · {t('Changed {{date}}', { date: formatDate(l.updated_at) })}
                </div>
                <progress className="progress progress-primary w-full" value={l.bought} max={Math.max(l.copies, 1)} aria-label={t('Bought')} />
                <div className="text-sm">{t('{{bought}} of {{copies}} copies bought', { bought: l.bought, copies: l.copies })}</div>
              </div>
            </Link>
          ))}
        </div>
      )}
      <CreateDialog open={creating} onClose={() => setCreating(false)} />
    </div>
  )
}
