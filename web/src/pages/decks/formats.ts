import { useDeckFormats } from '../../api/queries'

/** "Commander" / "Standard" as the formats endpoint names them. */
export function useFormatName() {
  const { data: games = [] } = useDeckFormats()
  return (id: string) => games.flatMap((g) => g.formats).find((f) => f.id === id)?.name ?? id
}
