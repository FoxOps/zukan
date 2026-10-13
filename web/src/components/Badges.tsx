import type { Game } from '../api/queries'
import { CONDITIONS, conditionName, finishName } from '../lib/format'

// Special finishes stand out from the game's base finish (non-foil, normal, standard).
const FINISH_STYLES: Record<string, string> = {
  foil: 'border-0 bg-linear-to-r from-sky-300 via-fuchsia-300 to-amber-200 text-neutral-900',
  holo: 'border-0 bg-linear-to-r from-indigo-300 via-sky-300 to-emerald-300 text-neutral-900',
  reverse: 'border-0 bg-linear-to-r from-pink-300 via-violet-300 to-sky-300 text-neutral-900',
  etched: 'border-0 bg-linear-to-r from-stone-300 via-amber-200 to-stone-400 text-neutral-900',
  rainbow: 'border-0 bg-linear-to-r from-red-300 via-yellow-200 to-sky-300 text-neutral-900',
  first_edition: 'badge-neutral',
}

export function FinishBadge({ game, finish, size = 'badge-sm' }: { game?: Game; finish: string; size?: string }) {
  const base = game?.finishes[0]?.code === finish
  const style = base ? 'badge-ghost' : (FINISH_STYLES[finish] ?? 'badge-accent')
  return <span className={`badge ${size} whitespace-nowrap ${style}`}>{finishName(game, finish)}</span>
}

export function ConditionBadge({ condition, size = 'badge-sm' }: { condition: string; size?: string }) {
  const color = CONDITIONS.find((c) => c.code === condition)?.color ?? '#888'
  return (
    <span
      className={`badge ${size} border-0 font-semibold ${condition === 'GD' ? 'text-neutral-900' : 'text-white'}`}
      style={{ backgroundColor: color }}
      title={conditionName(condition)}
    >
      {condition}
    </span>
  )
}
