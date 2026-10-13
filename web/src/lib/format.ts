const locale = navigator.language || 'en'

const money = new Intl.NumberFormat(locale, { style: 'currency', currency: 'EUR' })
const day = new Intl.DateTimeFormat(locale, { dateStyle: 'medium' })
const moment = new Intl.DateTimeFormat(locale, { dateStyle: 'short', timeStyle: 'short' })

/** API decimals arrive as strings ("12.50"). */
export function formatMoney(value: string | number | null | undefined): string {
  if (value === null || value === undefined || value === '') return '—'
  return money.format(Number(value))
}

export function formatDate(value: string | null | undefined): string {
  return value ? day.format(new Date(value)) : '—'
}

export function formatDateTime(value: string | null | undefined): string {
  return value ? moment.format(new Date(value)) : '—'
}

const languageNames = new Intl.DisplayNames([locale], { type: 'language' })

export function languageName(code: string): string {
  try {
    return languageNames.of(code) ?? code
  } catch {
    return code
  }
}

export const CONDITIONS = [
  { code: 'MT', name: 'Mint' },
  { code: 'NM', name: 'Near Mint' },
  { code: 'EX', name: 'Excellent' },
  { code: 'GD', name: 'Good' },
  { code: 'LP', name: 'Light Played' },
  { code: 'PL', name: 'Played' },
  { code: 'PO', name: 'Poor' },
] as const
