import type { Game } from '../api/queries'

type Props = {
  game?: Game
  // Rarity as the card data spells it, and the game's rarity it stands for.
  rarity: string | null | undefined
  code?: string | null
  // Language the card is printed in: Japanese and Chinese cards show other pictograms.
  lang?: string | null
  className?: string
}

/** Rarity pictogram (when the game has one) next to its name: both are always shown. */
export function RarityBadge({ game, rarity, code, lang, className = '' }: Props) {
  if (!rarity) return null
  const def = code ? game?.rarities?.find((r) => r.code === code) : undefined
  const variant = lang ? (def?.icons?.[lang] ?? def?.icons?.[lang.split('-')[0]]) : undefined
  const icon = variant ?? def?.icon
  return (
    <span className={`inline-flex items-center gap-1 whitespace-nowrap ${className}`}>
      {icon && (
        <img
          src={icon}
          alt=""
          aria-hidden
          // Japanese and Chinese pictograms are black letters ("RR"): light on dark themes.
          className={`inline-block h-4 shrink-0 object-contain ${variant ? 'zukan-ink w-auto max-w-8' : 'w-4'}`}
        />
      )}
      <span className="capitalize">{rarity}</span>
    </span>
  )
}
