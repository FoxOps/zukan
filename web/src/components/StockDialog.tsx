import { useEffect, useRef, useState } from 'react'
import type { Game } from '../api/queries'
import { useAdjust } from '../api/stock'
import { CONDITIONS, languageName } from '../lib/format'

export type StockTarget = {
  printingId: number
  title: string
  finishes: string[]
  languages: string[]
}

type Props = { game?: Game; target: StockTarget | null; onClose: () => void }

/** Pick finish, condition, language and quantity, then add or remove copies. */
export function StockDialog({ game, target, onClose }: Props) {
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
        <button>close</button>
      </form>
    </dialog>
  )
}

function StockForm({ game, target, close }: { game: Game; target: StockTarget; close: () => void }) {
  const adjust = useAdjust()
  const finishes = target.finishes.length ? target.finishes : game.finishes.map((f) => f.code)
  const [finish, setFinish] = useState(finishes[0] ?? '')
  const [condition, setCondition] = useState<(typeof CONDITIONS)[number]['code']>('NM')
  const [language, setLanguage] = useState(() => {
    const preferred = localStorage.getItem('tcg.language')
    return preferred && game.languages.includes(preferred) ? preferred : (target.languages[0] ?? 'en')
  })
  const [quantity, setQuantity] = useState(1)

  const submit = (sign: 1 | -1) => {
    localStorage.setItem('tcg.language', language)
    adjust.mutate(
      { printing_id: target.printingId, finish, condition, language, delta: sign * quantity, source: 'web' },
      { onSuccess: close },
    )
  }
  const finishName = (code: string) => game.finishes.find((f) => f.code === code)?.name ?? code

  return (
    <div className="modal-box animate-in fade-in zoom-in-95 duration-200">
      <h3 className="text-lg font-bold">{target.title}</h3>
      <div className="mt-4 grid grid-cols-2 gap-3">
        <div className="fieldset col-span-2">
          <span className="fieldset-legend">Finish</span>
          <div className="join">
            {finishes.map((f) => (
              <input
                key={f}
                type="radio"
                name="finish"
                className="join-item btn btn-sm"
                aria-label={finishName(f)}
                checked={finish === f}
                onChange={() => setFinish(f)}
              />
            ))}
          </div>
        </div>
        <label className="fieldset">
          <span className="fieldset-legend">Condition</span>
          <select
            className="select select-sm"
            value={condition}
            onChange={(e) => setCondition(e.target.value as typeof condition)}
          >
            {CONDITIONS.map((c) => (
              <option key={c.code} value={c.code}>
                {c.code} — {c.name}
              </option>
            ))}
          </select>
        </label>
        <label className="fieldset">
          <span className="fieldset-legend">Language</span>
          <select className="select select-sm" value={language} onChange={(e) => setLanguage(e.target.value)}>
            {game.languages.map((l) => (
              <option key={l} value={l}>
                {languageName(l)}
                {target.languages.includes(l) ? '' : ' (not listed)'}
              </option>
            ))}
          </select>
        </label>
        <label className="fieldset col-span-2">
          <span className="fieldset-legend">Quantity</span>
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
          <button className="btn btn-ghost">Cancel</button>
        </form>
        <button className="btn btn-outline btn-error" disabled={adjust.isPending} onClick={() => submit(-1)}>
          Remove
        </button>
        <button className="btn btn-primary" disabled={adjust.isPending || !finish} onClick={() => submit(1)}>
          Add
        </button>
      </div>
    </div>
  )
}
