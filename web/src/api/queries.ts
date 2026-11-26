import { useEffect, useState } from 'react'
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

/** The games the user chose to show (Settings, `catalog_games`; none chosen: all), for
 * every page listing games or their data. Admin pages, About and Settings keep `useGames`. */
export function useShownGames() {
  const { data: games = [] } = useGames()
  const { data: me } = useMe()
  const chosen = me?.catalog_games
  const isShown = (gameId: string) => !chosen || chosen.includes(gameId)
  const shown = chosen ? games.filter((g) => chosen.includes(g.id)) : games
  return { games, shown, isShown, filtered: shown.length < games.length }
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

/** A game's name, with its market when its family is split ("Pokémon TCG · Asia");
 * `t` translates the market. */
export function gameLabel(group: GameGroup, game: Game, t: (text: string) => string): string {
  return group.games.length > 1 ? `${group.name} · ${t(game.region_label ?? game.name)}` : game.name
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
    // Kept as long as it is fresh, also while no page shows it.
    gcTime: 10 * 60_000,
  })
}

/** `base` ms doubled per failure up to `max`, ±20 % (no jitter without failures). */
export function backoff(base: number, failures: number, max: number): number {
  if (failures === 0) return base
  return Math.min(base * 2 ** failures, max) * (0.8 + Math.random() * 0.4)
}

// Health checks failed in a row (reset by an answer).
let healthFailures = 0

export function useHealth() {
  return useQuery({
    queryKey: ['health'],
    queryFn: async () => {
      try {
        const health = await call(api.GET('/api/health'))
        healthFailures = 0
        return health
      } catch (e) {
        healthFailures += 1
        throw e
      }
    },
    // Also tells when maintenance starts and ends (catalog refresh slowing the server).
    // Server not answering: checked less and less often (30 s, then every minute), with
    // jitter so open tabs do not all ask at once.
    refetchInterval: () => backoff(15_000, healthFailures, 60_000),
  })
}

/** Latest Android app on GitHub; undefined data while loading or when there is none. */
/** True once the browser is idle after the first render (at most 2 s later): secondary
 * requests wait for the page's own. */
function useIdle(): boolean {
  const [idle, setIdle] = useState(false)
  useEffect(() => {
    if (typeof requestIdleCallback === 'function') {
      const id = requestIdleCallback(() => setIdle(true), { timeout: 2000 })
      return () => cancelIdleCallback(id)
    }
    const id = setTimeout(() => setIdle(true), 1000)
    return () => clearTimeout(id)
  }, [])
  return idle
}

export function useAndroidRelease() {
  // Only the menu's download link uses it: asked once the page has what it needs.
  const idle = useIdle()
  return useQuery({
    queryKey: ['android-release'],
    enabled: idle,
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

export type Binder = Schemas['BinderOut']

/** Sets followed in the Binder module, with their progress. */
export function useBinders(enabled = true) {
  return useQuery({
    queryKey: ['binder'],
    queryFn: () => call(api.GET('/api/binder')),
    enabled,
  })
}

export function useBinder(binderId: number, enabled = true) {
  return useQuery({
    queryKey: ['binder', binderId],
    queryFn: () => call(api.GET('/api/binder/{binder_id}', { params: { path: { binder_id: binderId } } })),
    enabled,
  })
}

export type Deck = Schemas['DeckOut']
export type DeckDetail = Schemas['DeckDetailOut']

/** Decks of the Decks module, last changed first. */
export function useDecks(enabled = true) {
  return useQuery({
    queryKey: ['decks'],
    queryFn: () => call(api.GET('/api/decks')),
    enabled,
  })
}

export function useDeck(deckId: number, enabled = true) {
  return useQuery({
    queryKey: ['decks', deckId],
    queryFn: () => call(api.GET('/api/decks/{deck_id}', { params: { path: { deck_id: deckId } } })),
    enabled,
  })
}

/** Games and formats decks can be built for. */
export function useDeckFormats(enabled = true) {
  return useQuery({
    queryKey: ['deck-formats'],
    queryFn: () => call(api.GET('/api/decks/formats')),
    staleTime: Infinity,
    enabled,
  })
}
