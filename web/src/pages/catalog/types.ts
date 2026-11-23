import type { ComponentType } from 'react'
import type { Schemas } from '../../api/client'
import type { Game } from '../../api/queries'
import type { ViewChoice } from '../../lib/views'

export type Card = Schemas['CardSummaryOut']

/** What every catalog view gets: one page of cards. */
export type CatalogViewProps = {
  cards: Card[]
  games: Game[]
  // Several games listed: say which one each card belongs to.
  showGame: boolean
  // Opens the stock dialog of a card; `adding`: the card whose versions are loading.
  add: (card: Card) => void
  adding: number | null
}

export type CatalogView = ViewChoice & { component: ComponentType<CatalogViewProps> }

export const cardLink = (card: Card) => (card.printing_id ? `/cards/${card.id}/${card.printing_id}` : `/cards/${card.id}`)
