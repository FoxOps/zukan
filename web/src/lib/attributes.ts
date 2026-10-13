/** Internal provider fields not worth showing. */
export const HIDDEN = new Set(['slugs', 'scryfall_id', 'cardmarket_id', 'back_image_url', 'back'])

export function hasVisibleAttributes(data: Record<string, unknown>): boolean {
  return Object.entries(data).some(([k, v]) => !HIDDEN.has(k) && v !== null && v !== '')
}
