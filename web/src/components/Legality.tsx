import { useTranslation } from 'react-i18next'

// Yu-Gi-Oh! ban lists: always shown, green when the card is not on them.
const BANLISTS = ['tcg', 'ocg', 'goat']

type Status = 'legal' | 'restricted' | 'banned' | 'out'

const STYLE: Record<Status, { className: string; mark: string; label: string }> = {
  legal: { className: 'border-success bg-success/15 text-success', mark: '✓', label: 'Legal' },
  restricted: { className: 'border-warning bg-warning/15 text-warning', mark: '!', label: 'Restricted' },
  banned: { className: 'border-error bg-error/15 text-error', mark: '✕', label: 'Banned' },
  out: { className: 'border-error bg-error/15 text-error', mark: '✕', label: 'Not legal' },
}

function status(key: string, value: unknown): Status {
  if (key === 'legal') return value ? 'legal' : 'out'
  const text = String(value).toLowerCase()
  if (text === 'legal') return 'legal'
  if (['banned', 'forbidden'].includes(text)) return 'banned'
  if (['restricted', 'limited', 'semi-limited'].includes(text)) return 'restricted'
  return 'out'
}

// Format ids written as one word by the sources (Scryfall).
const FORMAT_NAMES: Record<string, string> = {
  paupercommander: 'Pauper Commander',
  competitivebrawl: 'Competitive Brawl',
  standardbrawl: 'Standard Brawl',
  historicbrawl: 'Historic Brawl',
  oldschool: 'Old School',
  predh: 'PreDH',
  tlr: 'TLR',
}

function formatName(format: string): string {
  // Ban lists are acronyms (TCG, OCG, GOAT); formats are words ("pauper_commander").
  if (BANLISTS.includes(format)) return format.toUpperCase()
  if (FORMAT_NAMES[format]) return FORMAT_NAMES[format]
  return format.replace(/_/g, ' ').replace(/^./, (c) => c.toUpperCase())
}

/** One badge per format: green legal, orange restricted / limited, red banned / forbidden,
 * red too when not legal there. A mark and the tooltip say it without color too. */
export function Legality({ attribute, value }: { attribute: string; value: unknown }) {
  const { t } = useTranslation()
  if (!value || typeof value !== 'object') return null
  const entries: [string, Status, string][] =
    attribute === 'banlist'
      ? BANLISTS.map((list) => {
          const listed = (value as Record<string, unknown>)[list]
          return [list, listed ? status(attribute, listed) : 'legal', listed ? String(listed) : STYLE.legal.label]
        })
      : Object.entries(value as Record<string, unknown>).map(([format, v]) => {
          const s = status(attribute, v)
          return [format, s, attribute === 'legal' ? STYLE[s].label : String(v).replace(/_/g, ' ')]
        })
  if (!entries.length) return null
  return (
    <ul className="flex flex-wrap gap-1.5" aria-label={t('Legality')}>
      {entries.map(([format, s, text]) => (
        <li
          key={format}
          className={`inline-flex items-center gap-1 rounded-full border px-2.5 py-0.5 text-xs font-semibold ${STYLE[s].className}`}
          title={`${formatName(format)}: ${t(text.charAt(0).toUpperCase() + text.slice(1))}`}
        >
          <span aria-hidden>{STYLE[s].mark}</span>
          {formatName(format)}
          <span className="sr-only">: {t(STYLE[s].label)}</span>
        </li>
      ))}
    </ul>
  )
}
