import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useToast } from '../components/toast'
import { api, call, type Schemas } from './client'
import { t } from '../i18n'

export type AdjustIn = Schemas['AdjustIn']

/** Queries showing stock or value, refreshed after any stock change. */
export function useInvalidateStock() {
  const client = useQueryClient()
  return () =>
    Promise.all(
      ['card', 'collection', 'value', 'transactions'].map((key) =>
        client.invalidateQueries({ queryKey: [key] }),
      ),
    )
}

/** Add/remove copies, with a toast offering to undo the change. */
export function useAdjust() {
  const toast = useToast()
  const invalidate = useInvalidateStock()
  const undo = useMutation({
    mutationFn: (transactionId: number) =>
      call(
        api.POST('/api/collection/transactions/{transaction_id}/undo', {
          params: { path: { transaction_id: transactionId } },
        }),
      ),
    onSuccess: () => {
      toast(t('Change undone'), 'info')
      return invalidate()
    },
    onError: (e) => toast(e.message, 'error'),
  })
  return useMutation({
    mutationFn: (body: AdjustIn) => call(api.POST('/api/collection/adjust', { body })),
    onSuccess: (result, body) => {
      const vars = { n: Math.abs(body.delta), name: result.item.name, total: result.item.quantity }
      const text = body.delta > 0 ? t('Added {n} × {name} (now {total})', vars) : t('Removed {n} × {name} (now {total})', vars)
      toast(text, 'success', {
        label: t('Undo'),
        run: () => undo.mutate(result.transaction_id),
      })
      return invalidate()
    },
    onError: (e) => toast(e.message, 'error'),
  })
}
