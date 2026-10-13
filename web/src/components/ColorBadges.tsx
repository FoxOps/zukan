import type { Game } from '../api/queries'
import { t } from '../i18n'

type Color = Game['colors'][number]

/** A game color (MTG mana, Pokémon energy, Sorcery element): its official symbol once the
 * server has it, else a badge in the plugin's color, so new games need no UI change. */
export function ColorSymbol({ color, size = 'h-5 w-5' }: { color: Color; size?: string }) {
  const name = t(color.name)
  if (color.icon) {
    return <img src={color.icon} alt={name} title={name} className={`${size} inline-block object-contain`} />
  }
  return (
    <span
      className="badge badge-sm border-0 text-white [text-shadow:0_0_2px_#000]"
      style={{ backgroundColor: color.hex }}
      title={name}
    >
      {name}
    </span>
  )
}

export function ColorBadges({ game, colors }: { game?: Game; colors: string[] }) {
  if (!colors.length) return null
  return (
    <span className="inline-flex flex-wrap items-center gap-1">
      {colors.map((code) => {
        const color = game?.colors.find((c) => c.code === code)
        return <ColorSymbol key={code} color={color ?? { code, name: code, hex: '#888', icon: null }} />
      })}
    </span>
  )
}
