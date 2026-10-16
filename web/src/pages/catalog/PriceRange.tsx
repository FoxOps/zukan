import { formatMoney } from '../../lib/format'
import type { Card } from './types'

export function PriceRange({ card }: { card: Card }) {
  if (card.price_min === null) return null
  const currency = card.currency ?? undefined
  return (
    <>
      {card.price_min === card.price_max
        ? formatMoney(card.price_min, currency)
        : `${formatMoney(card.price_min, currency)} - ${formatMoney(card.price_max, currency)}`}
    </>
  )
}

