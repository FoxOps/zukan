import type { ReactNode } from 'react'
import { useUrlState } from './hooks'

export const listIcon = (
  <svg viewBox="0 0 24 24" className="h-4 w-4 fill-none stroke-current stroke-2" aria-hidden>
    <path d="M8 6h13M8 12h13M8 18h13M3 6h.01M3 12h.01M3 18h.01" strokeLinecap="round" />
  </svg>
)
export const gridIcon = (
  <svg viewBox="0 0 24 24" className="h-4 w-4 fill-none stroke-current stroke-2" aria-hidden>
    <rect x="3" y="3" width="7" height="9" rx="1" />
    <rect x="14" y="3" width="7" height="9" rx="1" />
    <rect x="3" y="14" width="7" height="7" rx="1" />
    <rect x="14" y="14" width="7" height="7" rx="1" />
  </svg>
)

/** A way to show a page of results (list, pictures...), see `ViewToggle`. */
export type ViewChoice = {
  id: string
  // Translated label (natural language key).
  label: string
  icon: ReactNode
}

function saved(key: string): string | null {
  try {
    return localStorage.getItem(key)
  } catch {
    return null
  }
}

/** View in the URL (`?view=`), else the last one used on this browser (`storageKey`),
 * else the first of `views`. */
export function useView<V extends ViewChoice>(views: V[], storageKey: string): [V, (id: string) => void] {
  const url = useUrlState()
  const view = views.find((v) => v.id === (url.get('view') || saved(storageKey))) ?? views[0]
  const choose = (id: string) => {
    try {
      localStorage.setItem(storageKey, id)
    } catch {
      // Storage refused: the URL still keeps it.
    }
    url.set({ view: id }, false)
  }
  return [view, choose]
}
