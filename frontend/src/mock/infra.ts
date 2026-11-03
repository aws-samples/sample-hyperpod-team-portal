/* ============================================================================
 * Infrastructure Mock — Stage 5-B
 *
 * Single source of truth for every Admin "infra" page (cluster, resource pools,
 * nodes, scheduling, quota, storage, network, events, audit). Keep IDs and
 * cross-references consistent so pages can link naturally.
 * ========================================================================== */

import { mockWorkspaces } from './workspaces';
import { mockUsers } from './users';

/* ---------- Cluster ------------------------------------------------------- */

export interface HyperPodCluster {
  id: string;
  name: string;
  status: 'Running' | 'Upgrading' | 'Degraded';
  region: string;
  createdAt: string;
  eks: {
    name: string;
    version: string;
    endpoint: string;
    addons: Array<{ name: string; version: string; status: 'Active' | 'Degraded' }>;
    accessEntryCount: number;
    loggingEnabled: string[];
  };
  slaMonthlyPct: number;
  slaTargetPct: number;
}

export const mockCluster: HyperPodCluster = {
  id: 'hp-cluster-prod-01',
  name: 'hyperpod-prod-cluster-01',
  status: 'Running',
  region: 'us-west-2',
  createdAt: '2025-06-12T02:14:00Z',
  eks: {
    name: 'eks-hyperpod-prod',
    version: '1.31',
    endpoint: 'https://F4B2D7A8C91E.gr7.us-west-2.eks.amazonaws.com',
    addons: [
      { name: 'vpc-cni', version: 'v1.19.2-eksbuild.1', status: 'Active' },
      { name: 'kube-proxy', version: 'v1.31.0-eksbuild.2', status: 'Active' },
      { name: 'coredns', version: 'v1.11.3-eksbuild.1', status: 'Active' },
      { name: 'aws-ebs-csi-driver', version: 'v1.36.0-eksbuild.1', status: 'Active' },
      { name: 'aws-fsx-csi-driver', version: 'v1.11.0', status: 'Active' },
      { name: 'amazon-cloudwatch-observability', version: 'v3.3.0', status: 'Active' },
      { name: 'kueue', version: 'v0.9.1', status: 'Active' },
      { name: 'training-operator', version: 'v1.8.0', status: 'Degraded' },
    ],
    accessEntryCount: 14,
    loggingEnabled: ['api', 'audit', 'authenticator', 'controllerManager', 'scheduler'],
  },
  slaMonthlyPct: 99.94,
  slaTargetPct: 99.9,
};

/* ---------- Instance Groups ---------------------------------------------- */

export interface InstanceGroup {
  id: string;
  name: string;
  instanceType: string;
  nodeCount: number;
  desiredCount: number;
  enabled: boolean;
  az: string[];
  role: 'general' | 'gpu-h100' | 'gpu-a100' | 'dedicated';
}

export const mockInstanceGroups: InstanceGroup[] = [
  {
    id: 'ig-001',
    name: 'ig-general-cpu',
    instanceType: 'ml.m6i.4xlarge',
    nodeCount: 8,
    desiredCount: 8,
    enabled: true,
    az: ['us-west-2a', 'us-west-2b'],
    role: 'general',
  },
  {
    id: 'ig-002',
    name: 'ig-gpu-h100',
    instanceType: 'ml.p5.48xlarge',
    nodeCount: 16,
    desiredCount: 16,
    enabled: true,
    az: ['us-west-2a', 'us-west-2b', 'us-west-2c'],
    role: 'gpu-h100',
  },
  {
    id: 'ig-003',
    name: 'ig-gpu-a100',
    instanceType: 'ml.p4d.24xlarge',
    nodeCount: 16,
    desiredCount: 16,
    enabled: true,
    az: ['us-west-2a', 'us-west-2b'],
    role: 'gpu-a100',
  },
  {
    id: 'ig-004',
    name: 'ig-dedicated-inference',
    instanceType: 'ml.g5.12xlarge',
    nodeCount: 8,
    desiredCount: 8,
    enabled: true,
    az: ['us-west-2a', 'us-west-2c'],
    role: 'dedicated',
  },
];

/* ---------- Cluster Nodes (48 nodes) ------------------------------------- */

export type NodeStatus = 'Healthy' | 'Warning' | 'Faulty' | 'Maintenance';

export interface ClusterNode {
  id: string;
  instanceType: string;
  status: NodeStatus;
  az: string;
  groupId: string;
  groupName: string;
  gpuTotal: number;
  gpuUsed: number;
  podCount: number;
  joinedAt: string;
  kernelVersion: string;
  kubeletVersion: string;
}

/** Stable pseudo-randomish generator so snapshots stay consistent. */
const NODE_BLUEPRINT: Array<Omit<ClusterNode, 'id' | 'joinedAt'>> = [];

(() => {
  const azs = ['us-west-2a', 'us-west-2b', 'us-west-2c'];
  const groups = mockInstanceGroups;

  const push = (
    group: InstanceGroup,
    status: NodeStatus,
    azIdx: number,
    gpuTotal: number,
    gpuUsed: number,
    podCount: number,
  ) => {
    NODE_BLUEPRINT.push({
      instanceType: group.instanceType,
      status,
      az: azs[azIdx % azs.length]!,
      groupId: group.id,
      groupName: group.name,
      gpuTotal,
      gpuUsed,
      podCount,
      kernelVersion: '5.15.0-1068-aws',
      kubeletVersion: 'v1.31.0-eks-8af6e63',
    });
  };

  // general pool — 8 nodes, CPU only
  for (let i = 0; i < 8; i += 1) {
    push(groups[0]!, i === 5 ? 'Warning' : 'Healthy', i, 0, 0, 6 + (i % 4));
  }
  // H100 pool — 16 nodes
  for (let i = 0; i < 16; i += 1) {
    let s: NodeStatus = 'Healthy';
    if (i === 3) s = 'Faulty';
    else if (i === 11) s = 'Warning';
    else if (i === 14) s = 'Maintenance';
    const used = s === 'Faulty' ? 0 : s === 'Maintenance' ? 0 : 4 + (i % 5);
    push(groups[1]!, s, i, 8, used, 4 + (i % 3));
  }
  // A100 pool — 16 nodes
  for (let i = 0; i < 16; i += 1) {
    let s: NodeStatus = 'Healthy';
    if (i === 7) s = 'Faulty';
    else if (i === 2) s = 'Warning';
    const used = s === 'Faulty' ? 0 : 2 + (i % 6);
    push(groups[2]!, s, i, 8, used, 3 + (i % 3));
  }
  // Dedicated inference — 8 nodes
  for (let i = 0; i < 8; i += 1) {
    const s: NodeStatus = i === 4 ? 'Maintenance' : 'Healthy';
    push(groups[3]!, s, i, 4, s === 'Maintenance' ? 0 : 1 + (i % 3), 2 + (i % 3));
  }
})();

export const mockClusterNodes: ClusterNode[] = NODE_BLUEPRINT.map((n, idx) => {
  const hex = (idx + 17).toString(16).padStart(4, '0');
  return {
    ...n,
    id: `i-0${hex}a8b7c6d5e4f${(idx % 10).toString(16)}`,
    joinedAt: new Date(
      Date.UTC(2025, 5, 12) + idx * 36 * 3600 * 1000,
    ).toISOString(),
  };
});

/* ---------- Resource Pools ---------------------------------------------- */

export interface ResourcePool {
  id: string;
  name: string;
  displayName: string;
  role: InstanceGroup['role'];
  groupId: string;
  instanceType: string;
  status: 'Active' | 'Paused' | 'Scaling';
  nodeTotal: number;
  nodeAvailable: number;
  gpuTotal: number;
  gpuAllocated: number;
  gpuQueued: number;
  kueueQueue: string;
  grantedWorkspaces: string[];
  description: string;
}

export const mockResourcePools: ResourcePool[] = [
  {
    id: 'pool-general',
    name: 'general-pool',
    displayName: '通用池',
    role: 'general',
    groupId: 'ig-001',
    instanceType: 'ml.m6i.4xlarge',
    status: 'Active',
    nodeTotal: 8,
    nodeAvailable: 7,
    gpuTotal: 0,
    gpuAllocated: 0,
    gpuQueued: 0,
    kueueQueue: 'cq-general',
    grantedWorkspaces: mockWorkspaces.map((w) => w.id),
    description: 'CPU 通用池,承载平台组件与轻量任务',
  },
  {
    id: 'pool-h100',
    name: 'gpu-h100-pool',
    displayName: 'GPU 加速池 — H100',
    role: 'gpu-h100',
    groupId: 'ig-002',
    instanceType: 'ml.p5.48xlarge',
    status: 'Active',
    nodeTotal: 16,
    nodeAvailable: 13,
    gpuTotal: 128,
    gpuAllocated: 86,
    gpuQueued: 24,
    kueueQueue: 'cq-gpu-h100',
    grantedWorkspaces: ['ws-001', 'ws-002'],
    description: 'H100 高端训练池,优先大模型预训练',
  },
  {
    id: 'pool-a100',
    name: 'gpu-a100-pool',
    displayName: 'GPU 加速池 — A100',
    role: 'gpu-a100',
    groupId: 'ig-003',
    instanceType: 'ml.p4d.24xlarge',
    status: 'Active',
    nodeTotal: 16,
    nodeAvailable: 15,
    gpuTotal: 128,
    gpuAllocated: 72,
    gpuQueued: 8,
    kueueQueue: 'cq-gpu-a100',
    grantedWorkspaces: ['ws-001', 'ws-002', 'ws-003'],
    description: 'A100 通用训练池,SFT / 微调 / 中等规模任务',
  },
  {
    id: 'pool-dedicated',
    name: 'dedicated-inference-pool',
    displayName: '专属池 — 推理',
    role: 'dedicated',
    groupId: 'ig-004',
    instanceType: 'ml.g5.12xlarge',
    status: 'Active',
    nodeTotal: 8,
    nodeAvailable: 7,
    gpuTotal: 32,
    gpuAllocated: 18,
    gpuQueued: 0,
    kueueQueue: 'cq-inference',
    grantedWorkspaces: ['ws-001', 'ws-002', 'ws-003'],
    description: 'g5 系列推理专属池,长驻低延迟服务',
  },
];

/* ---------- Kueue Queues ------------------------------------------------ */

export interface KueueQueue {
  id: string;
  name: string;
  poolId: string;
  poolName: string;
  cpuCapacity: number;
  cpuUsed: number;
  gpuCapacity: number;
  gpuUsed: number;
  pendingJobs: number;
  runningJobs: number;
  preemptionCount: number;
}

export const mockKueueQueues: KueueQueue[] = [
  {
    id: 'cq-general',
    name: 'cq-general',
    poolId: 'pool-general',
    poolName: '通用池',
    cpuCapacity: 256,
    cpuUsed: 168,
    gpuCapacity: 0,
    gpuUsed: 0,
    pendingJobs: 0,
    runningJobs: 12,
    preemptionCount: 0,
  },
  {
    id: 'cq-gpu-h100',
    name: 'cq-gpu-h100',
    poolId: 'pool-h100',
    poolName: 'GPU — H100',
    cpuCapacity: 1536,
    cpuUsed: 980,
    gpuCapacity: 128,
    gpuUsed: 86,
    pendingJobs: 3,
    runningJobs: 6,
    preemptionCount: 2,
  },
  {
    id: 'cq-gpu-a100',
    name: 'cq-gpu-a100',
    poolId: 'pool-a100',
    poolName: 'GPU — A100',
    cpuCapacity: 1536,
    cpuUsed: 720,
    gpuCapacity: 128,
    gpuUsed: 72,
    pendingJobs: 1,
    runningJobs: 9,
    preemptionCount: 0,
  },
  {
    id: 'cq-inference',
    name: 'cq-inference',
    poolId: 'pool-dedicated',
    poolName: '推理专属',
    cpuCapacity: 384,
    cpuUsed: 210,
    gpuCapacity: 32,
    gpuUsed: 18,
    pendingJobs: 0,
    runningJobs: 7,
    preemptionCount: 0,
  },
];

/* ---------- Queued Tasks ------------------------------------------------- */

export interface QueuedTask {
  id: string;
  name: string;
  workspaceId: string;
  queueName: string;
  gpuRequested: number;
  gpuType: 'H100' | 'A100' | 'g5';
  submittedAt: string;
  priority: 'high' | 'medium' | 'low';
  waitSeconds: number;
}

export const mockQueuedTasks: QueuedTask[] = [
  {
    id: 'job-q-001',
    name: 'llama3-8b-sft-r7',
    workspaceId: 'ws-001',
    queueName: 'cq-gpu-h100',
    gpuRequested: 16,
    gpuType: 'H100',
    submittedAt: new Date(Date.now() - 18 * 60_000).toISOString(),
    priority: 'high',
    waitSeconds: 1080,
  },
  {
    id: 'job-q-002',
    name: 'qwen72b-continue-pretrain',
    workspaceId: 'ws-001',
    queueName: 'cq-gpu-h100',
    gpuRequested: 32,
    gpuType: 'H100',
    submittedAt: new Date(Date.now() - 55 * 60_000).toISOString(),
    priority: 'high',
    waitSeconds: 3300,
  },
  {
    id: 'job-q-003',
    name: 'resnet50-imagenet-baseline',
    workspaceId: 'ws-002',
    queueName: 'cq-gpu-a100',
    gpuRequested: 8,
    gpuType: 'A100',
    submittedAt: new Date(Date.now() - 7 * 60_000).toISOString(),
    priority: 'medium',
    waitSeconds: 420,
  },
  {
    id: 'job-q-004',
    name: 'yolo-annotation-tuning',
    workspaceId: 'ws-002',
    queueName: 'cq-gpu-a100',
    gpuRequested: 4,
    gpuType: 'A100',
    submittedAt: new Date(Date.now() - 3 * 60_000).toISOString(),
    priority: 'low',
    waitSeconds: 180,
  },
  {
    id: 'job-q-005',
    name: 'mistral7b-dpo-exp12',
    workspaceId: 'ws-001',
    queueName: 'cq-gpu-h100',
    gpuRequested: 8,
    gpuType: 'H100',
    submittedAt: new Date(Date.now() - 34 * 60_000).toISOString(),
    priority: 'medium',
    waitSeconds: 2040,
  },
  {
    id: 'job-q-006',
    name: 'rec-ranking-nightly',
    workspaceId: 'ws-003',
    queueName: 'cq-gpu-a100',
    gpuRequested: 16,
    gpuType: 'A100',
    submittedAt: new Date(Date.now() - 12 * 60_000).toISOString(),
    priority: 'medium',
    waitSeconds: 720,
  },
  {
    id: 'job-q-007',
    name: 'rec-user-features-etl',
    workspaceId: 'ws-003',
    queueName: 'cq-general',
    gpuRequested: 0,
    gpuType: 'g5',
    submittedAt: new Date(Date.now() - 2 * 60_000).toISOString(),
    priority: 'low',
    waitSeconds: 120,
  },
  {
    id: 'job-q-008',
    name: 'stable-diffusion-finetune',
    workspaceId: 'ws-002',
    queueName: 'cq-gpu-h100',
    gpuRequested: 8,
    gpuType: 'H100',
    submittedAt: new Date(Date.now() - 22 * 60_000).toISOString(),
    priority: 'medium',
    waitSeconds: 1320,
  },
];

/* ---------- Quota Matrix ------------------------------------------------ */

export interface QuotaCell {
  quota: number;
  used: number;
}

export interface QuotaRow {
  workspaceId: string;
  cells: Record<string, QuotaCell>; // keyed by poolId
}

export const mockQuotaMatrix: QuotaRow[] = [
  {
    workspaceId: 'ws-001',
    cells: {
      'pool-general': { quota: 120, used: 82 },
      'pool-h100': { quota: 72, used: 56 },
      'pool-a100': { quota: 48, used: 30 },
      'pool-dedicated': { quota: 12, used: 8 },
    },
  },
  {
    workspaceId: 'ws-002',
    cells: {
      'pool-general': { quota: 64, used: 40 },
      'pool-h100': { quota: 32, used: 22 },
      'pool-a100': { quota: 40, used: 18 },
      'pool-dedicated': { quota: 10, used: 6 },
    },
  },
  {
    workspaceId: 'ws-003',
    cells: {
      'pool-general': { quota: 72, used: 46 },
      'pool-h100': { quota: 16, used: 8 },
      'pool-a100': { quota: 40, used: 24 },
      'pool-dedicated': { quota: 10, used: 4 },
    },
  },
];

/* ---------- Network ----------------------------------------------------- */

export interface Subnet {
  id: string;
  cidr: string;
  az: string;
  type: 'Public' | 'Private';
  availableIps: number;
  totalIps: number;
}

export interface SecurityGroupRule {
  direction: 'Ingress' | 'Egress';
  protocol: 'tcp' | 'udp' | 'icmp' | '-1';
  fromPort: number;
  toPort: number;
  source: string;
  description: string;
}

export interface SecurityGroup {
  id: string;
  name: string;
  description: string;
  rules: SecurityGroupRule[];
}

export interface VpcEndpoint {
  id: string;
  serviceName: string;
  type: 'Interface' | 'Gateway';
  status: 'available' | 'pending';
  az: string[];
}

export interface NatGateway {
  id: string;
  subnetId: string;
  status: 'available' | 'pending' | 'failed';
  elasticIp: string;
}

export interface NetworkInfo {
  vpc: {
    id: string;
    cidr: string;
    region: string;
    createdAt: string;
    dnsSupport: boolean;
    dnsHostnames: boolean;
  };
  subnets: Subnet[];
  securityGroups: SecurityGroup[];
  endpoints: VpcEndpoint[];
  natGateways: NatGateway[];
}

export const mockNetworkInfo: NetworkInfo = {
  vpc: {
    id: 'vpc-0a1b2c3d4e5f6a7b8',
    cidr: '10.0.0.0/16',
    region: 'us-west-2',
    createdAt: '2025-06-10T08:12:00Z',
    dnsSupport: true,
    dnsHostnames: true,
  },
  subnets: [
    { id: 'subnet-0a11', cidr: '10.0.1.0/24', az: 'us-west-2a', type: 'Public', availableIps: 238, totalIps: 251 },
    { id: 'subnet-0a12', cidr: '10.0.2.0/24', az: 'us-west-2b', type: 'Public', availableIps: 242, totalIps: 251 },
    { id: 'subnet-0a13', cidr: '10.0.3.0/24', az: 'us-west-2c', type: 'Public', availableIps: 245, totalIps: 251 },
    { id: 'subnet-0a21', cidr: '10.0.11.0/24', az: 'us-west-2a', type: 'Private', availableIps: 180, totalIps: 251 },
    { id: 'subnet-0a22', cidr: '10.0.12.0/24', az: 'us-west-2b', type: 'Private', availableIps: 192, totalIps: 251 },
    { id: 'subnet-0a23', cidr: '10.0.13.0/24', az: 'us-west-2c', type: 'Private', availableIps: 207, totalIps: 251 },
    { id: 'subnet-0a31', cidr: '10.0.21.0/24', az: 'us-west-2a', type: 'Private', availableIps: 120, totalIps: 251 },
    { id: 'subnet-0a32', cidr: '10.0.22.0/24', az: 'us-west-2b', type: 'Private', availableIps: 148, totalIps: 251 },
  ],
  securityGroups: [
    {
      id: 'sg-0001a',
      name: 'hyperpod-cluster-sg',
      description: 'HyperPod cluster control plane SG',
      rules: [
        { direction: 'Ingress', protocol: 'tcp', fromPort: 443, toPort: 443, source: '10.0.0.0/16', description: 'K8s API' },
        { direction: 'Ingress', protocol: 'tcp', fromPort: 10250, toPort: 10250, source: 'sg-0001a', description: 'kubelet' },
        { direction: 'Egress', protocol: '-1', fromPort: 0, toPort: 0, source: '0.0.0.0/0', description: 'Allow all egress' },
      ],
    },
    {
      id: 'sg-0002b',
      name: 'hyperpod-node-sg',
      description: 'HyperPod worker node SG',
      rules: [
        { direction: 'Ingress', protocol: 'tcp', fromPort: 22, toPort: 22, source: '10.0.0.0/16', description: 'SSH from VPC' },
        { direction: 'Ingress', protocol: 'tcp', fromPort: 2379, toPort: 2380, source: 'sg-0002b', description: 'etcd peer' },
        { direction: 'Ingress', protocol: '-1', fromPort: 0, toPort: 0, source: 'sg-0001a', description: 'From control plane' },
        { direction: 'Egress', protocol: '-1', fromPort: 0, toPort: 0, source: '0.0.0.0/0', description: 'Allow all egress' },
      ],
    },
    {
      id: 'sg-0003c',
      name: 'fsx-lustre-sg',
      description: 'FSx for Lustre file system SG',
      rules: [
        { direction: 'Ingress', protocol: 'tcp', fromPort: 988, toPort: 988, source: 'sg-0002b', description: 'Lustre' },
        { direction: 'Ingress', protocol: 'tcp', fromPort: 1021, toPort: 1023, source: 'sg-0002b', description: 'Lustre' },
      ],
    },
    {
      id: 'sg-0004d',
      name: 'inference-alb-sg',
      description: 'Public ALB for inference endpoints',
      rules: [
        { direction: 'Ingress', protocol: 'tcp', fromPort: 443, toPort: 443, source: '0.0.0.0/0', description: 'HTTPS' },
        { direction: 'Ingress', protocol: 'tcp', fromPort: 80, toPort: 80, source: '0.0.0.0/0', description: 'HTTP redirect' },
      ],
    },
  ],
  endpoints: [
    { id: 'vpce-01', serviceName: 'com.amazonaws.us-west-2.s3', type: 'Gateway', status: 'available', az: ['us-west-2a', 'us-west-2b', 'us-west-2c'] },
    { id: 'vpce-02', serviceName: 'com.amazonaws.us-west-2.ecr.api', type: 'Interface', status: 'available', az: ['us-west-2a', 'us-west-2b'] },
    { id: 'vpce-03', serviceName: 'com.amazonaws.us-west-2.ecr.dkr', type: 'Interface', status: 'available', az: ['us-west-2a', 'us-west-2b'] },
    { id: 'vpce-04', serviceName: 'com.amazonaws.us-west-2.logs', type: 'Interface', status: 'available', az: ['us-west-2a', 'us-west-2b', 'us-west-2c'] },
    { id: 'vpce-05', serviceName: 'com.amazonaws.us-west-2.monitoring', type: 'Interface', status: 'available', az: ['us-west-2a', 'us-west-2b'] },
    { id: 'vpce-06', serviceName: 'com.amazonaws.us-west-2.ssm', type: 'Interface', status: 'available', az: ['us-west-2a', 'us-west-2b'] },
    { id: 'vpce-07', serviceName: 'com.amazonaws.us-west-2.ssmmessages', type: 'Interface', status: 'available', az: ['us-west-2a', 'us-west-2b'] },
    { id: 'vpce-08', serviceName: 'com.amazonaws.us-west-2.ec2messages', type: 'Interface', status: 'available', az: ['us-west-2a', 'us-west-2b'] },
    { id: 'vpce-09', serviceName: 'com.amazonaws.us-west-2.sagemaker.api', type: 'Interface', status: 'available', az: ['us-west-2a', 'us-west-2b'] },
    { id: 'vpce-10', serviceName: 'com.amazonaws.us-west-2.sagemaker.runtime', type: 'Interface', status: 'available', az: ['us-west-2a', 'us-west-2b'] },
    { id: 'vpce-11', serviceName: 'com.amazonaws.us-west-2.sts', type: 'Interface', status: 'available', az: ['us-west-2a', 'us-west-2b', 'us-west-2c'] },
    { id: 'vpce-12', serviceName: 'com.amazonaws.us-west-2.elasticfilesystem', type: 'Interface', status: 'available', az: ['us-west-2a', 'us-west-2b'] },
    { id: 'vpce-13', serviceName: 'com.amazonaws.us-west-2.kms', type: 'Interface', status: 'available', az: ['us-west-2a', 'us-west-2b'] },
    { id: 'vpce-14', serviceName: 'com.amazonaws.us-west-2.secretsmanager', type: 'Interface', status: 'pending', az: ['us-west-2a', 'us-west-2b'] },
  ],
  natGateways: [
    { id: 'nat-0a1b', subnetId: 'subnet-0a11', status: 'available', elasticIp: '34.216.88.17' },
    { id: 'nat-0a2b', subnetId: 'subnet-0a12', status: 'available', elasticIp: '34.216.102.44' },
    { id: 'nat-0a3b', subnetId: 'subnet-0a13', status: 'available', elasticIp: '34.216.129.9' },
  ],
};

/* ---------- Ops Events -------------------------------------------------- */

export type EventSeverity = 'info' | 'warning' | 'error';
export type EventKind =
  | 'node-failure'
  | 'node-replaced'
  | 'cluster-upgrade'
  | 'quota-change'
  | 'queue-preempt'
  | 'addon-update'
  | 'scale';

export interface OpsEvent {
  id: string;
  ts: string;
  kind: EventKind;
  severity: EventSeverity;
  title: string;
  detail: string;
  source: string;
  targetId?: string;
}

const now = Date.now();
const ago = (minutes: number): string => new Date(now - minutes * 60_000).toISOString();

export const mockOpsEvents: OpsEvent[] = [
  { id: 'evt-001', ts: ago(3), kind: 'node-failure', severity: 'error', title: 'H100 节点 ECC 错误', detail: 'i-017a8b7c6d5e4f3 GPU0 出现 uncorrectable ECC,已标记 NotReady', source: 'HealthMonitoring', targetId: 'i-017a8b7c6d5e4f3' },
  { id: 'evt-002', ts: ago(12), kind: 'queue-preempt', severity: 'warning', title: 'Kueue 抢占触发', detail: 'cq-gpu-h100 抢占 2 个低优先级任务,为 llama3-8b-sft-r7 释放 16 卡', source: 'Kueue Controller' },
  { id: 'evt-003', ts: ago(28), kind: 'node-replaced', severity: 'info', title: '故障节点替换完成', detail: 'i-018f4c... 替换为 i-019b2a..., 约 11 分钟', source: 'HealthMonitoring' },
  { id: 'evt-004', ts: ago(42), kind: 'quota-change', severity: 'info', title: 'Workspace 配额调整', detail: 'ws-002 H100 配额 28 → 32 卡,操作人 alice@example.com', source: 'Admin Console' },
  { id: 'evt-005', ts: ago(67), kind: 'addon-update', severity: 'warning', title: 'training-operator 升级失败', detail: 'v1.7.2 → v1.8.0 超时 10 分钟,已回滚', source: 'Addon Controller' },
  { id: 'evt-006', ts: ago(90), kind: 'scale', severity: 'info', title: '资源池扩容', detail: 'gpu-h100-pool 节点数 14 → 16', source: 'AutoScaler' },
  { id: 'evt-007', ts: ago(125), kind: 'node-failure', severity: 'error', title: 'NotReady — kubelet 失联', detail: 'i-020c8d... kubelet 连续 5 min 未上报', source: 'HealthMonitoring', targetId: 'i-020c8d7e6f5a4b3' },
  { id: 'evt-008', ts: ago(160), kind: 'cluster-upgrade', severity: 'info', title: '集群版本升级准备', detail: 'EKS 1.30 → 1.31 已创建升级计划,预计耗时 45 min', source: 'Cluster Manager' },
  { id: 'evt-009', ts: ago(210), kind: 'queue-preempt', severity: 'warning', title: 'Kueue 抢占触发', detail: 'cq-gpu-a100 抢占 1 个训练任务', source: 'Kueue Controller' },
  { id: 'evt-010', ts: ago(280), kind: 'node-replaced', severity: 'info', title: '故障节点替换完成', detail: 'i-015d9... 替换为 i-017a8..., 约 8 分钟', source: 'HealthMonitoring' },
  { id: 'evt-011', ts: ago(340), kind: 'quota-change', severity: 'info', title: 'Workspace 配额调整', detail: 'ws-003 A100 配额 32 → 40 卡', source: 'Admin Console' },
  { id: 'evt-012', ts: ago(400), kind: 'addon-update', severity: 'info', title: 'vpc-cni 升级成功', detail: 'v1.19.0 → v1.19.2-eksbuild.1', source: 'Addon Controller' },
  { id: 'evt-013', ts: ago(520), kind: 'node-failure', severity: 'warning', title: 'GPU 温度告警', detail: 'i-016b2c... GPU3 持续高温 88°C', source: 'HealthMonitoring' },
  { id: 'evt-014', ts: ago(640), kind: 'scale', severity: 'info', title: '推理池缩容', detail: 'dedicated-inference-pool 节点数 10 → 8', source: 'AutoScaler' },
  { id: 'evt-015', ts: ago(780), kind: 'cluster-upgrade', severity: 'info', title: 'kueue 升级完成', detail: 'v0.8.1 → v0.9.1,已重启 scheduler', source: 'Addon Controller' },
  { id: 'evt-016', ts: ago(920), kind: 'node-replaced', severity: 'info', title: '批量节点替换', detail: '因 AMI 安全补丁,替换 p4d 节点 4 台', source: 'HealthMonitoring' },
  { id: 'evt-017', ts: ago(1100), kind: 'quota-change', severity: 'info', title: 'Workspace 新增', detail: '新建 team-c-recsys,初始 H100 配额 16 卡', source: 'Admin Console' },
  { id: 'evt-018', ts: ago(1320), kind: 'node-failure', severity: 'error', title: 'NVLink 拓扑错误', detail: 'i-018f4c... NVLink 拓扑检测失败,需人工介入', source: 'HealthMonitoring' },
  { id: 'evt-019', ts: ago(1500), kind: 'scale', severity: 'info', title: '资源池扩容', detail: 'gpu-a100-pool 节点数 12 → 16', source: 'AutoScaler' },
  { id: 'evt-020', ts: ago(1800), kind: 'addon-update', severity: 'info', title: 'fsx-csi-driver 升级', detail: 'v1.10.0 → v1.11.0', source: 'Addon Controller' },
  { id: 'evt-021', ts: ago(2160), kind: 'queue-preempt', severity: 'info', title: 'Kueue 空闲回收', detail: '通用池回收 24 卡空闲容量', source: 'Kueue Controller' },
  { id: 'evt-022', ts: ago(2640), kind: 'cluster-upgrade', severity: 'info', title: 'EKS 访问策略更新', detail: 'Access Entries 从 11 增加到 14', source: 'Cluster Manager' },
];

/* ---------- Audit Logs -------------------------------------------------- */

export type AuditAction = 'create' | 'update' | 'delete' | 'scale' | 'login';

export interface AuditLog {
  id: string;
  ts: string;
  operatorEmail: string;
  operatorRole: 'admin' | 'user' | 'viewer';
  action: AuditAction;
  resourceType: string;
  targetId: string;
  workspaceId?: string;
  ip: string;
  result: 'success' | 'failure';
  detail: string;
}

const ADMIN_EMAIL = mockUsers[0]!.email;
const USER_EMAIL_1 = mockUsers[1]!.email;
const USER_EMAIL_2 = mockUsers[2]!.email;

export const mockAuditLogs: AuditLog[] = [
  { id: 'log-001', ts: ago(4),   operatorEmail: ADMIN_EMAIL, operatorRole: 'admin', action: 'update', resourceType: 'ResourcePool', targetId: 'pool-h100', ip: '10.0.11.42', result: 'success', detail: '扩容 H100 池节点数 14 → 16' },
  { id: 'log-002', ts: ago(9),   operatorEmail: USER_EMAIL_1, operatorRole: 'user', action: 'create', resourceType: 'TrainingJob', targetId: 'job-llama3-8b-sft-r7', workspaceId: 'ws-001', ip: '10.0.12.88', result: 'success', detail: '提交训练任务,16 卡 H100' },
  { id: 'log-003', ts: ago(17),  operatorEmail: ADMIN_EMAIL, operatorRole: 'admin', action: 'update', resourceType: 'Quota', targetId: 'ws-002/pool-h100', workspaceId: 'ws-002', ip: '10.0.11.42', result: 'success', detail: '配额 28 → 32 卡' },
  { id: 'log-004', ts: ago(22),  operatorEmail: USER_EMAIL_2, operatorRole: 'user', action: 'create', resourceType: 'InferenceService', targetId: 'svc-qwen72b-v2', workspaceId: 'ws-001', ip: '10.0.13.10', result: 'success', detail: '部署推理服务 2 副本' },
  { id: 'log-005', ts: ago(35),  operatorEmail: USER_EMAIL_1, operatorRole: 'user', action: 'delete', resourceType: 'DevInstance', targetId: 'dev-alice-notebook-7', workspaceId: 'ws-001', ip: '10.0.12.88', result: 'success', detail: '删除开发机' },
  { id: 'log-006', ts: ago(48),  operatorEmail: ADMIN_EMAIL, operatorRole: 'admin', action: 'scale', resourceType: 'InstanceGroup', targetId: 'ig-002', ip: '10.0.11.42', result: 'success', detail: 'H100 group 扩容' },
  { id: 'log-007', ts: ago(62),  operatorEmail: USER_EMAIL_2, operatorRole: 'user', action: 'update', resourceType: 'TrainingJob', targetId: 'job-resnet50-baseline', workspaceId: 'ws-002', ip: '10.0.13.10', result: 'failure', detail: '修改超参失败: job 已 Running' },
  { id: 'log-008', ts: ago(80),  operatorEmail: ADMIN_EMAIL, operatorRole: 'admin', action: 'create', resourceType: 'FsxPermissionGroup', targetId: 'pg-008', ip: '10.0.11.42', result: 'success', detail: '新建 shared-models-ro 权限组' },
  { id: 'log-009', ts: ago(104), operatorEmail: USER_EMAIL_1, operatorRole: 'user', action: 'login', resourceType: 'Session', targetId: 'sess-fa82', ip: '10.0.12.88', result: 'success', detail: 'SSO 登录' },
  { id: 'log-010', ts: ago(130), operatorEmail: ADMIN_EMAIL, operatorRole: 'admin', action: 'delete', resourceType: 'ResourcePool', targetId: 'pool-legacy-k80', ip: '10.0.11.42', result: 'success', detail: '下线老旧 K80 资源池' },
  { id: 'log-011', ts: ago(170), operatorEmail: USER_EMAIL_2, operatorRole: 'user', action: 'create', resourceType: 'Experiment', targetId: 'exp-recsys-v4', workspaceId: 'ws-003', ip: '10.0.13.77', result: 'success', detail: '新建实验' },
  { id: 'log-012', ts: ago(210), operatorEmail: ADMIN_EMAIL, operatorRole: 'admin', action: 'update', resourceType: 'EksAddon', targetId: 'training-operator', ip: '10.0.11.42', result: 'failure', detail: '升级 training-operator 失败,已回滚' },
  { id: 'log-013', ts: ago(260), operatorEmail: USER_EMAIL_1, operatorRole: 'user', action: 'create', resourceType: 'TrainingJob', targetId: 'job-mistral7b-dpo', workspaceId: 'ws-001', ip: '10.0.12.88', result: 'success', detail: '提交 DPO 训练,8 卡 H100' },
  { id: 'log-014', ts: ago(320), operatorEmail: ADMIN_EMAIL, operatorRole: 'admin', action: 'update', resourceType: 'SecurityGroup', targetId: 'sg-0002b', ip: '10.0.11.42', result: 'success', detail: '放通 Lustre 1021-1023 端口' },
  { id: 'log-015', ts: ago(400), operatorEmail: USER_EMAIL_2, operatorRole: 'user', action: 'delete', resourceType: 'InferenceService', targetId: 'svc-stale-bert', workspaceId: 'ws-002', ip: '10.0.13.10', result: 'success', detail: '下线过期推理服务' },
  { id: 'log-016', ts: ago(510), operatorEmail: ADMIN_EMAIL, operatorRole: 'admin', action: 'create', resourceType: 'Workspace', targetId: 'ws-003', ip: '10.0.11.42', result: 'success', detail: '新建 team-c-recsys workspace' },
  { id: 'log-017', ts: ago(640), operatorEmail: USER_EMAIL_1, operatorRole: 'user', action: 'update', resourceType: 'InferenceService', targetId: 'svc-qwen72b', workspaceId: 'ws-001', ip: '10.0.12.88', result: 'success', detail: '副本数 2 → 4' },
  { id: 'log-018', ts: ago(780), operatorEmail: ADMIN_EMAIL, operatorRole: 'admin', action: 'scale', resourceType: 'InstanceGroup', targetId: 'ig-004', ip: '10.0.11.42', result: 'success', detail: '推理池缩容 10 → 8' },
  { id: 'log-019', ts: ago(940), operatorEmail: USER_EMAIL_2, operatorRole: 'user', action: 'login', resourceType: 'Session', targetId: 'sess-ab33', ip: '10.0.13.10', result: 'failure', detail: 'MFA 校验失败' },
  { id: 'log-020', ts: ago(1120),operatorEmail: ADMIN_EMAIL, operatorRole: 'admin', action: 'update', resourceType: 'Quota', targetId: 'ws-003/pool-a100', workspaceId: 'ws-003', ip: '10.0.11.42', result: 'success', detail: '配额 32 → 40 卡' },
  { id: 'log-021', ts: ago(1400),operatorEmail: ADMIN_EMAIL, operatorRole: 'admin', action: 'create', resourceType: 'VpcEndpoint', targetId: 'vpce-14', ip: '10.0.11.42', result: 'success', detail: '创建 secretsmanager endpoint' },
  { id: 'log-022', ts: ago(1700),operatorEmail: USER_EMAIL_1, operatorRole: 'user', action: 'create', resourceType: 'DevInstance', targetId: 'dev-alice-vscode-12', workspaceId: 'ws-001', ip: '10.0.12.88', result: 'success', detail: '创建 VSCode 开发机,2 卡 A100' },
];

/* ---------- FSx File Systems -------------------------------------------- */

export interface FsxFileSystem {
  id: string;
  name: string;
  type: 'Lustre' | 'OpenZFS';
  capacityGiB: number;
  usedGiB: number;
  throughputMBps: number;
  mountTargets: number;
  monthlyCostUsd: number;
  createdAt: string;
  subnetIds: string[];
  deploymentType: string;
}

export const mockFsxFileSystems: FsxFileSystem[] = [
  {
    id: 'fs-0a1b2c3d4e5f6',
    name: 'hyperpod-shared-datasets',
    type: 'Lustre',
    capacityGiB: 24_576,
    usedGiB: 16_820,
    throughputMBps: 1000,
    mountTargets: 24,
    monthlyCostUsd: 3_280,
    createdAt: '2025-06-20T09:10:00Z',
    subnetIds: ['subnet-0a21', 'subnet-0a22'],
    deploymentType: 'PERSISTENT_2',
  },
  {
    id: 'fs-0f9e8d7c6b5a4',
    name: 'hyperpod-cv-images',
    type: 'Lustre',
    capacityGiB: 12_288,
    usedGiB: 8_140,
    throughputMBps: 500,
    mountTargets: 16,
    monthlyCostUsd: 1_540,
    createdAt: '2025-07-08T11:32:00Z',
    subnetIds: ['subnet-0a21'],
    deploymentType: 'PERSISTENT_2',
  },
  {
    id: 'fs-0c3b2a1d4e5f6',
    name: 'hyperpod-recsys-features',
    type: 'Lustre',
    capacityGiB: 9_600,
    usedGiB: 4_310,
    throughputMBps: 500,
    mountTargets: 12,
    monthlyCostUsd: 1_180,
    createdAt: '2025-08-14T13:48:00Z',
    subnetIds: ['subnet-0a22', 'subnet-0a23'],
    deploymentType: 'PERSISTENT_2',
  },
];

/* ---------- Mount Audit -------------------------------------------------- */

export interface MountAuditEntry {
  id: string;
  ts: string;
  userEmail: string;
  fsxId: string;
  mountPath: string;
  action: 'mount' | 'unmount';
  instanceId: string;
  workspaceId: string;
  source: 'dev' | 'training' | 'inference';
}

export const mockMountAudit: MountAuditEntry[] = [
  { id: 'm-001', ts: ago(3),   userEmail: USER_EMAIL_1, fsxId: 'fs-0a1b2c3d4e5f6', mountPath: '/fsx/shared/datasets/', action: 'mount', instanceId: 'dev-alice-vscode-12', workspaceId: 'ws-001', source: 'dev' },
  { id: 'm-002', ts: ago(15),  userEmail: USER_EMAIL_2, fsxId: 'fs-0f9e8d7c6b5a4', mountPath: '/fsx/shared/images/coco/', action: 'mount', instanceId: 'job-resnet50-baseline', workspaceId: 'ws-002', source: 'training' },
  { id: 'm-003', ts: ago(42),  userEmail: USER_EMAIL_1, fsxId: 'fs-0a1b2c3d4e5f6', mountPath: '/fsx/shared/models/llama3/', action: 'mount', instanceId: 'svc-llama3-serving', workspaceId: 'ws-001', source: 'inference' },
  { id: 'm-004', ts: ago(88),  userEmail: mockUsers[3]!.email, fsxId: 'fs-0c3b2a1d4e5f6', mountPath: '/fsx/shared/features/users/', action: 'mount', instanceId: 'job-rec-ranking', workspaceId: 'ws-003', source: 'training' },
  { id: 'm-005', ts: ago(130), userEmail: USER_EMAIL_1, fsxId: 'fs-0a1b2c3d4e5f6', mountPath: '/fsx/projects/team-a/', action: 'unmount', instanceId: 'dev-alice-notebook-7', workspaceId: 'ws-001', source: 'dev' },
  { id: 'm-006', ts: ago(205), userEmail: mockUsers[4]!.email, fsxId: 'fs-0f9e8d7c6b5a4', mountPath: '/fsx/shared/images/imagenet/', action: 'mount', instanceId: 'dev-eve-vscode-3', workspaceId: 'ws-002', source: 'dev' },
  { id: 'm-007', ts: ago(320), userEmail: USER_EMAIL_2, fsxId: 'fs-0f9e8d7c6b5a4', mountPath: '/fsx/projects/team-b/', action: 'mount', instanceId: 'job-yolo-annotation', workspaceId: 'ws-002', source: 'training' },
  { id: 'm-008', ts: ago(450), userEmail: mockUsers[5]!.email, fsxId: 'fs-0c3b2a1d4e5f6', mountPath: '/fsx/shared/features/items/', action: 'mount', instanceId: 'dev-frank-notebook-2', workspaceId: 'ws-003', source: 'dev' },
  { id: 'm-009', ts: ago(640), userEmail: ADMIN_EMAIL, fsxId: 'fs-0a1b2c3d4e5f6', mountPath: '/fsx/admin/scripts/', action: 'mount', instanceId: 'dev-alice-admin-ops', workspaceId: 'ws-001', source: 'dev' },
  { id: 'm-010', ts: ago(820), userEmail: USER_EMAIL_1, fsxId: 'fs-0a1b2c3d4e5f6', mountPath: '/fsx/shared/hf-cache/', action: 'mount', instanceId: 'job-mistral7b-dpo', workspaceId: 'ws-001', source: 'training' },
];
