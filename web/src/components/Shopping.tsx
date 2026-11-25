import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useNavigate } from 'react-router'
import { api, call } from '../api/client'
import { useShoppingCache, useShoppingLists, type ShoppingSync } from '../api/shopping'
import { Icon } from './Icon'
import { Select } from './Select'
import { useToast } from './toast'

/** Create list / Update list of a deck or a followed set: the list is made from what the
 * source misses (and opened), rebuilt with the ticks kept, or deleted once nothing is
 * missing. `listId`: the source's list, null when it has none. */
export function SourceListButton({
  source,
  sourceId,
  listId,
  className = '',
  onDeleted,
}: {
  source: 'deck' | 'binder'
  sourceId: number
  listId: number | null | undefined
  className?: string
  // The list was deleted (nothing missing any more): the list page leaves it.
  onDeleted?: () => void
}) {
  const { t } = useTranslation()
  const toast = useToast()
  const navigate = useNavigate()
  const client = useQueryClient()
  const cache = useShoppingCache()
  const sync = useMutation({
    mutationFn: (): Promise<ShoppingSync> =>
      source === 'deck'
        ? call(api.POST('/api/decks/{deck_id}/shopping-list', { params: { path: { deck_id: sourceId } } }))
        : call(api.POST('/api/binder/{binder_id}/shopping-list', { params: { path: { binder_id: sourceId } } })),
    onSuccess: async (result) => {
      if (result.status === 'deleted') onDeleted?.()
      await cache(result.list ?? null, result.status === 'deleted' && listId ? listId : undefined)
      await client.invalidateQueries({ queryKey: [source === 'deck' ? 'decks' : 'binder', sourceId] })
      if (result.status === 'nothing') toast(t('Nothing to buy'), 'info')
      else if (result.status === 'deleted') toast(t('Nothing left to buy: the shopping list was removed.'), 'success')
      else if (result.status === 'updated') toast(t('Shopping list updated.'), 'success')
      if (result.status === 'created' && result.list) navigate(`/shopping/${result.list.id}`)
    },
    onError: (error) => toast(error.message, 'error'),
  })
  return (
    <button
      className={`btn gap-2 ${className}`}
      disabled={sync.isPending}
      onClick={() => sync.mutate()}
      title={listId ? t('Rebuild the shopping list from what is still missing') : t('Make a shopping list of the missing cards')}
    >
      {sync.isPending ? <span className="loading loading-spinner loading-sm" /> : <Icon name={listId ? 'sync' : 'list'} />}
      {listId ? t('Update list') : t('Create list')}
    </button>
  )
}

/** Editions accepted for a shopping item: any, or one or several printings of the card. */
export function EditionPicker({
  cardId,
  value,
  onChange,
  disabled,
}: {
  cardId: number
  value: number[]
  onChange: (printingIds: number[]) => void
  disabled?: boolean
}) {
  const { t } = useTranslation()
  const card = useQuery({
    queryKey: ['card', cardId],
    queryFn: () => call(api.GET('/api/cards/{card_id}', { params: { path: { card_id: cardId } } })),
  })
  const printings = card.data?.printings ?? []
  if (card.isPending) return <span className="loading loading-dots loading-sm" />
  const toggle = (id: number) => onChange(value.includes(id) ? value.filter((x) => x !== id) : [...value, id])
  return (
    <fieldset className="flex flex-col gap-1" disabled={disabled}>
      <label className="flex items-center gap-2 text-sm">
        <input type="checkbox" className="checkbox checkbox-sm" checked={value.length === 0} onChange={() => onChange([])} />
        {t('Any edition')}
      </label>
      <div className="flex max-h-48 flex-col gap-1 overflow-y-auto">
        {printings.map((p) => (
          <label key={p.id} className="flex items-center gap-2 text-sm">
            <input type="checkbox" className="checkbox checkbox-sm" checked={value.includes(p.id)} onChange={() => toggle(p.id)} />
            <span className="font-mono text-xs">
              {p.set.code.toUpperCase()} {p.collector_number}
            </span>
            <span className="truncate text-base-content/70">{p.set.name}</span>
          </label>
        ))}
      </div>
      {value.length > 1 && <p className="text-xs text-base-content/70">{t('Copies may come from any of the chosen editions, in any mix.')}</p>}
    </fieldset>
  )
}

/** Card page: add copies of the card to one of the user's lists of its game, or to a
 * new list. The printing shown is the edition chosen first. */
export function AddToShoppingList({
  open,
  onClose,
  cardId,
  gameId,
  printingId,
}: {
  open: boolean
  onClose: () => void
  cardId: number
  gameId: string
  printingId: number | null
}) {
  const { t } = useTranslation()
  const toast = useToast()
  const cache = useShoppingCache()
  const lists = useShoppingLists(open)
  const gameLists = (lists.data ?? []).filter((l) => l.game_id === gameId)
  const [chosen, setChosen] = useState<string | null>(null)
  const [newName, setNewName] = useState('')
  const [quantity, setQuantity] = useState(1)
  const [editions, setEditions] = useState<number[] | null>(null)
  const target = chosen ?? (gameLists[0] ? String(gameLists[0].id) : 'new')
  const shownEditions = editions ?? (printingId ? [printingId] : [])
  const add = useMutation({
    mutationFn: async () => {
      let listId = Number(target)
      if (target === 'new') {
        const made = await call(api.POST('/api/shopping-lists', { body: { name: newName.trim(), game_id: gameId } }))
        listId = made.id
      }
      return call(
        api.POST('/api/shopping-lists/{list_id}/items', {
          params: { path: { list_id: listId } },
          body: { card_id: cardId, quantity, printing_ids: shownEditions },
        }),
      )
    },
    onSuccess: async (detail) => {
      await cache(detail)
      toast(t('Added to {{name}}.', { name: detail.name }), 'success')
      setChosen(null)
      setEditions(null)
      setQuantity(1)
      setNewName('')
      onClose()
    },
    onError: (error) => toast(error.message, 'error'),
  })
  const ready = quantity >= 1 && (target !== 'new' || newName.trim().length > 0)
  return (
    <dialog className={`modal ${open ? 'modal-open' : ''}`} onClose={onClose}>
      {open && (
        <form
          className="modal-box rounded-[20px] animate-in fade-in zoom-in-95 duration-200"
          onSubmit={(e) => {
            e.preventDefault()
            if (ready) add.mutate()
          }}
        >
          <h3 className="text-2xl">{t('Add to shopping list')}</h3>
          <div className="mt-4 flex flex-col gap-3">
            <label className="fieldset py-0">
              <span className="fieldset-legend">{t('Shopping list')}</span>
              <Select
                className="w-full"
                value={target}
                onChange={setChosen}
                aria-label={t('Shopping list')}
                options={[...gameLists.map((l) => ({ value: String(l.id), label: l.name })), { value: 'new', label: t('New list…') }]}
              />
            </label>
            {target === 'new' && (
              <label className="fieldset py-0">
                <span className="fieldset-legend">{t('Name')}</span>
                <input className="input w-full" value={newName} maxLength={100} autoFocus onChange={(e) => setNewName(e.target.value)} />
              </label>
            )}
            <label className="fieldset py-0">
              <span className="fieldset-legend">{t('Copies')}</span>
              <input
                type="number"
                className="input w-28"
                min={1}
                max={999}
                value={quantity}
                onChange={(e) => setQuantity(Math.max(1, Math.min(999, Number(e.target.value) || 1)))}
              />
            </label>
            <div className="fieldset py-0">
              <span className="fieldset-legend">{t('Editions')}</span>
              <EditionPicker cardId={cardId} value={shownEditions} onChange={setEditions} />
            </div>
          </div>
          <div className="modal-action">
            <button type="button" className="btn btn-ghost" onClick={onClose}>
              {t('Cancel')}
            </button>
            <button type="submit" className="btn btn-primary" disabled={!ready || add.isPending}>
              {add.isPending && <span className="loading loading-spinner loading-sm" />}
              {t('Add')}
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

/** One box per copy, ticked from the left (like the Android app): a box not ticked
 * ticks up to it, a ticked box unticks from it. */
export function CopyBoxes({
  quantity,
  bought,
  onChange,
  disabled,
  label,
}: {
  quantity: number
  bought: number
  onChange: (bought: number) => void
  disabled?: boolean
  label: string
}) {
  const { t } = useTranslation()
  return (
    <span className="flex flex-wrap gap-1" role="group" aria-label={label}>
      {Array.from({ length: quantity }, (_, copy) => (
        <input
          key={copy}
          type="checkbox"
          className="checkbox checkbox-sm checkbox-primary"
          checked={copy < bought}
          disabled={disabled}
          aria-label={t('Copy {{n}} of {{total}}', { n: copy + 1, total: quantity })}
          onChange={() => onChange(copy < bought ? copy : copy + 1)}
        />
      ))}
    </span>
  )
}
