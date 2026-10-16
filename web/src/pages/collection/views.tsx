import { gridIcon, listIcon } from '../../lib/views'
import { ImageView } from './ImageView'
import { ListView } from './ListView'
import type { CollectionView } from './types'

/** Available views, the first is the default. A new view is one more entry here. */
export const COLLECTION_VIEWS: CollectionView[] = [
  { id: 'list', label: 'List', icon: listIcon, component: ListView },
  { id: 'images', label: 'Images', icon: gridIcon, component: ImageView },
]
