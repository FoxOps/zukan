import type { Game } from '../api/queries'

type Props = {
  game?: Game
  // Rarity as the card data spells it, and the game's rarity it stands for.
  rarity: string | null | undefined
  code?: string | null
  className?: string
}

/** Rarity pictogram (when the game has one) next to its name: both are always shown. */
export function RarityBadge({ game, rarity, code, className = '' }: Props) {
  if (!rarity) return null
  const icon = code ? game?.rarities?.find((r) => r.code === code)?.icon : null
  return (
    <span className={`inline-flex items-center gap-1 whitespace-nowrap ${className}`}>
      {icon && <img src={icon} alt="" aria-hidden className="inline-block h-4 w-4 shrink-0 object-contain" />}
      <span className="capitalize">{rarity}</span>
    </span>
  )
}
