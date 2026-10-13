// Game-specific card data is free-form JSON from the game plugin; it is rendered
// generically so a new game needs no UI change.

import { HIDDEN } from '../lib/attributes'

function label(key: string): string {
  return key
    .replace(/_/g, ' ')
    .replace(/([a-z])([A-Z])/g, '$1 $2')
    .replace(/^./, (c) => c.toUpperCase())
}

type Value = string | number | boolean | null | Value[] | { [key: string]: Value }

function isScalar(v: Value): v is string | number | boolean {
  return ['string', 'number', 'boolean'].includes(typeof v)
}

function inline(v: Value): string {
  if (isScalar(v)) return String(v)
  if (Array.isArray(v)) return v.map(inline).join(', ')
  if (v && typeof v === 'object')
    return Object.entries(v)
      .filter(([, x]) => x !== null && x !== '' && x !== 0)
      .map(([k, x]) => `${label(k)} ${inline(x)}`)
      .join(' · ')
  return ''
}

export function Attributes({ data }: { data: Record<string, unknown> }) {
  const entries = Object.entries(data as Record<string, Value>).filter(
    ([k, v]) => !HIDDEN.has(k) && v !== null && v !== '' && !(Array.isArray(v) && v.length === 0),
  )
  const texts = entries.filter(([, v]) => typeof v === 'string' && v.length > 40)
  const facts = entries.filter(([k, v]) => !texts.some(([t]) => t === k) && (isScalar(v) || (Array.isArray(v) && v.every(isScalar))))
  const lists = entries.filter(([k]) => !texts.some(([t]) => t === k) && !facts.some(([f]) => f === k))

  return (
    <div className="flex flex-col gap-3">
      {facts.length > 0 && (
        <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 text-sm">
          {facts.map(([k, v]) => (
            <div key={k} className="contents">
              <dt className="text-base-content/60">{label(k)}</dt>
              <dd>{inline(v)}</dd>
            </div>
          ))}
        </dl>
      )}
      {texts.map(([k, v]) => (
        <div key={k} className="prose prose-sm max-w-none whitespace-pre-line">
          <p>{v as string}</p>
        </div>
      ))}
      {lists.map(([k, v]) => (
        <div key={k}>
          <div className="mb-1 text-sm font-semibold">{label(k)}</div>
          {Array.isArray(v) ? (
            <ul className="list-inside list-disc text-sm">
              {v.map((item, i) => (
                <li key={i}>{inline(item)}</li>
              ))}
            </ul>
          ) : (
            <p className="text-sm">{inline(v)}</p>
          )}
        </div>
      ))}
    </div>
  )
}
