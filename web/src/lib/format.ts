import type { Game } from '../api/queries'
import i18n, { currentLanguage } from '../i18n'

// Formatters follow the interface language.
function formatters() {
  const locale = currentLanguage()
  return {
    money: new Map<string, Intl.NumberFormat>(),
    day: new Intl.DateTimeFormat(locale, { dateStyle: 'medium' }),
    moment: new Intl.DateTimeFormat(locale, { dateStyle: 'short', timeStyle: 'short' }),
    languages: new Intl.DisplayNames([locale], { type: 'language' }),
  }
}
let cache: { lang: string; value: ReturnType<typeof formatters> } | null = null
function format() {
  if (cache?.lang !== currentLanguage()) cache = { lang: currentLanguage(), value: formatters() }
  return cache.value
}

/** API decimals arrive as strings ("12.50"). Currency: ISO code of the price source. */
export function formatMoney(value: string | number | null | undefined, currency = 'EUR'): string {
  if (value === null || value === undefined || value === '') return '—'
  const { money } = format()
  let formatter = money.get(currency)
  if (!formatter) {
    formatter = new Intl.NumberFormat(currentLanguage(), { style: 'currency', currency })
    money.set(currency, formatter)
  }
  return formatter.format(Number(value))
}

export function formatDate(value: string | null | undefined): string {
  return value ? format().day.format(new Date(value)) : '—'
}

export function formatDateTime(value: string | null | undefined): string {
  return value ? format().moment.format(new Date(value)) : '—'
}

export function languageName(code: string): string {
  try {
    const name = format().languages.of(code) ?? code
    return name.charAt(0).toLocaleUpperCase(currentLanguage()) + name.slice(1)
  } catch {
    return code
  }
}

/** Cardmarket grading scale, with Cardmarket's badge colors. */
export const CONDITIONS = [
  { code: 'MT', name: 'Mint', color: '#17a2b8' },
  { code: 'NM', name: 'Near Mint', color: '#3caf56' },
  { code: 'EX', name: 'Excellent', color: '#82891e' },
  { code: 'GD', name: 'Good', color: '#ffc107' },
  { code: 'LP', name: 'Light Played', color: '#fd8b2b' },
  { code: 'PL', name: 'Played', color: '#e56874' },
  { code: 'PO', name: 'Poor', color: '#dc3545' },
] as const

/** Cardmarket page of a product, in the interface language (Cardmarket redirects the
 * product id to the product page). */
/** Finish name from the game plugin, translated when the dictionary knows it. */
export function finishName(game: Game | undefined, code: string): string {
  return i18n.t(game?.finishes.find((f) => f.code === code)?.name ?? code)
}

export function conditionName(code: string): string {
  const condition = CONDITIONS.find((c) => c.code === code)
  return condition ? i18n.t(condition.name) : code
}

/** Country whose flag stands for a card language. */
export const LANGUAGE_FLAGS: Record<string, string> = {
  en: 'gb',
  fr: 'fr',
  de: 'de',
  it: 'it',
  es: 'es',
  pt: 'pt',
  ja: 'jp',
  ko: 'kr',
  'zh-hans': 'cn',
  'zh-hant': 'tw',
  ru: 'ru',
}

/** Lower case without accents, to filter lists the way the catalog search works. */
export function normalize(text: string): string {
  return text.normalize('NFKD').replace(/\p{M}/gu, '').toLowerCase()
}
