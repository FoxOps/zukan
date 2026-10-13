import type { Game } from '../api/queries'

/** Game colors (MTG mana, Pokémon energy, Sorcery elements) as badges; hex comes from the
 * game plugin so new games need no UI change. */
export function ColorBadges({ game, colors }: { game?: Game; colors: string[] }) {
  if (!colors.length) return null
  return (
    <span className="inline-flex flex-wrap gap-1">
      {colors.map((code) => {
        const color = game?.colors.find((c) => c.code === code)
        return (
          <span
            key={code}
            className="badge badge-sm border-0 text-white [text-shadow:0_0_2px_#000]"
            style={{ backgroundColor: color?.hex ?? '#888' }}
            title={color?.name ?? code}
          >
            {color?.name ?? code}
          </span>
        )
      })}
    </span>
  )
}
