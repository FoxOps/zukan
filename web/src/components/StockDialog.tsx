import { useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import type { Game } from '../api/queries'
import { useAdjust } from '../api/stock'
import { currentLanguage } from '../i18n'
import { CONDITIONS, conditionName, finishName, languageName } from '../lib/format'
import { LangFlag } from './Badges'

export type StockTarget = {
  printingId: number
  title: string
  finishes: string[]
  languages: string[]
}

type Props = { game?: Game; target: StockTarget | null; onClose: () => void }

/** Pick finish, condition, language and quantity, then add or remove copies. */
export function StockDialog({ game, target, onClose }: Props) {
  const { t } = useTranslation()
  const dialog = useRef<HTMLDialogElement>(null)
  useEffect(() => {
    if (target) dialog.current?.showModal()
  }, [target])
  return (
    <dialog ref={dialog} className="modal" onClose={onClose}>
      {target && game && (
        // Keyed so each opening starts from fresh defaults.
        <StockForm key={target.printingId} game={game} target={target} close={() => dialog.current?.close()} />
      )}
      <form method="dialog" className="modal-backdrop">
        <button>{t('close')}</button>
      </form>
    </dialog>
  )
}

function StockForm({ game, target, close }: { game: Game; target: StockTarget; close: () => void }) {
  const { t } = useTranslation()
  const adjust = useAdjust()
  const finishes = target.finishes.length ? target.finishes : game.finishes.map((f) => f.code)
  const [finish, setFinish] = useState(finishes[0] ?? '')
  const [condition, setCondition] = useState<(typeof CONDITIONS)[number]['code']>('NM')
  // Languages the printing exists in (all of the game's when the catalog does not say).
  const languages = target.languages.length ? target.languages : game.languages
  const [language, setLanguage] = useState(() => {
    const preferred = [localStorage.getItem('tcg.language'), currentLanguage()]
    return preferred.find((l) => l && languages.includes(l)) ?? languages[0] ?? 'en'
  })
  const [quantity, setQuantity] = useState(1)

  const submit = (sign: 1 | -1) => {
    localStorage.setItem('tcg.language', language)
    adjust.mutate(
      { printing_id: target.printingId, finish, condition, language, delta: sign * quantity, source: 'web' },
      { onSuccess: close },
    )
  }

  return (
    <div className="modal-box animate-in fade-in zoom-in-95 duration-200">
      <h3 className="text-lg font-bold">{target.title}</h3>
      <div className="mt-4 grid grid-cols-2 gap-3">
        <div className="fieldset col-span-2">
          <span className="fieldset-legend">{t('Finish')}</span>
          <div className="join">
            {finishes.map((f) => (
              <input
                key={f}
                type="radio"
                name="finish"
                className="join-item btn btn-sm"
                aria-label={finishName(game, f)}
                checked={finish === f}
                onChange={() => setFinish(f)}
              />
            ))}
          </div>
        </div>
        <div className="fieldset col-span-2">
          <span className="fieldset-legend">
            {t('Condition')}: {conditionName(condition)}
          </span>
          <div className="flex flex-wrap gap-1">
            {CONDITIONS.map((c) => (
              <button
                key={c.code}
                type="button"
                title={t(c.name)}
                aria-pressed={condition === c.code}
                className={`btn btn-sm min-w-11 border-0 font-semibold ${c.code === 'GD' ? 'text-neutral-900' : 'text-white'} ${condition === c.code ? 'ring-2 ring-base-content ring-offset-2 ring-offset-base-100' : 'opacity-60 hover:opacity-100'}`}
                style={{ backgroundColor: c.color }}
                onClick={() => setCondition(c.code)}
              >
                {c.code}
              </button>
            ))}
          </div>
        </div>
        <div className="fieldset">
          <span className="fieldset-legend">
            {t('Language')}: {languageName(language)}
          </span>
          <div className="flex flex-wrap gap-1">
            {languages.map((l) => (
              <button
                key={l}
                type="button"
                title={languageName(l)}
                aria-label={languageName(l)}
                aria-pressed={language === l}
                className={`btn btn-sm btn-ghost px-1.5 ${language === l ? 'ring-2 ring-base-content ring-offset-2 ring-offset-base-100' : 'opacity-60 hover:opacity-100'}`}
                onClick={() => setLanguage(l)}
              >
                <LangFlag lang={l} className="h-5" />
              </button>
            ))}
          </div>
        </div>
        <label className="fieldset">
          <span className="fieldset-legend">{t('Quantity')}</span>
          <input
            type="number"
            min={1}
            max={1000}
            className="input input-sm w-32"
            value={quantity}
            onChange={(e) => setQuantity(Math.max(1, Math.min(1000, Number(e.target.value) || 1)))}
          />
        </label>
      </div>
      <div className="modal-action">
        <form method="dialog">
          <button className="btn btn-ghost">{t('Cancel')}</button>
        </form>
        <button className="btn btn-outline btn-error" disabled={adjust.isPending} onClick={() => submit(-1)}>
          {t('Remove')}
        </button>
        <button className="btn btn-primary" disabled={adjust.isPending || !finish} onClick={() => submit(1)}>
          {t('Add')}
        </button>
      </div>
    </div>
  )
}
