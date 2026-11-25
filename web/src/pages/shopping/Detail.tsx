import { keepPreviousData, useMutation, useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link, useNavigate, useParams } from 'react-router'
import { api, call } from '../../api/client'
import { useGame } from '../../api/queries'
import { editionsLabel, SHOPPING_FORMATS, useShoppingCache, useShoppingEdits, useShoppingList, type ShoppingDetail, type ShoppingItem } from '../../api/shopping'
import { CardImage } from '../../components/CardImage'
import { SearchInput } from '../../components/Filters'
import { Icon } from '../../components/Icon'
import { Pagination } from '../../components/Pagination'
import { CopyBoxes, EditionPicker, SourceListButton } from '../../components/Shopping'
import { ShownName } from '../../components/ShownName'
import { useToast } from '../../components/toast'
import { finishName, formatDate, languageName } from '../../lib/format'
import { SourceBadge } from '../Shopping'

const PAGE_SIZE = 12

/** Search the list's game in the catalog (name in any language) and add one copy of a
 * card, any edition; copies and editions are changed on the item after. */
function AddCards({ list, busy, onAdd }: { list: ShoppingDetail; busy: boolean; onAdd: (cardId: number) => void }) {
  const { t } = useTranslation()
  const [open, setOpen] = useState(list.items.length === 0)
  const [q, setQ] = useState('')
  const [page, setPage] = useState(1)
  const results = useQuery({
    queryKey: ['shopping-card-search', list.game_id, q, page],
    enabled: open && q.length > 0,
    placeholderData: keepPreviousData,
    queryFn: ({ signal }) => call(api.GET('/api/cards', { signal, params: { query: { game: list.game_id, q, page, page_size: PAGE_SIZE } } })),
  })
  const cards = q ? (results.data?.items ?? []) : []
  return (
    <div className="card rounded-[20px] border border-base-300 bg-base-100">
      <div className="card-body gap-3 p-4">
        <button type="button" className="flex items-center gap-2 font-semibold" aria-expanded={open} onClick={() => setOpen((o) => !o)}>
          <span className={`transition-transform ${open ? 'rotate-90' : ''}`} aria-hidden>
            ▸
          </span>
          {t('Add cards')}
        </button>
        {open && (
          <>
            <SearchInput
              value={q}
              onChange={(v) => {
                setQ(v)
                setPage(1)
              }}
              placeholder={t('Name in any language')}
            />
            {!q ? (
              <p className="text-sm text-base-content/70">{t('Search the catalog by name to add cards.')}</p>
            ) : results.isError ? (
              <div className="alert alert-error">{results.error.message}</div>
            ) : results.data ? (
              cards.length === 0 ? (
                <p className="text-sm text-base-content/70">{t('No cards found')}</p>
              ) : (
                <>
                  <ul className="flex flex-col divide-y divide-base-300">
                    {cards.map((card) => (
                      <li key={card.id} className="flex items-center gap-2 px-1 py-1.5">
                        <span className="block w-8 shrink-0">
                          <CardImage thumb src={card.image} alt="" game={list.game_id} landscape={card.orientation === 'landscape'} />
                        </span>
                        <span className="min-w-0 flex-1 truncate text-sm">
                          <ShownName name={card.name} translation={card.translation} />
                        </span>
                        <button type="button" className="btn btn-primary btn-xs" disabled={busy} onClick={() => onAdd(card.id)} title={t('Add one copy (any printing)')}>
                          +1
                        </button>
                      </li>
                    ))}
                  </ul>
                  <div className="flex justify-center">
                    <Pagination page={page} pageSize={PAGE_SIZE} total={results.data.total} onChange={setPage} />
                  </div>
                </>
              )
            ) : (
              <span className="loading loading-dots loading-md mx-auto" />
            )}
          </>
        )}
      </div>
    </div>
  )
}

function ItemRow({ list, item }: { list: ShoppingDetail; item: ShoppingItem }) {
  const { t } = useTranslation()
  const toast = useToast()
  const game = useGame(list.game_id)
  const { patch, remove } = useShoppingEdits(list.id, (e) => toast(e.message, 'error'))
  const [editing, setEditing] = useState(false)
  const busy = patch.isPending || remove.isPending
  const editions = editionsLabel(item)
  const wanted = [item.language && languageName(item.language), item.finish && finishName(game, item.finish)].filter(Boolean).join(' · ')
  const done = item.bought_count >= item.quantity
  return (
    <li className="flex flex-col gap-2 px-3 py-2">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
        <CopyBoxes
          quantity={item.quantity}
          bought={item.bought_count}
          disabled={busy}
          label={t('Copies of {{name}} bought', { name: item.name })}
          onChange={(bought) => patch.mutate({ itemId: item.id, body: { bought_count: bought } })}
        />
        <span className="w-8 text-right font-mono text-sm">{item.quantity}×</span>
        <span className={`min-w-0 flex-1 ${done ? 'text-base-content/50 line-through' : ''}`}>
          {item.card_id ? (
            <Link className="link-hover" to={`/cards/${item.card_id}`}>
              <ShownName name={item.name} translation={item.translation} />
            </Link>
          ) : (
            <ShownName name={item.name} translation={item.translation} />
          )}
          <span className="block text-xs text-base-content/70">
            <span className="font-mono">{editions || t('Any edition')}</span>
            {wanted && ` · ${wanted}`}
            {item.manual && list.source && ` · ${t('added by hand')}`}
          </span>
        </span>
        <span className="join">
          <button className="btn btn-xs join-item" aria-label={t('One copy less')} disabled={busy || item.quantity <= 1} onClick={() => patch.mutate({ itemId: item.id, body: { quantity: item.quantity - 1 } })}>
            <Icon name="minus" />
          </button>
          <button className="btn btn-xs join-item" aria-label={t('One copy more')} disabled={busy || item.quantity >= 999} onClick={() => patch.mutate({ itemId: item.id, body: { quantity: item.quantity + 1 } })}>
            <Icon name="plus" />
          </button>
        </span>
        {item.card_id && (
          <button className="btn btn-ghost btn-xs" aria-expanded={editing} onClick={() => setEditing((e) => !e)}>
            {t('Editions')}
          </button>
        )}
        <button className="btn btn-ghost btn-xs text-error" aria-label={t('Remove {{name}}', { name: item.name })} disabled={busy} onClick={() => remove.mutate(item.id)}>
          <Icon name="close" />
        </button>
      </div>
      {editing && item.card_id && (
        <div className="ml-2 rounded-box bg-base-200 p-3">
          <EditionPicker
            cardId={item.card_id}
            disabled={busy}
            value={item.editions.flatMap((e) => (e.printing_id ? [e.printing_id] : []))}
            onChange={(ids) => patch.mutate({ itemId: item.id, body: { printing_ids: ids } })}
          />
        </div>
      )}
    </li>
  )
}

/** One shopping list: rename it, add and remove cards, change copies and editions, tick
 * copies bought, download it; a list of a deck or a followed set is updated from it. */
export default function ShoppingDetailPage() {
  const { t } = useTranslation()
  const toast = useToast()
  const navigate = useNavigate()
  const cache = useShoppingCache()
  const { listId } = useParams()
  const id = Number(listId)
  const query = useShoppingList(id)
  const { add, rename } = useShoppingEdits(id, (e) => toast(e.message, 'error'))
  const [name, setName] = useState<string | null>(null)
  const [deleting, setDeleting] = useState(false)
  const remove = useMutation({
    mutationFn: () => call(api.DELETE('/api/shopping-lists/{list_id}', { params: { path: { list_id: id } } })),
    onSuccess: async () => {
      await cache(null, id)
      navigate('/shopping')
    },
    onError: (e) => toast(e.message, 'error'),
  })

  if (query.isPending) return <span className="loading loading-spinner loading-lg m-auto block" />
  if (query.isError) return <div className="alert alert-error">{query.error.message}</div>
  const list = query.data
  const saveName = () => {
    const next = name?.trim()
    if (next && next !== list.name) rename.mutate(next)
    setName(null)
  }
  const sourceLink = list.deck_id ? `/decks/${list.deck_id}` : list.binder_id ? `/binder/${list.binder_id}` : null

  return (
    <div className="flex flex-col gap-4">
      <Link to="/shopping" className="link-hover text-sm text-base-content/70">
        ← {t('Shopping list')}
      </Link>
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="flex min-w-0 flex-col gap-1">
          {name === null ? (
            <button className="text-left text-3xl font-display font-bold" title={t('Rename')} onClick={() => setName(list.name)}>
              {list.name}
            </button>
          ) : (
            <form
              onSubmit={(e) => {
                e.preventDefault()
                saveName()
              }}
            >
              <input className="input input-lg" value={name} maxLength={100} autoFocus aria-label={t('Name')} onChange={(e) => setName(e.target.value)} onBlur={saveName} />
            </form>
          )}
          <div className="flex flex-wrap items-center gap-2 text-sm text-base-content/70">
            <SourceBadge list={list} />
            {sourceLink && (
              <Link className="link" to={sourceLink}>
                {list.source === 'deck' ? t('Open the deck') : t('Open the set')}
              </Link>
            )}
            <span>{t('Changed {{date}}', { date: formatDate(list.updated_at) })}</span>
            <span>· {t('{{bought}} of {{copies}} copies bought', { bought: list.bought, copies: list.copies })}</span>
          </div>
        </div>
        <div className="flex flex-wrap gap-2">
          {list.source && (
            <SourceListButton
              source={list.source}
              sourceId={(list.source === 'deck' ? list.deck_id : list.binder_id) as number}
              listId={list.id}
              onDeleted={() => navigate('/shopping', { replace: true })}
            />
          )}
          {SHOPPING_FORMATS.map((format) => (
            <a key={format} className="btn" href={`/api/shopping-lists/${list.id}/download?format=${format}`} download>
              {t('Download .{{format}}', { format })}
            </a>
          ))}
          <button className="btn btn-ghost text-error" onClick={() => setDeleting(true)}>
            {t('Delete')}
          </button>
        </div>
      </div>
      {list.source && <p className="text-sm text-base-content/70">{t('Update list rebuilds the cards from what is still missing: cards added by hand go, ticks stay on copies still missing.')}</p>}

      <AddCards list={list} busy={add.isPending} onAdd={(cardId) => add.mutate({ card_id: cardId, quantity: 1, printing_ids: [] })} />

      {list.items.length === 0 ? (
        <div className="rounded-2xl border border-dashed border-base-300 p-6 text-center text-base-content/70">{t('This list is empty.')}</div>
      ) : (
        <ul className="flex flex-col divide-y divide-base-300 rounded-2xl border border-base-300 bg-base-100">
          {list.items.map((item) => (
            <ItemRow key={item.id} list={list} item={item} />
          ))}
        </ul>
      )}

      <dialog className={`modal ${deleting ? 'modal-open' : ''}`} onClose={() => setDeleting(false)}>
        {deleting && (
          <div className="modal-box rounded-[20px]">
            <h3 className="text-2xl">{t('Delete {{name}}?', { name: list.name })}</h3>
            <p className="py-2 text-sm text-base-content/70">{t('The list and its ticks are deleted, in the Android app too. Your collection does not change.')}</p>
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
