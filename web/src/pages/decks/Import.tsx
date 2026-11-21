import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { api, call, type Schemas } from '../../api/client'
import { Select } from '../../components/Select'
import { useToast } from '../../components/toast'

type Line = Schemas['DeckImportLineOut']
type Section = Schemas['DeckImportEntryIn']['section']

// Example decklists, as each game's deck sites export them.
const PLACEHOLDERS: Record<string, string> = {
  mtg: 'Commander\n1 Krenko, Mob Boss\n\nDeck\n4 Lightning Bolt (M10) 146\n30 Mountain\n\nSideboard\n2 Pyroblast',
  pokemon: "Pokémon: 8\n4 Charmander PAF 7\n4 Charizard ex OBF 125\n\nTrainer: 4\n4 Professor's Research SVI 189\n\nEnergy: 1\n10 Basic {R} Energy SVE 2",
  lorcana: '4 Elsa - Snow Queen\n4 Friends on the Other Side\n2 Dalmatian Puppy - Tail Wagger',
  riftbound: 'Legend:\n1 Ahri, Nine-Tailed Fox\n\nChampion:\n1 Ahri, Alluring\n\nMain Deck:\n3 Ahri, Alluring\n3 Mind Rune Spark\n\nBattlefields:\n1 Grove of the God-Willow\n\nRunes:\n6 Calm Rune\n6 Mind Rune',
  yugioh: '#main\n46986414\n46986414\n#extra\n98502113\n!side\n44095762',
  sorcery: 'Avatar:\n1 Sparkmage\n\nAtlas:\n4 Arid Desert\n\nSpellbook:\n4 Pudge Butcher\n\nCollection:\n1 Fireball',
}
const STATUS = { resolved: 'badge-success', ambiguous: 'badge-warning', unknown: 'badge-error' } as const

/** Paste a plain-text decklist, check what each line resolves to (pick a card for
 * ambiguous or unknown names), then add the cards to the deck or replace its list.
 * Nothing is allocated: the collection's available copies do not change. */
export function ImportDialog({
  deckId,
  gameId,
  sections: formatSections,
  open,
  onClose,
}: {
  deckId: number
  gameId: string
  // The deck format's sections and their shown names.
  sections: { id: Section; name: string }[]
  open: boolean
  onClose: () => void
}) {
  const { t } = useTranslation()
  const kind = gameId.startsWith('pokemon') ? 'pokemon' : gameId.startsWith('yugioh') ? 'yugioh' : gameId
  const help: Record<string, string> = {
    pokemon: t('One card per line ("4 Charmander PAF 7"), as Pokémon TCG Live exports them; the set code and number choose the printing.'),
    lorcana: t('One card per line with its full name ("4 Elsa - Snow Queen"), as Dreamborn and Inktable export them.'),
    riftbound: t('One card per line ("3 Ahri, Alluring"). "Legend", "Champion", "Battlefields", "Runes" and "Sideboard" lines start those sections; legends, runes and battlefields found in the main deck go to theirs.'),
    yugioh: t('A YDK file (#main, #extra, !side and one card password per line) or one card per line ("3 Dark Magician") under "Main Deck", "Extra Deck" and "Side Deck"; Extra Deck monsters go to the Extra Deck.'),
    sorcery: t('One card per line ("4 Pudge Butcher") under "Avatar", "Atlas", "Spellbook" and "Collection", as Curiosa exports them; avatars and sites found in the spellbook go to theirs.'),
  }
  const toast = useToast()
  const client = useQueryClient()
  const [text, setText] = useState('')
  const [lines, setLines] = useState<Line[] | null>(null)
  const [skipped, setSkipped] = useState<string[]>([])
  // Card picked and section per line number ('' : line left out).
  const [picked, setPicked] = useState<Record<number, string>>({})
  const [sections, setSections] = useState<Record<number, Section>>({})
  const [replace, setReplace] = useState(false)

  const close = () => {
    setLines(null)
    setText('')
    setPicked({})
    setSections({})
    setReplace(false)
    onClose()
  }
  const preview = useMutation({
    mutationFn: () => call(api.POST('/api/decks/import/preview', { body: { text, game_id: gameId as Schemas['DeckImportPreviewIn']['game_id'] } })),
    onSuccess: (result) => {
      setLines(result.lines)
      setSkipped(result.skipped)
      setPicked(Object.fromEntries(result.lines.map((l) => [l.line, l.card ? String(l.card.card_id) : ''])))
      setSections(Object.fromEntries(result.lines.map((l) => [l.line, l.section])))
    },
    onError: (e) => toast(e.message, 'error'),
  })
  const entries = (lines ?? [])
    .filter((l) => picked[l.line])
    .map((l) => ({
      card_id: Number(picked[l.line]),
      quantity: l.quantity,
      section: sections[l.line] ?? l.section,
      // The printing the line names, for the card it was found as.
      printing_id: l.printing && l.card && String(l.card.card_id) === picked[l.line] ? l.printing.id : null,
    }))
  const save = useMutation({
    mutationFn: () =>
      call(api.POST('/api/decks/{deck_id}/import', { params: { path: { deck_id: deckId } }, body: { entries, replace } })),
    onSuccess: async () => {
      await client.invalidateQueries({ queryKey: ['decks'] })
      toast(t('{{count}} cards imported', { count: entries.reduce((n, e) => n + e.quantity, 0) }), 'success')
      close()
    },
    onError: (e) => toast(e.message, 'error'),
  })
  const problems = (lines ?? []).filter((l) => l.status !== 'resolved').length

  return (
    <dialog className={`modal ${open ? 'modal-open' : ''}`} onClose={close}>
      {open && (
        <div className="modal-box max-w-3xl animate-in fade-in zoom-in-95 duration-200">
          <h3 className="text-lg font-bold">{t('Import a decklist')}</h3>
          {lines === null ? (
            <div className="mt-3 flex flex-col gap-2">
              <p className="text-sm text-base-content/70">
                {help[kind] ?? t('One card per line ("4 Lightning Bolt"). "Commander", "Companion" and "Sideboard" lines start those sections; a set code and number ("(M10) 146") choose the printing.')}
              </p>
              <textarea
                className="textarea h-64 w-full font-mono text-sm"
                value={text}
                onChange={(e) => setText(e.target.value)}
                placeholder={PLACEHOLDERS[kind] ?? PLACEHOLDERS.mtg}
                aria-label={t('Decklist')}
              />
            </div>
          ) : (
            <div className="mt-3 flex flex-col gap-2">
              <p className="text-sm">
                {problems > 0
                  ? t('{{count}} lines need a choice: pick the card or leave the line out.', { count: problems })
                  : t('Every line was found.')}
              </p>
              <div className="max-h-96 overflow-y-auto rounded-box border border-base-300">
                <table className="table table-sm">
                  <thead>
                    <tr>
                      <th>{t('Line')}</th>
                      <th className="text-right">{t('Qty')}</th>
                      <th>{t('Card')}</th>
                      <th>{t('Section')}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {lines.map((l) => (
                      <tr key={l.line} className={picked[l.line] ? '' : 'opacity-60'}>
                        <td className="max-w-48">
                          <div className="flex items-center gap-1">
                            <span className={`badge badge-xs ${STATUS[l.status]}`}>{t(l.status === 'resolved' ? 'Found' : l.status === 'ambiguous' ? 'Ambiguous' : 'Unknown')}</span>
                          </div>
                          <div className="truncate font-mono text-xs" title={l.text}>
                            {l.text}
                          </div>
                        </td>
                        <td className="text-right">{l.quantity}</td>
                        <td>
                          {l.status === 'resolved' && l.card ? (
                            <span className="flex flex-wrap items-center gap-1 text-sm">
                              {l.card.name}
                              {l.printing ? (
                                <span className="badge badge-xs badge-outline font-mono">
                                  {l.printing.set_code} {l.printing.collector_number}
                                </span>
                              ) : (
                                l.set_code && (
                                  <span className="badge badge-xs badge-ghost" title={t('No printing of this card has that set code and number: any printing')}>
                                    {t('{{set}} not found', { set: [l.set_code, l.collector_number].filter(Boolean).join(' ') })}
                                  </span>
                                )
                              )}
                            </span>
                          ) : (
                            <Select
                              className="w-full min-w-48"
                              value={picked[l.line] ?? ''}
                              onChange={(v) => setPicked((p) => ({ ...p, [l.line]: v }))}
                              aria-label={t('Card for line {{line}}', { line: l.line })}
                              options={[
                                { value: '', label: l.candidates.length ? t('Leave out') : t('Not found: left out') },
                                ...l.candidates.map((c) => ({ value: String(c.card_id), label: `${c.name}${c.type_line ? ` · ${c.type_line}` : ''}` })),
                              ]}
                            />
                          )}
                        </td>
                        <td>
                          <Select
                            className="w-36"
                            disabled={formatSections.length < 2}
                            value={sections[l.line] ?? l.section}
                            onChange={(v) => setSections((s) => ({ ...s, [l.line]: v as Section }))}
                            aria-label={t('Section')}
                            options={[
                              ...formatSections.map((s) => ({ value: s.id, label: s.name })),
                              // A section the format lacks ("Commander" in a Standard deck): kept, shown as read.
                              ...(formatSections.some((s) => s.id === (sections[l.line] ?? l.section)) ? [] : [{ value: sections[l.line] ?? l.section, label: sections[l.line] ?? l.section }]),
                            ]}
                          />
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              {skipped.length > 0 && (
                <p className="text-xs text-base-content/60">{t('Lines not understood: {{lines}}', { lines: skipped.join(' · ') })}</p>
              )}
              <label className="flex items-center gap-2 text-sm">
                <input type="checkbox" className="checkbox checkbox-sm" checked={replace} onChange={(e) => setReplace(e.target.checked)} />
                {t('Replace the current decklist (copies allocated to cards that leave it are released)')}
              </label>
            </div>
          )}
          <div className="modal-action">
            <button className="btn btn-ghost" onClick={close}>
              {t('Cancel')}
            </button>
            {lines === null ? (
              <button className="btn btn-primary" disabled={!text.trim() || preview.isPending} onClick={() => preview.mutate()}>
                {preview.isPending && <span className="loading loading-spinner loading-sm" />}
                {t('Preview')}
              </button>
            ) : (
              <>
                <button className="btn btn-ghost" onClick={() => setLines(null)}>
                  {t('Edit text')}
                </button>
                <button className="btn btn-primary" disabled={entries.length === 0 || save.isPending} onClick={() => save.mutate()}>
                  {save.isPending && <span className="loading loading-spinner loading-sm" />}
                  {t('Import {{count}} cards', { count: entries.reduce((n, e) => n + e.quantity, 0) })}
                </button>
              </>
            )}
          </div>
        </div>
      )}
      <form method="dialog" className="modal-backdrop">
        <button onClick={close}>{t('Close')}</button>
      </form>
    </dialog>
  )
}
