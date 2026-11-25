import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api, call, type Schemas } from './client'

export type ShoppingList = Schemas['ShoppingListOut']
export type ShoppingDetail = Schemas['ShoppingListDetailOut']
export type ShoppingItem = Schemas['ShoppingItemOut']
export type ShoppingSync = Schemas['ShoppingSyncOut']

export const SHOPPING_FORMATS = ['txt', 'md', 'pdf'] as const

/** The user's shopping lists (every user: no module needed). */
export function useShoppingLists(enabled = true) {
  return useQuery({
    queryKey: ['shopping-lists'],
    enabled,
    queryFn: () => call(api.GET('/api/shopping-lists')),
  })
}

export function useShoppingList(id: number) {
  return useQuery({
    queryKey: ['shopping-list', id],
    meta: { inlineError: true },
    queryFn: () => call(api.GET('/api/shopping-lists/{list_id}', { params: { path: { list_id: id } } })),
  })
}

/** Keeps the list page and the lists overview in step after a change. */
export function useShoppingCache() {
  const client = useQueryClient()
  return (detail: ShoppingDetail | null, removedId?: number) => {
    if (detail) client.setQueryData(['shopping-list', detail.id], detail)
    if (removedId !== undefined) client.removeQueries({ queryKey: ['shopping-list', removedId] })
    return client.invalidateQueries({ queryKey: ['shopping-lists'] })
  }
}

/** Edits of one list's items: tick copies, change copies or editions, add, remove. */
export function useShoppingEdits(listId: number, onError: (error: Error) => void) {
  const update = useShoppingCache()
  const path = { list_id: listId }
  const patch = useMutation({
    mutationFn: ({ itemId, body }: { itemId: number; body: Schemas['ShoppingItemIn'] }) =>
      call(api.PATCH('/api/shopping-lists/{list_id}/items/{item_id}', { params: { path: { ...path, item_id: itemId } }, body })),
    onSuccess: (detail) => update(detail),
    onError,
  })
  const add = useMutation({
    mutationFn: (body: Schemas['ShoppingItemAddIn']) => call(api.POST('/api/shopping-lists/{list_id}/items', { params: { path }, body })),
    onSuccess: (detail) => update(detail),
    onError,
  })
  const remove = useMutation({
    mutationFn: (itemId: number) => call(api.DELETE('/api/shopping-lists/{list_id}/items/{item_id}', { params: { path: { ...path, item_id: itemId } } })),
    onSuccess: (detail) => update(detail),
    onError,
  })
  const rename = useMutation({
    mutationFn: (name: string) => call(api.PATCH('/api/shopping-lists/{list_id}', { params: { path }, body: { name } })),
    onSuccess: (detail) => update(detail),
    onError,
  })
  return { patch, add, remove, rename }
}

/** "M10 146 / 2X2 117", empty for any edition. */
export function editionsLabel(item: Pick<ShoppingItem, 'editions'>): string {
  return item.editions
    .map((e) => [e.set_code, e.collector_number].filter(Boolean).join(' '))
    .filter(Boolean)
    .join(' / ')
}
