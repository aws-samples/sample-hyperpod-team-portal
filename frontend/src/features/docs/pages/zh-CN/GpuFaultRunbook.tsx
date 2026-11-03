import { Typography } from 'antd';
import MarkdownDocPage from '../../components/MarkdownDocPage';
import runbook from '../../content/gpu-fault-runbook.zh-CN.md?raw';

const { Text } = Typography;

export default function DocsGpuFaultRunbook() {
  return (
    <MarkdownDocPage
      title="GPU 节点故障诊断 Runbook"
      description="Capacity Block / Self-Managed EKS / SageMaker HyperPod 通用 — 节点 NotReady、Xid 错误、GPU 隔离等故障的排查与恢复步骤。"
      meta={<Text type="secondary">v1 · 2026-07-06</Text>}
      markdown={runbook}
    />
  );
}
