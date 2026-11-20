import type { ReactNode } from 'react'
import type { Game } from '../api/queries'
import { ColorSymbol } from '../components/ColorBadges'

// Pokémon energy types as TCGdex writes them in each card language.
const POKEMON_TYPES: Record<string, string> = Object.fromEntries(
  Object.entries({
    grass: ['Grass', 'Plante', 'Pflanze', 'Planta', 'Erba', 'Grama'],
    fire: ['Fire', 'Feu', 'Feuer', 'Fuego', 'Fuoco', 'Fogo'],
    water: ['Water', 'Eau', 'Wasser', 'Agua', 'Acqua', 'Água'],
    lightning: ['Lightning', 'Électrique', 'Elektro', 'Rayo', 'Lampo', 'Elétrico'],
    psychic: ['Psychic', 'Psy', 'Psycho', 'Psíquico', 'Psico'],
    fighting: ['Fighting', 'Combat', 'Kampf', 'Lucha', 'Lotta', 'Lutador'],
    darkness: ['Darkness', 'Obscurité', 'Finsternis', 'Oscuridad', 'Oscurità', 'Escuridão'],
    metal: ['Metal', 'Métal', 'Metall', 'Metálica', 'Acero', 'Metallo'],
    fairy: ['Fairy', 'Fée', 'Fee', 'Hada', 'Folletto', 'Fada'],
    dragon: ['Dragon', 'Drache', 'Dragón', 'Drago', 'Dragão'],
    colorless: ['Colorless', 'Incolore', 'Farblos', 'Incolora', 'Incoloro', 'Incolor'],
  }).flatMap(([code, names]) => names.map((name) => [name.toLowerCase(), code])),
)

/** A game color by code, or by name (Pokémon attack costs name energy types). */
function colorOf(game: Game, value: string) {
  const code = game.group === 'pokemon' ? (POKEMON_TYPES[value.toLowerCase()] ?? value) : value
  return game.colors.find((c) => c.code === code || c.name.toLowerCase() === value.toLowerCase())
}

/** Costs given as color names or codes (Pokémon attack costs), as their symbols; null
 * when one is not a color of the game (or has no picture yet). */
export function costSymbols(game: Game | undefined, values: string[]): ReactNode {
  if (!game || values.length === 0) return null
  const colors = values.map((v) => colorOf(game, v))
  if (colors.some((c) => !c?.icon)) return null
  return (
    <span className="inline-flex flex-wrap items-center gap-0.5 align-middle">
      {colors.map((color, i) => (
        <ColorSymbol key={i} color={color!} size="h-[1.15em] w-[1.15em]" />
      ))}
    </span>
  )
}

/** Counts by color code (Sorcery thresholds `{fire: 2}`), as that many symbols; null
 * when a key is not a color of the game. */
export function thresholdSymbols(game: Game | undefined, counts: Record<string, unknown>): ReactNode {
  if (!game) return null
  const entries = Object.entries(counts).filter(([, n]) => typeof n === 'number' && n > 0) as [string, number][]
  if (entries.length === 0 || entries.some(([k]) => !colorOf(game, k)?.icon)) return null
  return costSymbols(game, entries.flatMap(([k, n]) => Array<string>(Math.min(n, 9)).fill(k)))
}
