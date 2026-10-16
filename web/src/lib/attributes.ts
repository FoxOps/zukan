/** Internal provider fields not worth showing. */
export const HIDDEN = new Set([
  'slugs', 'scryfall_id', 'cardmarket_id', 'market_ids', 'back_image_url', 'back',
  // Data bookkeeping, and Riftbound domains (shown as color symbols).
  'finishes_guessed', 'finishes_confirmed', 'domains',
  // Yu-Gi-Oh! ids and frame (shown by the card type).
  'konami_id', 'frame',
])

export function hasVisibleAttributes(data: Record<string, unknown>): boolean {
  return Object.entries(data).some(([k, v]) => !HIDDEN.has(k) && v !== null && v !== '')
}
