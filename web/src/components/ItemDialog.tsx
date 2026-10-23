import { useMutation } from '@tanstack/react-query'
import { useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { api, call, type Schemas } from '../api/client'
import { useInvalidateStock } from '../api/stock'
import { useGame } from '../api/queries'
import { formatMoney } from '../lib/format'
import { ConditionBadge, FinishBadge, LangFlag } from './Badges'
import { useToast } from './toast'
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
    onSuccess: () => {
      toast(t('Saved'))
      close()
      return invalidate()
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
    <div className="modal-box animate-in fade-in zoom-in-95 duration-200">
        <h3 className="text-lg font-bold">
          <ShownName name={item.name} translation={item.translation} />
        </h3>
        <p className="flex flex-wrap items-center gap-1 text-sm text-base-content/60">
          {item.set.name} {item.collector_number}
          <RarityBadge game={game} rarity={item.rarity} code={item.rarity_code} lang={item.language} />
          <FinishBadge game={game} finish={item.finish} />
          <ConditionBadge condition={item.condition} />
          <LangFlag lang={item.language} />
        </p>
        <div className="mt-4 flex flex-col gap-2">
          <label className="fieldset">
            <span className="fieldset-legend">{t('Quantity')}</span>
            <input type="number" min={0} className="input w-32" value={quantity} onChange={(e) => setQuantity(Math.max(0, Number(e.target.value) || 0))} />
          </label>
          <label className="fieldset">
            <span className="fieldset-legend">{t('Manual price ({{currency}})', { currency: item.currency })}</span>
            <input inputMode="decimal" className="input w-40" placeholder={item.market_price ? t('Market {{price}}', { price: formatMoney(item.market_price, item.currency) }) : t('No market price')} value={price} onChange={(e) => setPrice(e.target.value)} />
            <span className="label">{t('Empty = use the market price')}</span>
          </label>
          <label className="fieldset">
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
            <button className="btn btn-ghost text-error mr-auto" onClick={() => setConfirmDelete(true)}>
              {t('Delete')}
            </button>
          )}
          <form method="dialog">
            <button className="btn btn-ghost">{t('Cancel')}</button>
          </form>
          <button className="btn btn-primary" disabled={save.isPending} onClick={() => save.mutate()}>
            {t('Save')}
          </button>
        </div>
    </div>
  )
}
