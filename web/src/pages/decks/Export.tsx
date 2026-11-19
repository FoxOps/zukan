import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { api, call, type Schemas } from '../../api/client'
import { useToast } from '../../components/toast'

/** The decklist as text in the game's usual format (Moxfield / MTGO, Pokémon TCG Live,
 * Dreamborn): copy it or save it as a .txt file. The import reads it back. */
export function ExportDialog({ deck, open, onClose }: { deck: Schemas['DeckOut']; open: boolean; onClose: () => void }) {
  const { t } = useTranslation()
  const toast = useToast()
  // Lorcana lists name no set.
  const withSets = deck.game_id !== 'lorcana'
  const [sets, setSets] = useState(true)
  const exported = useQuery({
    queryKey: ['deck-export', deck.id, sets, deck.updated_at],
    enabled: open,
    queryFn: () => call(api.GET('/api/decks/{deck_id}/export', { params: { path: { deck_id: deck.id }, query: { sets } } })),
  })
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(exported.data?.text ?? '')
      toast(t('Decklist copied'), 'success')
    } catch {
      toast(t('Copy failed: select the text and copy it.'), 'error')
    }
  }
  const download = () => {
    if (!exported.data) return
    const link = document.createElement('a')
    link.href = URL.createObjectURL(new Blob([exported.data.text], { type: 'text/plain;charset=utf-8' }))
    link.download = exported.data.filename
    link.click()
    URL.revokeObjectURL(link.href)
  }

  return (
    <dialog className={`modal ${open ? 'modal-open' : ''}`} onClose={onClose}>
      {open && (
        <div className="modal-box max-w-2xl animate-in fade-in zoom-in-95 duration-200">
          <h3 className="text-lg font-bold">{t('Export {{name}}', { name: deck.name })}</h3>
          <p className="py-1 text-sm text-base-content/70">
            {deck.game_id.startsWith('pokemon')
              ? t('Pokémon TCG Live format: paste it in the game or on Limitless.')
              : deck.game_id === 'lorcana'
                ? t('Dreamborn / Inktable format.')
                : t('Moxfield / MTGO format, read by most deck sites.')}
          </p>
          {withSets && (
            <label className="flex items-center gap-2 py-1 text-sm">
              <input type="checkbox" className="toggle toggle-sm toggle-primary" checked={sets} onChange={(e) => setSets(e.target.checked)} />
              {t('Include set codes and numbers (the printing each line asks for, else the allocated copies)')}
            </label>
          )}
          {exported.isError ? (
            <div className="alert alert-error">{exported.error.message}</div>
          ) : (
            <textarea className="textarea mt-2 h-72 w-full font-mono text-sm" readOnly value={exported.data?.text ?? ''} aria-label={t('Decklist')} onFocus={(e) => e.target.select()} />
          )}
          <div className="modal-action">
            <button className="btn btn-ghost" onClick={onClose}>
              {t('Close')}
            </button>
            <button className="btn" disabled={!exported.data} onClick={download}>
              {t('Download .txt')}
            </button>
            <button className="btn btn-primary" disabled={!exported.data} onClick={copy}>
              {t('Copy')}
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
