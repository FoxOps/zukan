import { useQuery } from '@tanstack/react-query'
import { api, call, type Schemas } from './client'

export type Game = Schemas['GameOut']
export type Me = Schemas['MeOut']

export const meQuery = {
  queryKey: ['me'],
  queryFn: () => call(api.GET('/api/auth/me')),
}

export function useMe() {
  return useQuery({
    ...meQuery,
    retry: false,
    // The layout shows it.
    meta: { inlineError: true },
    staleTime: 60_000,
  })
}

export function useGames() {
  return useQuery({
    queryKey: ['games'],
    queryFn: () => call(api.GET('/api/games')),
    staleTime: Infinity,
  })
}

export type GameGroup = { id: string; name: string; games: Game[] }

/** Games of one family split by market (Pokémon TCG / Asia / China) as one group, in the
 * order the server lists them; other games are a group of their own. */
export function gameGroups(games: Game[]): GameGroup[] {
  const groups = new Map<string, GameGroup>()
  for (const g of games) {
    const group = groups.get(g.group) ?? { id: g.group, name: g.group_name, games: [] }
    group.games.push(g)
    groups.set(g.group, group)
  }
  return [...groups.values()].map((group) =>
    group.games.length > 1 ? group : { ...group, name: group.games[0].name },
  )
}

export function useGame(gameId: string | null | undefined): Game | undefined {
  const { data } = useGames()
  return data?.find((g) => g.id === gameId)
}

export function useSets(gameId: string | null | undefined) {
  return useQuery({
    queryKey: ['sets', gameId],
    queryFn: () =>
      call(api.GET('/api/games/{game_id}/sets', { params: { path: { game_id: gameId! } } })),
    enabled: !!gameId,
    staleTime: 10 * 60_000,
  })
}

export function useHealth() {
  return useQuery({
    queryKey: ['health'],
    queryFn: () => call(api.GET('/api/health')),
    // Also tells when maintenance starts and ends (catalog refresh slowing the server).
    refetchInterval: 15_000,
  })
}

/** Latest Android app on GitHub; undefined data while loading or when there is none. */
export function useAndroidRelease() {
  return useQuery({
    queryKey: ['android-release'],
    queryFn: async () => {
      const { data, response } = await api.GET('/api/app/android')
      // No release (or GitHub unreachable): nothing to offer, not an error.
      return response.ok && data ? data : null
    },
    staleTime: 60 * 60_000,
    retry: false,
  })
}

export function useProviders() {
  return useQuery({
    queryKey: ['providers'],
    queryFn: () => call(api.GET('/api/auth/providers')),
    staleTime: Infinity,
  })
}
