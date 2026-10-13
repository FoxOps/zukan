import { useTranslation } from 'react-i18next'
import { Link } from 'react-router'

export default function NotFound() {
  const { t } = useTranslation()
  return (
    <div className="hero min-h-[50vh]">
      <div className="hero-content text-center">
        <div>
          <h1 className="text-4xl font-bold">{t('Not found')}</h1>
          <Link to="/" className="btn btn-primary mt-6">{t('Back to dashboard')}</Link>
        </div>
      </div>
    </div>
  )
}
