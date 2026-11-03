import { Typography } from 'antd';
import MarkdownDocPage from '../../components/MarkdownDocPage';
import runbook from '../../content/gpu-fault-runbook.en-US.md?raw';

const { Text } = Typography;

export default function DocsGpuFaultRunbook() {
  return (
    <MarkdownDocPage
      title="GPU Node Fault Diagnosis Runbook"
      description="Applies to Capacity Block / Self-Managed EKS / SageMaker HyperPod: troubleshooting and recovery steps for faults such as node NotReady, Xid errors, and GPU isolation."
      meta={<Text type="secondary">v1 · 2026-07-06</Text>}
      markdown={runbook}
    />
  );
}
