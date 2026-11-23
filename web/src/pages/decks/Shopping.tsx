import { useMutation, useQuery } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { api, call, type Schemas } from '../../api/client'
import { useToast } from '../../components/toast'

const FORMATS = ['txt', 'md', 'pdf'] as const

/** The cards the deck misses (neither set aside for it nor free in the collection), as a
 * check list to take to a shop: a .txt / .md / .pdf file, or a list sent to the Android
 * app, ticked there while buying (and deleted only there). */
export function ShoppingDialog({ deck, open, onClose }: { deck: Schemas['DeckOut']; open: boolean; onClose: () => void }) {
  const { t } = useTranslation()
  const toast = useToast()
  const shopping = useQuery({
    queryKey: ['deck-shopping', deck.id, deck.updated_at],
    enabled: open,
    queryFn: () => call(api.GET('/api/decks/{deck_id}/shopping', { params: { path: { deck_id: deck.id } } })),
  })
  const send = useMutation({
    mutationFn: () => call(api.POST('/api/decks/{deck_id}/shopping-list', { params: { path: { deck_id: deck.id } } })),
    onSuccess: () => toast(t('Shopping list sent: open it in the Zukan Android app.'), 'success'),
    onError: (error) => toast(error.message, 'error'),
  })
  const lines = shopping.data?.lines ?? []
  const copies = lines.reduce((n, l) => n + l.quantity, 0)

  return (
    <dialog className={`modal ${open ? 'modal-open' : ''}`} onClose={onClose}>
      {open && (
        <div className="modal-box rounded-[20px] max-w-2xl animate-in fade-in zoom-in-95 duration-200">
          <h3 className="text-2xl">{t('Shopping list for {{name}}', { name: deck.name })}</h3>
          <p className="py-1 text-sm text-base-content/70">
            {t('Copies neither set aside for this deck nor free in your collection (copies other decks hold count as missing).')}
          </p>
          {shopping.isError ? (
            <div className="alert alert-error">{shopping.error.message}</div>
          ) : shopping.isPending ? (
            <span className="loading loading-spinner" />
          ) : lines.length === 0 ? (
            <div className="alert alert-success">{t('You have every card of this deck.')}</div>
          ) : (
            <>
              <div className="text-sm font-medium">{t('{{count}} cards to get', { count: copies })}</div>
              <ul className="mt-2 max-h-72 overflow-y-auto rounded-box bg-base-200 p-2 text-sm">
                {lines.map((l) => (
                  <li key={`${l.card_id}-${l.printing_id}`} className="flex gap-2 px-2 py-1">
                    <span className="w-6 text-right font-mono">{l.quantity}</span>
                    <span className="min-w-0 flex-1">
                      {l.name}
                      {l.translation && <span className="text-base-content/70"> ({l.translation})</span>}
                    </span>
                    {l.set_code && (
                      <span className="font-mono text-xs text-base-content/70">
                        {l.set_code} {l.collector_number}
                      </span>
                    )}
                  </li>
                ))}
              </ul>
            </>
          )}
          <div className="modal-action flex-wrap">
            <button className="btn btn-ghost" onClick={onClose}>
              {t('Close')}
            </button>
            {FORMATS.map((format) => (
              <a
                key={format}
                className={`btn ${lines.length === 0 ? 'btn-disabled' : ''}`}
                aria-disabled={lines.length === 0}
                href={`/api/decks/${deck.id}/shopping/download?format=${format}`}
                download
              >
                {t('Download .{{format}}', { format })}
              </a>
            ))}
            <button className="btn btn-primary" disabled={lines.length === 0 || send.isPending} onClick={() => send.mutate()}>
              {t('Send to the app')}
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
