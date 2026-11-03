import { useEffect } from 'react';
import { Navigate, useNavigate } from 'react-router-dom';
import { Result, Button } from 'antd';

/**
 * Legacy quota management page. Path 2 refactor (2026-05-11) migrated quota
 * CRUD from a custom `resource_quota` DB table to AWS ComputeQuota APIs. The
 * new UI lives alongside the cluster instance groups at `/admin/cluster`
 * (bottom "团队配额" table). We redirect here to preserve old bookmarks.
 */
export default function AdminQuota() {
  const navigate = useNavigate();

  useEffect(() => {
    const t = setTimeout(() => navigate('/admin/cluster', { replace: true }), 1500);
    return () => clearTimeout(t);
  }, [navigate]);

  return (
    <Result
      status="info"
      title="配额管理已合并到「集群管理」"
      subTitle="路径 2 重构后已切换为 AWS ComputeQuota 原生 API · 1.5 秒后自动跳转"
      extra={[
        <Button
          type="primary"
          key="go"
          onClick={() => navigate('/admin/cluster', { replace: true })}
        >
          立即跳转
        </Button>,
      ]}
    />
  );
}

// Export a permanent redirect variant in case callers want to use it directly
// without the transitional notice screen.
export const AdminQuotaRedirect = () => (
  <Navigate to="/admin/cluster" replace />
);
