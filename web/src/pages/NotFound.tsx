import { useTranslation } from 'react-i18next'
import { Link } from 'react-router'
import { EmptyState } from '../components/Page'

export default function NotFound() {
  const { t } = useTranslation()
  return (
    <EmptyState title={t('Not found')} actions={<Link to="/" className="btn btn-primary min-h-11">{t('Back to the overview')}</Link>}>
      {t('This page does not exist, or no longer.')}
    </EmptyState>
  )
}
