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
    staleTime: Infinity,
  })
}

export function useProviders() {
  return useQuery({
    queryKey: ['providers'],
    queryFn: () => call(api.GET('/api/auth/providers')),
    staleTime: Infinity,
  })
}
