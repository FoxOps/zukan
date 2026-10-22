import logoDark from '../assets/brand/logo-dark.webp'
import logo from '../assets/brand/logo.webp'
import mascot from '../assets/brand/mascot.webp'

/**
 * The Zukan signature: chocolate lettering on light backgrounds, cream lettering on dark ones.
 * `onDark` is for a panel that is dark whatever the theme, such as the sidebar.
 */
export function Logo({ className = '', onDark = false }: { className?: string; onDark?: boolean }) {
  if (onDark) return <img src={logoDark} alt="Zukan" className={className} />
  return (
    <>
      <img src={logo} alt="Zukan" className={`zukan-logo-light ${className}`} />
      <img src={logoDark} alt="Zukan" className={`zukan-logo-dark ${className}`} />
    </>
  )
}

export function Mascot({ className = '' }: { className?: string }) {
  return <img src={mascot} alt="" aria-hidden className={className} />
}
