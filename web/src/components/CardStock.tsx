import { useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { api, call, type Schemas } from '../api/client'
import { useGames } from '../api/queries'
import { StockDialog, type StockTarget } from './StockDialog'
import { showError } from './toast'

type Card = Pick<Schemas['CardSummaryOut'], 'id' | 'game_id' | 'printing_id'>

/** "Add copies" from a card of a list: loads the card's versions, then opens the stock
 * dialog on the version shown (the others can be picked in the dialog). */
export function useCardStock() {
  const client = useQueryClient()
  const { data: games = [] } = useGames()
  const [target, setTarget] = useState<{ target: StockTarget; versions: StockTarget[]; game: string } | null>(null)
  const [loading, setLoading] = useState<number | null>(null)

  const add = async (card: Card) => {
    setLoading(card.id)
    try {
      const full = await client.fetchQuery({
        queryKey: ['card', card.id],
        queryFn: () => call(api.GET('/api/cards/{card_id}', { params: { path: { card_id: card.id } } })),
      })
      const versions = full.printings.map((p) => ({
        printingId: p.id,
        title: `${p.name || full.name} - ${p.set.code} ${p.collector_number ?? ''}`,
        finishes: p.finishes,
        languages: p.languages,
        label: `${p.set.code} ${p.collector_number ?? ''} · ${p.set.name}${p.set.release_date ? ` (${p.set.release_date.slice(0, 4)})` : ''}`,
      }))
      const shown = versions.find((v) => v.printingId === card.printing_id) ?? versions[0]
      if (shown) setTarget({ target: shown, versions, game: card.game_id })
    } catch (e) {
      showError((e as Error).message)
    } finally {
      setLoading(null)
    }
  }

  const dialog = (
    <StockDialog
      game={games.find((g) => g.id === target?.game)}
      target={target?.target ?? null}
      versions={target?.versions ?? []}
      onClose={() => setTarget(null)}
    />
  )
  return { add, loading, dialog }
}
