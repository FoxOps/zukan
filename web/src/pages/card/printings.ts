import type { Schemas } from '../../api/client'

export type PrintingOut = Schemas['PrintingOut']

// Printing orders; the API order (owned first, then newest) is the default.
export const PRINTING_SORTS = {
  owned: 'Owned first',
  newest: 'Newest sets',
  oldest: 'Oldest sets',
  set: 'Set name',
  number: 'Collector number',
  price_desc: 'Price: high to low',
  price_asc: 'Price: low to high',
} as const
export type PrintingSort = keyof typeof PRINTING_SORTS

function lowestTrend(p: PrintingOut, source: string | undefined): number | null {
  const trends = p.prices.filter((x) => x.source === source && x.trend !== null).map((x) => Number(x.trend))
  return trends.length ? Math.min(...trends) : null
}

export function sortPrintings(printings: PrintingOut[], sort: PrintingSort, source: string | undefined): PrintingOut[] {
  const date = (p: PrintingOut) => p.set.release_date ?? ''
  const number = (a: PrintingOut, b: PrintingOut) =>
    (a.collector_number ?? '').localeCompare(b.collector_number ?? '', undefined, { numeric: true })
  // Printings without a price stay last in both price orders.
  const price = (a: PrintingOut, b: PrintingOut, sign: number) => {
    const x = lowestTrend(a, source)
    const y = lowestTrend(b, source)
    if (x === null || y === null) return (x === null ? 1 : 0) - (y === null ? 1 : 0)
    return sign * (x - y)
  }
  const compare: Record<PrintingSort, ((a: PrintingOut, b: PrintingOut) => number) | null> = {
    owned: null,
    newest: (a, b) => date(b).localeCompare(date(a)) || number(a, b),
    oldest: (a, b) => date(a).localeCompare(date(b)) || number(a, b),
    set: (a, b) => a.set.name.localeCompare(b.set.name) || number(a, b),
    number: (a, b) => number(a, b) || a.set.name.localeCompare(b.set.name),
    price_desc: (a, b) => price(a, b, -1),
    price_asc: (a, b) => price(a, b, 1),
  }
  const fn = compare[sort]
  return fn ? [...printings].sort(fn) : printings
}

/** Codes printed on the printing's other languages ("BETB-KR024" under "BETB-EN024"). */
export function regionNumbers(p: PrintingOut): Record<string, string> {
  const numbers = p.attributes.numbers
  return numbers && typeof numbers === 'object' ? (numbers as Record<string, string>) : {}
}
