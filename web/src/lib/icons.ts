/** Link to the 64 px copy of an API pictogram (set symbol, rarity, color, text symbol):
 * bitmap symbols are often 150 px or more for a 16-32 CSS px slot. SVG ones come back
 * unchanged. Other links are left as they are. */
export function smallIcon(url: string): string
export function smallIcon(url: string | null | undefined): string | null | undefined
export function smallIcon(url: string | null | undefined): string | null | undefined {
  if (!url || !url.startsWith('/api/') || url.includes('size=')) return url
  return `${url}${url.includes('?') ? '&' : '?'}size=small`
}
