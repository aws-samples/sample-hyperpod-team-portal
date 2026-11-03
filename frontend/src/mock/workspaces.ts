import type { Workspace } from '@/types';

export const mockWorkspaces: Workspace[] = [
  {
    id: 'ws-001',
    name: 'team-a-nlp',
    displayName: 'Team A — NLP',
    namespace: 'team-a-nlp',
    createdAt: '2025-09-01T10:00:00Z',
    quotaGpu: 64,
    usedGpu: 42,
    memberCount: 6,
  },
  {
    id: 'ws-002',
    name: 'team-b-cv',
    displayName: 'Team B — Computer Vision',
    namespace: 'team-b-cv',
    createdAt: '2025-09-15T10:00:00Z',
    quotaGpu: 32,
    usedGpu: 18,
    memberCount: 4,
  },
  {
    id: 'ws-003',
    name: 'team-c-recsys',
    displayName: 'Team C — RecSys',
    namespace: 'team-c-recsys',
    createdAt: '2025-10-05T10:00:00Z',
    quotaGpu: 48,
    usedGpu: 30,
    memberCount: 5,
  },
];
