import { useState, type MouseEvent } from 'react'
import { useTranslation } from 'react-i18next'

type Props = {
  src: string | null | undefined
  back?: string | null
  alt: string
  className?: string
  // Clicking the picture flips it too (card page). Off where the picture is a link.
  flipOnClick?: boolean
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

/** Card picture at card proportions. Double-faced cards get a flip button (3D turn). */
export function CardImage({ src, back, alt, className = '', flipOnClick = false }: Props) {
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
        className={`absolute inset-0 h-full w-full rounded-[4.5%] object-cover ${turnable} ${extra}`}
      />
    ) : (
      <div
        className={`absolute inset-0 flex items-center justify-center rounded-[4.5%] bg-base-300 p-2 text-center text-sm text-base-content/60 ${turnable} ${extra}`}
      >
        {alt}
      </div>
    )
  const label = flipped ? t('Show front') : t('Show back')

  return (
    <div className={`relative perspective-distant aspect-[63/88] ${className}`}>
      <div
        className={`relative h-full w-full ${back ? 'transition-transform duration-500 transform-3d' : ''} ${flipped ? 'rotate-y-180' : ''} ${back && flipOnClick ? 'cursor-pointer' : ''}`}
        onClick={back && flipOnClick ? flip : undefined}
      >
        {face(src, alt)}
        {back && backWanted && face(back, `${alt} (${t('back')})`, 'rotate-y-180')}
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
