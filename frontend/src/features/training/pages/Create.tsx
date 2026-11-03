import { useEffect, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { PageContainer } from '@ant-design/pro-components';
import { getWorkspace } from '@/features/workspace/api';
import CreateForm from '../components/CreateForm';

/**
 * Training Create — page shell only. Breadcrumb + title. Actual form
 * lives in `components/CreateForm.tsx` (quota fetching, validation,
 * payload build, submit).
 */
export default function TrainingCreate() {
  const { wsId = '' } = useParams();
  const navigate = useNavigate();
  const { t } = useTranslation('training');
  const [workspaceName, setWorkspaceName] = useState<string>(t('nav.workspace'));

  useEffect(() => {
    if (!wsId) return;
    getWorkspace(wsId)
      .then((w) => setWorkspaceName(w.display_name))
      .catch(() => undefined);
  }, [wsId]);

  return (
    <PageContainer
      header={{
        title: t('create.title'),
        breadcrumb: {
          items: [
            {
              title: (
                <a onClick={() => navigate(`/workspaces/${wsId}`)}>
                  {workspaceName}
                </a>
              ),
            },
            {
              title: (
                <a onClick={() => navigate(`/workspaces/${wsId}/training`)}>
                  {t('nav.training')}
                </a>
              ),
            },
            { title: t('create.breadcrumbNew') },
          ],
        },
      }}
    >
      <CreateForm />
    </PageContainer>
  );
}
