import { useTranslation } from 'react-i18next'
import { Link } from 'react-router'

/** Says that `count` entries of the list belong to games hidden in Settings, so nothing
 * seems lost. */
export function HiddenGamesNote({ count }: { count: number }) {
  const { t } = useTranslation()
  if (count === 0) return null
  return (
    <p className="text-sm text-base-content/60">
      {t('{{count}} more in games hidden in Settings.', { count })}{' '}
      <Link to="/settings" className="link">
        {t('Choose games')}
      </Link>
    </p>
  )
}
