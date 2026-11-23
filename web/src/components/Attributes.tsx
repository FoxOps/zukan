// Game-specific card data is free-form JSON from the game plugin; it is rendered
// generically so a new game needs no UI change. Symbol tokens ("{2}{R}") show as the
// game's pictograms; an `<attribute>_symbols` value (the text with tokens) is shown in
// place of its plain attribute.

import { Fragment, type ReactNode } from 'react'
import { useTranslation } from 'react-i18next'
import type { Game } from '../api/queries'
import { HIDDEN, LEGALITY_KEYS } from '../lib/attributes'
import { Legality } from './Legality'
import { costSymbols, thresholdSymbols } from '../lib/symbols'
import { SymbolText } from './SymbolText'

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

const SYMBOLS = '_symbols'

/** An object's fields, with `<key>_symbols` taking the place of `<key>`. */
function withSymbols<T>(data: Record<string, T>): [string, T][] {
  return Object.entries(data)
    .filter(([k]) => !k.endsWith(SYMBOLS))
    .map(([k, v]) => [k, data[k + SYMBOLS] ?? v])
}

function inline(v: Value, game?: Game, key?: string): ReactNode {
  if (typeof v === 'string') return <SymbolText game={game} text={v} />
  if (isScalar(v)) return String(v)
  if (Array.isArray(v)) {
    // Costs as color names (Pokémon attacks: ["Fire", "Colorless"]).
    if (key === 'cost' && v.every((x) => typeof x === 'string')) {
      const symbols = costSymbols(game, v as string[])
      if (symbols) return symbols
    }
    return v.map((x, i) => (
      <Fragment key={i}>
        {i > 0 && ', '}
        {inline(x, game)}
      </Fragment>
    ))
  }
  if (v && typeof v === 'object') {
    if (key === 'thresholds') {
      const symbols = thresholdSymbols(game, v)
      if (symbols) return symbols
    }
    return withSymbols(v)
      .filter(([, x]) => x !== null && x !== '' && x !== 0)
      .map(([k, x], i) => (
        <Fragment key={k}>
          {i > 0 && ' · '}
          {label(k)} {inline(x, game, k)}
        </Fragment>
      ))
  }
  return ''
}

export function Attributes({ data, game }: { data: Record<string, unknown>; game?: Game }) {
  const { t } = useTranslation()
  const legality = LEGALITY_KEYS.filter((k) => data[k] && typeof data[k] === 'object')
  const entries = withSymbols(data as Record<string, Value>).filter(
    ([k, v]) =>
      !HIDDEN.has(k) &&
      !(LEGALITY_KEYS as readonly string[]).includes(k) &&
      v !== null &&
      v !== '' &&
      !(Array.isArray(v) && v.length === 0),
  )
  const texts = entries.filter(([, v]) => typeof v === 'string' && v.length > 40)
  const facts = entries.filter(
    ([k, v]) => !texts.some(([t]) => t === k) && (isScalar(v) || (Array.isArray(v) && v.every(isScalar)) || k === 'thresholds'),
  )
  const lists = entries.filter(([k]) => !texts.some(([t]) => t === k) && !facts.some(([f]) => f === k))

  return (
    <div className="flex flex-col gap-3">
      {legality.map((k) => (
        <div key={k} className="flex flex-col gap-1.5">
          <div className="text-sm font-semibold">{t('Legality')}</div>
          <Legality attribute={k} value={data[k]} />
        </div>
      ))}
      {facts.length > 0 && (
        <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 text-sm">
          {facts.map(([k, v]) => (
            <div key={k} className="contents">
              <dt className="text-base-content/60">{label(k)}</dt>
              <dd>{inline(v, game, k)}</dd>
            </div>
          ))}
        </dl>
      )}
      {texts.map(([k, v]) => (
        <div key={k} className="prose prose-sm max-w-none whitespace-pre-line">
          <p>
            <SymbolText game={game} text={v as string} />
          </p>
        </div>
      ))}
      {lists.map(([k, v]) => (
        <div key={k}>
          <div className="mb-1 text-sm font-semibold">{label(k)}</div>
          {Array.isArray(v) ? (
            <ul className="list-inside list-disc text-sm">
              {v.map((item, i) => (
                <li key={i}>{inline(item, game)}</li>
              ))}
            </ul>
          ) : (
            <p className="text-sm">{inline(v, game, k)}</p>
          )}
        </div>
      ))}
    </div>
  )
}
