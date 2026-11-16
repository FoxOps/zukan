// Optional modules (`app.modules` on the server): name and what they add.
export const MODULES: Record<string, { name: string; text: string }> = {
  binder: { name: 'Binder', text: 'Follow sets and check off the cards you own.' },
}

export const moduleInfo = (id: string) => MODULES[id] ?? { name: id, text: '' }
