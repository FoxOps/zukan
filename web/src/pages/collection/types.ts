import type { ComponentType } from 'react'
import type { ViewChoice } from '../../lib/views'
import type { Schemas } from '../../api/client'
import type { Game } from '../../api/queries'

export type Item = Schemas['ItemOut']

/** What every collection view gets: one page of items and the actions on them. */
export type ViewProps = {
  items: Item[]
  games: Game[]
  // Several games listed: say which one each item belongs to.
  showGame: boolean
  busy: boolean
  step: (item: Item, delta: 1 | -1) => void
  edit: (item: Item) => void
}

export type CollectionView = ViewChoice & { component: ComponentType<ViewProps> }

export const itemLink = (item: Item) => `/cards/${item.card_id}/${item.printing_id}`
