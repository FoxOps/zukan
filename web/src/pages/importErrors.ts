import { useTranslation } from 'react-i18next'
import type { Schemas } from '../api/client'

type ImportError = Schemas['ImportErrorOut']

/** A problem of an imported file in the UI language, with the values to correct (set,
 * number...) kept as written; the server's English text for codes this page does not
 * know yet. */
export function useImportErrorText() {
  const { t } = useTranslation()
  return (e: ImportError): string => {
    const p = (e.params ?? {}) as Record<string, string | number>
    switch (e.code) {
      case 'invalid_csv':
        return t('Not a valid CSV file: {{detail}}', p)
      case 'missing_columns':
        return t('Missing columns: {{columns}}', p)
      case 'too_many_rows':
        return t('More than {{max}} rows', p)
      case 'unknown_game':
        return t('Unknown game “{{game}}”', p)
      case 'invalid_quantity_or_price':
        return t('Invalid quantity or price')
      case 'invalid_price':
        return t('Invalid price “{{price}}”', p)
      case 'invalid_quantity':
        return t('Invalid quantity “{{quantity}}”', p)
      case 'nul_character':
        return t('Invalid character (NUL)')
      case 'notes_too_long':
        return t('Notes longer than {{max}} characters', p)
      case 'printing_not_found':
        return t('No printing of set “{{set}}” has the number “{{number}}”.', p)
      case 'printing_ambiguous':
        return t('Several printings of set “{{set}}” have the number “{{number}}”.', p)
      case 'finish_unknown':
        return t('Finish “{{finish}}” does not exist for this printing', p)
      case 'language_unsupported':
        return t('Language “{{language}}” is not supported for {{game}}', p)
      case 'condition_unknown':
        return t('Unknown condition “{{condition}}”', p)
      case 'not_enough_copies':
        return t('Not enough copies to remove')
      case 'set_not_found':
        return t('No set “{{set}}”', p)
      case 'set_ambiguous':
        return t('Several sets “{{set}}”', p)
      case 'set_language_missing':
        return t('No printing of this set in “{{language}}”', p)
      case 'set_finish_missing':
        return t('No printing of this set in “{{finish}}”', p)
      case 'set_twice':
        return t('Set listed twice')
      case 'decks_file_missing':
        return t('decks.csv is missing')
      case 'deck_reference_missing':
        return t('No deck reference')
      case 'deck_twice':
        return t('Deck “{{deck}}” listed twice', p)
      case 'game_without_decks':
        return t('No decks for game “{{game}}”', p)
      case 'format_unknown':
        return t('“{{format}}” is not a format of {{game}}', p)
      case 'deck_name_length':
        return t('Deck names have 1 to {{max}} characters', p)
      case 'deck_unknown':
        return t('Unknown deck “{{deck}}”', p)
      case 'section_unknown':
        return t('No section “{{section}}” in {{format}}', p)
      case 'card_not_found':
        return t('No card “{{card}}” in {{game}}', p)
      case 'printing_not_of_card':
        return t('Printing not found for this card')
      case 'card_not_in_deck':
        return t('This card is not in the deck')
      case 'module_disabled':
        return t('The {{module}} module is not enabled', p)
      default:
        return e.message
    }
  }
}
