import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { api, call, type Schemas } from '../api/client'
import { useInvalidateStock } from '../api/stock'
import { useGame } from '../api/queries'
import { formatMoney } from '../lib/format'
import { ConditionBadge, FinishBadge, LangFlag } from './Badges'
import { useToast } from './toast'
import { DialogHeader } from './Page'
import { RarityBadge } from './RarityBadge'
import { ShownName } from './ShownName'

type Item = Schemas['ItemOut']

/** Edit quantity, manual price and notes of an item, or delete it. */
export function ItemDialog({ item, onClose }: { item: Item | null; onClose: () => void }) {
  const { t } = useTranslation()
  const dialog = useRef<HTMLDialogElement>(null)
  useEffect(() => {
    if (item) dialog.current?.showModal()
  }, [item])
  return (
    <dialog ref={dialog} className="modal" onClose={onClose}>
      {item && <ItemForm key={item.id} item={item} close={() => dialog.current?.close()} />}
      <form method="dialog" className="modal-backdrop">
        <button>{t('close')}</button>
      </form>
    </dialog>
  )
}

function ItemForm({ item, close }: { item: Item; close: () => void }) {
  const { t } = useTranslation()
  const toast = useToast()
  const invalidate = useInvalidateStock()
  const client = useQueryClient()
  const game = useGame(item.game_id)
  const [quantity, setQuantity] = useState(item.quantity)
  const [price, setPrice] = useState(item.manual_price ?? '')
  const [notes, setNotes] = useState(item.notes ?? '')
  const [confirmDelete, setConfirmDelete] = useState(false)

  const save = useMutation({
    mutationFn: () =>
      call(
        api.PATCH('/api/collection/items/{item_id}', {
          params: { path: { item_id: item.id } },
          body: {
            quantity,
            manual_price: price.trim() === '' ? null : price.replace(',', '.'),
            notes,
          },
        }),
      ),
    onSuccess: (saved) => {
      // The row changes at once from the server's answer; pages, totals and other views
      // refresh in the background (sorting or filters may move or drop it).
      client.setQueriesData<Schemas['ItemPageOut']>({ queryKey: ['collection'] }, (page) =>
        page?.items && 'page_size' in page ? { ...page, items: page.items.map((i) => (i.id === saved.id ? saved : i)) } : page,
      )
      toast(t('Saved'))
      close()
      void invalidate()
    },
    onError: (e) => toast(e.message, 'error'),
  })
  const remove = useMutation({
    mutationFn: () =>
      call(api.DELETE('/api/collection/items/{item_id}', { params: { path: { item_id: item.id } } })),
    onSuccess: () => {
      toast(t('Item deleted'), 'info')
      close()
      return invalidate()
    },
    onError: (e) => toast(e.message, 'error'),
  })

  return (
    <div className="modal-box max-w-xl rounded-[20px] animate-in fade-in zoom-in-95 duration-200 motion-reduce:animate-none">
        <DialogHeader eyebrow={t('Your collection')} title={<>{t('Edit')} <ShownName name={item.name} translation={item.translation} /></>}>
          {item.set.name} {item.collector_number}
          <RarityBadge game={game} rarity={item.rarity} code={item.rarity_code} lang={item.language} />
          <FinishBadge game={game} finish={item.finish} />
          <ConditionBadge condition={item.condition} />
          <LangFlag lang={item.language} />
          <span>· {t('{{count}} owned', { count: item.quantity })}</span>
        </DialogHeader>
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          <label className="fieldset">
            <span className="fieldset-legend">{t('Quantity')}</span>
            <input type="number" min={0} className="input w-full" value={quantity} onChange={(e) => setQuantity(Math.max(0, Number(e.target.value) || 0))} />
          </label>
          <label className="fieldset">
            <span className="fieldset-legend">{t('Manual price ({{currency}})', { currency: item.currency })}</span>
            <input inputMode="decimal" className="input w-full" placeholder={item.market_price ? t('Market {{price}}', { price: formatMoney(item.market_price, item.currency) }) : t('No market price')} value={price} onChange={(e) => setPrice(e.target.value)} />
            <span className="label">{t('Empty = use the market price')}</span>
          </label>
          <label className="fieldset sm:col-span-2">
            <span className="fieldset-legend">{t('Notes')}</span>
            <textarea className="textarea w-full" maxLength={1000} value={notes} onChange={(e) => setNotes(e.target.value)} />
          </label>
        </div>
        <div className="modal-action flex-wrap">
          {confirmDelete ? (
            <button className="btn btn-error mr-auto" onClick={() => remove.mutate()}>
              {t('Delete item and its history?')}
            </button>
          ) : (
            <button className="btn btn-ghost min-h-11 text-error mr-auto" onClick={() => setConfirmDelete(true)}>
              {t('Delete')}
            </button>
          )}
          <form method="dialog">
            <button className="btn min-h-11">{t('Cancel')}</button>
          </form>
          <button className="btn btn-primary min-h-11" disabled={save.isPending} onClick={() => save.mutate()}>
            {save.isPending && <span className="loading loading-spinner loading-xs" />}
            {t('Save changes')}
          </button>
        </div>
    </div>
  )
}
