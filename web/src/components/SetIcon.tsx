import { smallIcon } from '../lib/icons'

/** A set's symbol. Magic's (Scryfall) are black on transparent: turned light on the dark
 * theme (`zukan-ink`); other games' are in color and stay as they are. `small`: up to
 * 32 CSS px, the 64 px copy is enough. */
export function SetIcon({ src, game, className = '', small = false }: { src: string; game: string; className?: string; small?: boolean }) {
  return (
    <img
      src={small ? smallIcon(src) : src}
      alt=""
      loading="lazy"
      decoding="async"
      className={`object-contain ${game === 'mtg' ? 'zukan-ink' : ''} ${className}`}
      onError={(e) => (e.currentTarget.style.display = 'none')}
    />
  )
}
