import { useEffect, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { PageContainer } from '@ant-design/pro-components';
import { useTranslation } from 'react-i18next';
import { getWorkspace } from '@/features/workspace/api';
import CreateForm from '../components/CreateForm';

/**
 * DevInstance Create — page shell only. Breadcrumb + title. Actual form
 * lives in `components/CreateForm/index.tsx` (templates / ws mounts fetch,
 * step validation, payload build, submit).
 */
export default function DevInstanceCreate() {
  const { wsId = '' } = useParams();
  const navigate = useNavigate();
  const { t } = useTranslation('devinstance');
  // 拉到前为 null, 渲染时回退到翻译后的"工作空间" (不在 useState 初值里翻译)
  const [workspaceName, setWorkspaceName] = useState<string | null>(null);

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
                  {workspaceName ?? t('nav.workspace')}
                </a>
              ),
            },
            {
              title: (
                <a onClick={() => navigate(`/workspaces/${wsId}/dev`)}>
                  {t('nav.devInstance')}
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
