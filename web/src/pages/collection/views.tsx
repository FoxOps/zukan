import { ImageView } from './ImageView'
import { ListView } from './ListView'
import type { CollectionView } from './types'

const listIcon = (
  <svg viewBox="0 0 24 24" className="h-4 w-4 fill-none stroke-current stroke-2" aria-hidden>
    <path d="M8 6h13M8 12h13M8 18h13M3 6h.01M3 12h.01M3 18h.01" strokeLinecap="round" />
  </svg>
)
const gridIcon = (
  <svg viewBox="0 0 24 24" className="h-4 w-4 fill-none stroke-current stroke-2" aria-hidden>
    <rect x="3" y="3" width="7" height="9" rx="1" />
    <rect x="14" y="3" width="7" height="9" rx="1" />
    <rect x="3" y="14" width="7" height="7" rx="1" />
    <rect x="14" y="14" width="7" height="7" rx="1" />
  </svg>
)

/** Available views, the first is the default. A new view is one more entry here. */
export const COLLECTION_VIEWS: CollectionView[] = [
  { id: 'list', label: 'List', icon: listIcon, component: ListView },
  { id: 'images', label: 'Images', icon: gridIcon, component: ImageView },
]
