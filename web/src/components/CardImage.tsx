import { useState } from 'react'

type Props = { src: string | null | undefined; back?: string | null; alt: string; className?: string }

/** Card picture at card proportions. Double-faced cards flip in 3D when clicked. */
export function CardImage({ src, back, alt, className = '' }: Props) {
  const [flipped, setFlipped] = useState(false)
  const [failed, setFailed] = useState(false)
  const face = (url: string | null | undefined, label: string, extra = '') =>
    url && !failed ? (
      <img
        src={url}
        alt={label}
        loading="lazy"
        onError={() => setFailed(true)}
        className={`absolute inset-0 h-full w-full rounded-[4.5%] object-cover backface-hidden ${extra}`}
      />
    ) : (
      <div
        className={`absolute inset-0 flex items-center justify-center rounded-[4.5%] bg-base-300 p-2 text-center text-sm text-base-content/60 backface-hidden ${extra}`}
      >
        {alt}
      </div>
    )

  return (
    <div className={`perspective-distant aspect-[63/88] ${className}`}>
      <div
        className={`relative h-full w-full transition-transform duration-500 transform-3d ${flipped ? 'rotate-y-180' : ''} ${back ? 'cursor-pointer' : ''}`}
        onClick={() => back && setFlipped((f) => !f)}
        title={back ? 'Click to flip' : undefined}
      >
        {face(src, alt)}
        {back && face(back, `${alt} (back)`, 'rotate-y-180')}
      </div>
    </div>
  )
}
