/** A set's symbol. Magic's (Scryfall) are black on transparent: turned light on the dark
 * theme (`zukan-ink`); other games' are in color and stay as they are. */
export function SetIcon({ src, game, className = '' }: { src: string; game: string; className?: string }) {
  return (
    <img
      src={src}
      alt=""
      loading="lazy"
      className={`object-contain ${game === 'mtg' ? 'zukan-ink' : ''} ${className}`}
      onError={(e) => (e.currentTarget.style.display = 'none')}
    />
  )
}
