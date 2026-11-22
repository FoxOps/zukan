import { useDeckFormats } from '../../api/queries'

/** "Commander" / "Standard" as the formats endpoint names them (`enabled`: the user has
 * the Decks module). */
export function useFormatName(enabled = true) {
  const { data: games = [] } = useDeckFormats(enabled)
  return (id: string) => games.flatMap((g) => g.formats).find((f) => f.id === id)?.name ?? id
}
