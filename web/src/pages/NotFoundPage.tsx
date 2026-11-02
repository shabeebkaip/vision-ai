import { Compass } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { Page } from '../components/layout/AppShell';
import { ButtonLink } from '../components/ui/Button';
import { EmptyState } from '../components/ui/States';

export function NotFoundPage() {
  const { t } = useTranslation();
  return (
    <Page>
      <div className="card">
        <EmptyState
          icon={<Compass className="size-6" aria-hidden />}
          title={t('errors.pageNotFound')}
          body={t('errors.pageNotFoundBody')}
          action={<ButtonLink to="/">{t('nav.overview')}</ButtonLink>}
        />
      </div>
    </Page>
  );
}
