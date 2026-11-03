import { useEffect, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { PageContainer } from '@ant-design/pro-components';
import { getWorkspace } from '@/features/workspace/api';
import CreateForm from '../components/CreateForm';

/**
 * Dynamo Create — page shell. Form 在 components/CreateForm (照推理)。
 */
export default function DynamoCreate() {
  const { wsId = '' } = useParams();
  const navigate = useNavigate();
  const { t } = useTranslation('dynamo');
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
            { title: <a onClick={() => navigate(`/workspaces/${wsId}`)}>{workspaceName}</a> },
            { title: <a onClick={() => navigate(`/workspaces/${wsId}/dynamo`)}>{t('nav.dynamo')}</a> },
            { title: t('create.breadcrumbNew') },
          ],
        },
      }}
    >
      <CreateForm />
    </PageContainer>
  );
}
