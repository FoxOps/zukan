import { useQuery } from '@tanstack/react-query'
import { api, call } from '../../api/client'

/** The six copies worth the most (the page's total is the number of collection items). */
export function useTopItems() {
  return useQuery({
    queryKey: ['collection', 'top'],
    queryFn: () => call(api.GET('/api/collection', { params: { query: { sort: 'price_desc', page_size: 6 } } })),
  })
}
