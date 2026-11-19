import { useTranslation } from 'react-i18next'
import type { Schemas } from '../../api/client'

type Issue = Schemas['DeckIssueOut']

/** An issue of the format check in the UI language (the server's English text for
 * codes this page does not know yet). */
function useIssueText() {
  const { t } = useTranslation()
  return (issue: Issue): string => {
    const p = (issue.params ?? {}) as Record<string, string | number | string[]>
    const n = p.count as number
    switch (issue.code) {
      case 'deck_size_exact':
        return t('The deck has {{n}} cards (commanders included), it needs exactly {{size}}', { n, size: p.size })
      case 'deck_size_min':
        return t('The main deck has {{n}} cards, it needs at least {{size}}', { n, size: p.size })
      case 'sideboard_max':
        return t('The sideboard has {{n}} cards, at most {{size}} allowed', { n, size: p.size })
      case 'sideboard_ignored':
        return t('This format has no sideboard: {{n}} cards not counted', { n })
      case 'commander_unused':
        return t('This format has no commander: those cards count as main deck')
      case 'copy_limit':
        return t('{{name}}: {{n}} copies, at most {{limit}} allowed', { name: p.name, n, limit: p.limit })
      case 'banned':
        return t('{{name}} is banned in this format', { name: p.name })
      case 'not_legal':
        return t('{{name}} is not legal in this format', { name: p.name })
      case 'restricted':
        return t('{{name}} is restricted to one copy', { name: p.name })
      case 'no_commander':
        return t('Choose a commander')
      case 'too_many_commanders':
        return t('{{n}} commanders, at most 2 allowed', { n: (p.count as number) ?? 3 })
      case 'commander_pair':
        return t('These two commanders cannot lead a deck together')
      case 'invalid_commander':
        return t('{{name}} cannot be a commander (not a legendary creature)', { name: p.name })
      case 'invalid_commander_creature':
        return t('{{name}} cannot be a commander (not a creature)', { name: p.name })
      case 'no_oathbreaker':
        return t('Choose an oathbreaker (a planeswalker)')
      case 'too_many_oathbreakers':
        return t('{{n}} oathbreakers: one, or two with partner', { n })
      case 'signature_spells':
        return t('{{n}} signature spells for {{size}} oathbreakers: one instant or sorcery each', { n, size: p.size })
      case 'invalid_oathbreaker':
        return t('{{name}} is neither a planeswalker nor an instant or sorcery', { name: p.name })
      case 'commander_rarity':
        return t('Commanders printed at uncommon are not checked')
      case 'color_identity':
        return t("{{name}} is outside the commander's color identity ({{colors}})", { name: p.name, colors: p.colors })
      case 'legality_unknown':
        return t('Legality of {{n}} cards is not known yet (it comes with the next catalog sync; Asian and Chinese Pokémon cards have none): {{names}}', {
          n,
          names: ((p.names as string[]) ?? []).slice(0, 10).join(', '),
        })
      // Pokémon.
      case 'deck_size':
        return t('The deck has {{n}} cards, it needs exactly {{size}}', { n, size: p.size })
      case 'section_unused':
        return t('This format has no sideboard nor commander: {{n}} cards not counted', { n })
      case 'no_basic':
        return t('The deck needs at least one Basic Pokémon')
      case 'basic_unknown':
        return t('The stage of some Pokémon is not known')
      case 'ace_spec_max':
        return t('{{n}} ACE SPEC cards, at most 1 allowed', { n })
      case 'ace_spec_banned':
        return t('{{name}}: ACE SPEC cards are banned in this format', { name: p.name })
      case 'radiant_max':
        return t('{{n}} Radiant Pokémon, at most 1 allowed', { n })
      case 'rule_box':
        return t('{{name}}: Rule Box Pokémon are banned in this format', { name: p.name })
      case 'single_type':
        return t("{{name}} is not of the deck's type ({{type}})", { name: p.name, type: p.type })
      // Lorcana.
      case 'inks_max':
        return t('The deck has {{n}} inks ({{inks}}), at most 2 allowed', { n, inks: ((p.inks as string[]) ?? []).map((i) => t(i[0].toUpperCase() + i.slice(1))).join(', ') })
      case 'off_ink':
        return t("{{name}} is not of the deck's inks ({{inks}})", { name: p.name, inks: ((p.inks as string[]) ?? []).map((i) => t(i[0].toUpperCase() + i.slice(1))).join(', ') })
      case 'glc_bans':
        return t('Not checked: the Gym Leader Challenge ban list')
      case 'special_rules':
        return t('Not checked: cards with special deck rules')
      case 'color_identity_unchecked':
        return t('Color identity is checked once a commander is set')
      case 'pair_by_text':
        return t("Commander pairs (Partner, Friends forever, Background, Doctor's companion) are checked from rules text")
      case 'not_modelled':
        return t('Not checked: companion deck conditions, cards with other special deck rules')
      default:
        return issue.message
    }
  }
}

const LEVEL = { error: 'text-error', warning: 'text-warning', info: 'text-info' } as const

/** Format check: issues (never blocking: a draft can be saved) and the checks that
 * could not be made. */
export function Validation({ validation }: { validation: Schemas['DeckValidationOut'] }) {
  const { t } = useTranslation()
  const text = useIssueText()
  return (
    <div className="card bg-base-200">
      <div className="card-body gap-2 p-4">
        <h2 className="flex items-center gap-2 font-semibold">
          {t('Format check')}
          {validation.valid ? (
            <span className="badge badge-sm badge-success">{t('Format rules met')}</span>
          ) : (
            <span className="badge badge-sm badge-warning">{t('{{count}} issues', { count: validation.issues.filter((i) => i.level === 'error').length })}</span>
          )}
        </h2>
        {validation.issues.length > 0 && (
          <ul className="flex flex-col gap-1 text-sm">
            {validation.issues.map((issue, i) => (
              <li key={i} className="flex gap-2">
                <span className={`${LEVEL[issue.level]} font-bold`} aria-hidden>
                  {issue.level === 'error' ? '✕' : issue.level === 'warning' ? '!' : 'i'}
                </span>
                <span>{text(issue)}</span>
              </li>
            ))}
          </ul>
        )}
        {validation.unverified.length > 0 && (
          <div className="mt-1 border-t border-base-300 pt-2">
            <div className="text-xs font-semibold uppercase text-base-content/60">{t('Not verified')}</div>
            <ul className="mt-1 flex flex-col gap-1 text-xs text-base-content/70">
              {validation.unverified.map((issue, i) => (
                <li key={i}>? {text(issue)}</li>
              ))}
            </ul>
          </div>
        )}
        <p className="text-xs text-base-content/50">{t('Issues never block saving: keep editing your draft.')}</p>
      </div>
    </div>
  )
}
