/** This browser's saved preferences (theme, views, last choices). Storage can be refused
 * (privacy settings, some private windows): reads give null and writes are dropped, the
 * interface works without them. */
export function readStored(key: string): string | null {
  try {
    return localStorage.getItem(key)
  } catch {
    return null
  }
}

export function store(key: string, value: string): void {
  try {
    localStorage.setItem(key, value)
  } catch {
    // Not kept: fine.
  }
}
