import { useState, type MouseEvent } from 'react'
import { useTranslation } from 'react-i18next'
import { Logo } from './Logo'

type Props = {
  src: string | null | undefined
  back?: string | null
  alt: string
  className?: string
  // Classes of the picture only, not of the flip button (hover lift on tiles: a button
  // moving under the pointer turns its click into a click on the tile link).
  faceClassName?: string
  // Clicking the picture flips it too (card page). Off where the picture is a link.
  flipOnClick?: boolean
  // Picture wider than tall (Riftbound battlefields): turned a quarter to fill the
  // portrait frame instead of being cropped.
  landscape?: boolean
  // Shown on the placeholder when there is no picture.
  game?: string
  setCode?: string | null
  number?: string | null
}

// Frame color of the placeholder, per game family (the part of the id before "-").
const GAME_TINTS: Record<string, string> = {
  mtg: '#8a5a2b',
  pokemon: '#c8423a',
  yugioh: '#6b4aa0',
  sorcery: '#5b6b78',
  lorcana: '#3a6fb0',
  riftbound: '#2e8a8a',
}

/** Stand-in for a missing picture: a card back in the game's color with the Zukan mark,
 * the card's name, set and number (text hidden on thumbnails too small to read it). */
export function CardPlaceholder({ name, game, setCode, number, className = '' }: { name: string; game?: string; setCode?: string | null; number?: string | null; className?: string }) {
  const { t } = useTranslation()
  const tint = GAME_TINTS[game?.split('-')[0] ?? ''] ?? 'var(--color-neutral)'
  const where = [setCode, number].filter(Boolean).join(' · ')
  return (
    <div
      className={`@container absolute inset-0 flex flex-col gap-[4%] rounded-[4.5%] p-[5%] text-left shadow-inner ${className}`}
      style={{ backgroundColor: tint }}
      role="img"
      aria-label={name ? `${name} (${t('No picture')})` : t('No picture')}
    >
      <div className="flex min-h-0 flex-1 items-center justify-center rounded-[6%] bg-base-200/95 p-[10%] ring-2 ring-white/40">
        <Logo className="max-h-full w-full object-contain opacity-80" />
      </div>
      <div className="hidden min-w-0 text-white @[7rem]:block">
        {name && <div className="line-clamp-2 text-xs font-semibold leading-tight @[12rem]:text-sm">{name}</div>}
        {where && <div className="truncate text-[0.65rem] opacity-85 @[12rem]:text-xs">{where}</div>}
        <div className="text-[0.6rem] uppercase tracking-wide opacity-70">{t('No picture')}</div>
      </div>
    </div>
  )
}

/** Two circular arrows around a card: "turn this card over". */
export function FlipIcon({ className = 'h-4 w-4' }: { className?: string }) {
  return (
    <svg viewBox="0 0 24 24" className={`fill-none stroke-current stroke-2 ${className}`} strokeLinecap="round" strokeLinejoin="round" aria-hidden>
      <rect x="8.5" y="7" width="7" height="10" rx="1.2" />
      <path d="M3.5 11a8.5 8.5 0 0 1 14.6-5.4" />
      <path d="M18.5 2.5v3.6h-3.6" />
      <path d="M20.5 13a8.5 8.5 0 0 1-14.6 5.4" />
      <path d="M5.5 21.5v-3.6h3.6" />
    </svg>
  )
}

// A landscape picture as wide as the frame is tall (88/63) and as tall as it is wide (63/88),
// centered then turned a quarter clockwise.
const TURNED = 'left-1/2 top-1/2 h-[71.59%] w-[139.68%] max-w-none -translate-x-1/2 -translate-y-1/2 rotate-90'

/** Card picture at card proportions. Double-faced cards get a flip button (3D turn). */
export function CardImage({ src, back, alt, className = '', faceClassName = '', flipOnClick = false, landscape = false, game, setCode, number }: Props) {
  const { t } = useTranslation()
  const [flipped, setFlipped] = useState(false)
  // The back is only downloaded once someone asks for it.
  const [backWanted, setBackWanted] = useState(false)
  const [failed, setFailed] = useState(false)
  const flip = () => {
    setBackWanted(true)
    setFlipped((f) => !f)
  }
  const onButton = (e: MouseEvent) => {
    // Inside a link (catalog tiles): turn the card, do not open its page.
    e.preventDefault()
    e.stopPropagation()
    flip()
  }
  // Own compositing layers (backface-hidden) only when the card can turn: they kept a
  // stale dimmed paint after list reloads in Chrome.
  const turnable = back ? 'backface-hidden' : ''
  const face = (url: string | null | undefined, label: string, extra = '') =>
    url && !failed ? (
      <img
        src={url}
        alt={label}
        loading="lazy"
        onError={() => setFailed(true)}
        className={`absolute rounded-[4.5%] object-cover ${landscape ? TURNED : 'inset-0 h-full w-full'} ${turnable} ${extra}`}
      />
    ) : (
      <CardPlaceholder name={label} game={game} setCode={setCode} number={number} className={`${turnable} ${extra}`} />
    )
  const label = flipped ? t('Show front') : t('Show back')

  return (
    <div className={`relative aspect-[63/88] ${className}`}>
      <div className={`h-full w-full perspective-distant ${faceClassName}`}>
        <div
          className={`relative h-full w-full ${back ? 'transition-transform duration-500 transform-3d' : ''} ${flipped ? 'rotate-y-180' : ''} ${back && flipOnClick ? 'cursor-pointer' : ''}`}
          onClick={back && flipOnClick ? flip : undefined}
        >
          {face(src, alt)}
          {back && backWanted && face(back, `${alt} (${t('back')})`, 'rotate-y-180')}
        </div>
      </div>
      {back && (
        <button
          type="button"
          className="btn btn-circle btn-sm absolute bottom-[3%] right-[3%] border-base-300 bg-base-100/85 shadow-md backdrop-blur-sm hover:bg-base-100"
          onClick={onButton}
          aria-label={label}
          aria-pressed={flipped}
          title={label}
        >
          <FlipIcon className={`h-4 w-4 transition-transform duration-500 ${flipped ? 'rotate-180' : ''}`} />
        </button>
      )}
    </div>
  )
}
