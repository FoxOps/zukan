import createClient from 'openapi-fetch'
import i18n from '../i18n'
import type { components, paths } from './schema'

export type Schemas = components['schemas']

/** Raised for non-2xx responses, with FastAPI's `detail` as message. Status 0: the
 * server could not be reached. */
export class ApiError extends Error {
  status: number
  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

// Cookie-authenticated writes must carry this header (CSRF protection).
const CSRF = { 'X-TCG-CSRF': '1' }
const listeners = new Set<() => void>()

/** Called when the session cannot be refreshed (user must log in again). */
export function onSessionExpired(listener: () => void): () => void {
  listeners.add(listener)
  return () => {
    listeners.delete(listener)
  }
}

let refreshing: Promise<boolean> | null = null

function refreshSession(): Promise<boolean> {
  // One refresh at a time: concurrent 401s wait for the same rotation.
  refreshing ??= fetch('/api/auth/refresh', {
    method: 'POST',
    headers: { ...CSRF, 'Content-Type': 'application/json' },
    body: '{}',
  })
    .then((r) => r.ok)
    .catch(() => false)
    .finally(() => {
      refreshing = null
    })
  return refreshing
}

/** fetch with CSRF header and a silent token refresh on 401. */
export async function authFetch(input: Request): Promise<Response> {
  const request = new Request(input, { credentials: 'same-origin' })
  request.headers.set('X-TCG-CSRF', '1')
  const retry = request.clone()
  const response = await fetch(request)
  if (response.status !== 401 || new URL(request.url).pathname.startsWith('/api/auth/')) {
    return response
  }
  if (await refreshSession()) {
    return fetch(retry)
  }
  listeners.forEach((l) => l())
  return response
}

export const api = createClient<paths>({ baseUrl: '', fetch: authFetch })

type Result<T> = { data?: T; error?: unknown; response: Response }

/** Message for a status without explanation from the server, in the interface language. */
export function statusMessage(status: number): string {
  const t = i18n.t.bind(i18n)
  if (status === 0) return t('The server cannot be reached. Check your connection and try again.')
  if (status === 401) return t('Your session has expired. Please log in again.')
  if (status === 403) return t('You are not allowed to do this.')
  if (status === 404) return t('This item does not exist (anymore).')
  if (status === 413) return t('This file is too large.')
  if (status === 429) return t('Too many requests. Try again in a moment.')
  if (status === 502 || status === 503 || status === 504) return t('The server is unavailable. Try again in a moment.')
  if (status >= 500) return t('Server error. Try again later.')
  return t('Request failed ({{status}})', { status })
}

function message(error: unknown, status: number): string {
  const detail = (error as { detail?: unknown } | undefined)?.detail
  // Unexpected server errors carry a generic text: ours is translated.
  if (typeof detail === 'string' && !/^internal server error$/i.test(detail)) return detail
  if (Array.isArray(detail)) {
    // Validation errors: "field: problem".
    return detail
      .map((d) => {
        const { msg, loc } = d as { msg?: string; loc?: unknown[] }
        const field = Array.isArray(loc) ? loc.filter((part) => part !== 'body' && part !== 'query').join('.') : ''
        return field ? `${field}: ${msg ?? ''}` : (msg ?? String(d))
      })
      .join(', ')
  }
  return statusMessage(status)
}

async function reach<T>(promise: Promise<T>): Promise<T> {
  try {
    return await promise
  } catch (e) {
    // fetch fails without a response: network down, server stopped, proxy refused.
    if (e instanceof TypeError) throw new ApiError(0, statusMessage(0))
    throw e
  }
}

/** Await an openapi-fetch call and return its data, throwing ApiError on failure. */
export async function call<T>(promise: Promise<Result<T>>): Promise<T> {
  const { data, error, response } = await reach(promise)
  if (!response.ok) throw new ApiError(response.status, message(error, response.status))
  return data as T
}

/** Upload a file as multipart form data (openapi-fetch does not cover this nicely). */
export async function upload<T>(url: string, file: File): Promise<T> {
  const form = new FormData()
  form.append('file', file)
  const response = await reach(authFetch(new Request(url, { method: 'POST', body: form })))
  const body = await response.json().catch(() => undefined)
  if (!response.ok) throw new ApiError(response.status, message(body, response.status))
  return body as T
}
