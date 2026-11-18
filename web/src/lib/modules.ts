// Optional modules (`app.modules` on the server): name and what they add.
export const MODULES: Record<string, { name: string; text: string }> = {
  binder: { name: 'Binder', text: 'Follow sets and check off the cards you own.' },
  decks: { name: 'Decks', text: 'Build Magic decks, check format rules and set owned copies aside for each deck.' },
}

export const moduleInfo = (id: string) => MODULES[id] ?? { name: id, text: '' }
