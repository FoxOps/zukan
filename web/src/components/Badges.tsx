import type { Game } from '../api/queries'
import { CONDITIONS, LANGUAGE_FLAGS, conditionName, finishName, languageName } from '../lib/format'
import cn from 'flag-icons/flags/4x3/cn.svg'
import de from 'flag-icons/flags/4x3/de.svg'
import es from 'flag-icons/flags/4x3/es.svg'
import fr from 'flag-icons/flags/4x3/fr.svg'
import gb from 'flag-icons/flags/4x3/gb.svg'
import it from 'flag-icons/flags/4x3/it.svg'
import jp from 'flag-icons/flags/4x3/jp.svg'
import kr from 'flag-icons/flags/4x3/kr.svg'
import pt from 'flag-icons/flags/4x3/pt.svg'
import ru from 'flag-icons/flags/4x3/ru.svg'
import tw from 'flag-icons/flags/4x3/tw.svg'

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

const FLAGS: Record<string, string> = { cn, de, es, fr, gb, it, jp, kr, pt, ru, tw }

/** Flag of a card language, its name as tooltip; the code when no flag is known. */
export function LangFlag({ lang, className = 'h-3.5' }: { lang: string; className?: string }) {
  const country = LANGUAGE_FLAGS[lang]
  const src = country && FLAGS[country]
  if (!src) return <span className="badge badge-ghost badge-sm" title={languageName(lang)}>{lang}</span>
  return (
    <img
      src={src}
      alt={languageName(lang)}
      title={languageName(lang)}
      className={`inline-block aspect-[4/3] rounded-[2px] shadow-sm ring-1 ring-base-content/10 ${className}`}
    />
  )
}
