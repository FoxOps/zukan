import { gridIcon, listIcon } from '../../lib/views'
import { ImageView } from './ImageView'
import { ListView } from './ListView'
import type { CatalogView } from './types'

/** Available views, the first is the default. A new view is one more entry here. */
export const CATALOG_VIEWS: CatalogView[] = [
  { id: 'images', label: 'Images', icon: gridIcon, component: ImageView },
  { id: 'list', label: 'List', icon: listIcon, component: ListView },
]
