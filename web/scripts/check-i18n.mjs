// Check that every text passed to t('...') has a translation in each locale.
// Keys are the English texts; `{{count}}` keys are plurals and need `_one` / `_other`.
// Texts coming from the server (game colors and finishes, job kinds...) are listed below.
import { readdirSync, readFileSync, statSync } from 'node:fs'
import { join } from 'node:path'

const SRC = new URL('../src/', import.meta.url).pathname
const LOCALES = { en: 'locales/en.json', fr: 'locales/fr.json' }
const DYNAMIC = [
  // Navigation labels, sort options, conditions, job kinds and states, roles, sources.
  'Dashboard', 'Collection', 'Catalog', 'Import / export', 'Settings', 'Users', 'Data sync',
  'Data checks', 'Type', 'Subtype', 'Rarity', 'Category', 'Trainer type', 'Stage', 'name', 'rarity', 'set name', 'release date', 'card count',
  'cross-checked', 'differences',
  'Name', 'Newest sets', 'Recently changed', 'Quantity', 'Price: low to high', 'Price: high to low',
  'Owned first', 'Oldest sets', 'Set name', 'Collector number',
  'Mint', 'Near Mint', 'Excellent', 'Good', 'Light Played', 'Played', 'Poor',
  'catalog', 'prices', 'images', 'running', 'success', 'failed', 'user', 'admin', 'web', 'scan', 'import',
  'cancelled', 'auto', 'manual',
  // Collection views and trend periods.
  'List', 'Images', '24h', '7d', '30d',
  // Finance periods.
  'Finance', '1 day', '7 days', '30 days', '90 days', '1 year',
  // Stale card reasons, job report.
  'Missed by the last catalog sync', 'No image', 'No card details', 'arbitrated values written',
  // Job report counters.
  'sets', 'cards', 'printings', 'names', 'owned printings', 'prices received', 'stored',
  'already cached', 'skipped', 'without source', 'refused by source', 'old prices removed',
  'empty cards removed', 'translations copied', 'printings moved', 'set icons', 'card backs', 'pictures not downloaded', 'refresh', 'outdated cards', 'updated', 'not found at the source',
  // Markets of the games split by region (`GameOut.region_label`).
  'International', 'Asia', 'China', 'TCG', 'OCG',
  // Names from the game plugins.
  'White', 'Blue', 'Black', 'Red', 'Green', 'Colorless', 'Grass', 'Fire', 'Water', 'Lightning',
  'Psychic', 'Fighting', 'Darkness', 'Metal', 'Fairy', 'Dragon', 'Air', 'Earth',
  'Foil', 'Etched foil', 'Holo', 'Reverse holo', '1st edition', 'Standard', 'Rainbow foil',
  'Fury', 'Calm', 'Mind', 'Body', 'Chaos', 'Order', 'Normal', 'Supertype', 'Tag', 'text',
  'No type', 'Amber', 'Amethyst', 'Emerald', 'Ruby', 'Sapphire', 'Steel', 'Dark', 'Light', 'Wind', 'Divine', 'Spell', 'Trap', 'Unlimited', '1st Edition', 'Limited Edition', 'Classification', 'Story', 'Inkwell', 'Monster type', 'Archetype',
]

function files(dir) {
  return readdirSync(dir).flatMap((name) => {
    const path = join(dir, name)
    if (statSync(path).isDirectory()) return files(path)
    return /\.tsx?$/.test(name) && !name.endsWith('.d.ts') ? [path] : []
  })
}

const keys = new Set(DYNAMIC)
const call = /(?<![\w.])t\(\s*(['"])((?:\\.|(?!\1).)*)\1/g
for (const file of files(SRC)) {
  for (const match of readFileSync(file, 'utf8').matchAll(call)) keys.add(match[2].replace(/\\(.)/g, '$1'))
}

let problems = 0
for (const [lang, path] of Object.entries(LOCALES)) {
  const dictionary = JSON.parse(readFileSync(join(SRC, path), 'utf8'))
  const used = new Set()
  for (const key of keys) {
    const needed = key.includes('{{count}}') ? [`${key}_one`, `${key}_other`] : lang === 'en' ? [] : [key]
    for (const entry of needed) {
      used.add(entry)
      if (!(entry in dictionary)) {
        console.error(`${lang}: missing ${JSON.stringify(entry)}`)
        problems++
      }
    }
  }
  for (const entry of Object.keys(dictionary)) {
    if (!used.has(entry)) {
      console.error(`${lang}: unused ${JSON.stringify(entry)}`)
      problems++
    }
  }
}
if (problems) process.exit(1)
console.log(`${keys.size} texts translated`)
