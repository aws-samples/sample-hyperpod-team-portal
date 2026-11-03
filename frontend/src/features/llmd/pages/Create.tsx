import { useEffect, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { PageContainer } from '@ant-design/pro-components';
import { getWorkspace } from '@/features/workspace/api';
import CreateForm from '../components/CreateForm';

/**
 * llm-d Create — page shell. Form 在 components/CreateForm (照 dynamo)。
 */
export default function LlmdCreate() {
  const { wsId = '' } = useParams();
  const navigate = useNavigate();
  const { t } = useTranslation('llmd');
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
            { title: <a onClick={() => navigate(`/workspaces/${wsId}/llmd`)}>{t('nav.llmd')}</a> },
            { title: t('create.breadcrumbNew') },
          ],
        },
      }}
    >
      <CreateForm />
    </PageContainer>
  );
}
