/** Internal provider fields not worth showing. */
export const HIDDEN = new Set([
  'slugs', 'scryfall_id', 'cardmarket_id', 'market_ids', 'back_image_url', 'back',
  // Data bookkeeping, and Riftbound domains (shown as color symbols).
  'finishes_guessed', 'finishes_confirmed', 'languages_guessed', 'domains',
  // Yu-Gi-Oh! ids and frame (shown by the card type).
  'konami_id', 'frame',
  // Codes printed per language (shown next to the collector number).
  'numbers',
])

export function hasVisibleAttributes(data: Record<string, unknown>): boolean {
  return Object.entries(data).some(([k, v]) => !HIDDEN.has(k) && v !== null && v !== '')
}

/** Attributes holding a card's legality, per game (shown by `Legality`):
 * - `legalities` (Magic, Lorcana): format → "legal" | "restricted" | "banned" | "not_legal"
 * - `legal` (Pokémon printings): format → true / false
 * - `banlist` (Yu-Gi-Oh!): list → "Forbidden" | "Limited" | "Semi-Limited", a list left out
 *   means unlimited there. */
export const LEGALITY_KEYS = ['legalities', 'legal', 'banlist'] as const
