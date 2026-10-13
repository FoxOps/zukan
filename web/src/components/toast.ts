import { createContext, useContext } from 'react'

export type Kind = 'success' | 'error' | 'info'
export type ToastAction = { label: string; run: () => void }
export type ToastFn = (text: string, kind?: Kind, action?: ToastAction) => void

export const ToastContext = createContext<ToastFn>(() => {})

export function useToast() {
  return useContext(ToastContext)
}
