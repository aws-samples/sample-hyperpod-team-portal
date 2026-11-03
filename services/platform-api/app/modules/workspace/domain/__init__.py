"""Workspace domain · 纯函数 + 类型,不依赖 IO / DB / AWS client.

- `aws_team_mapping` · Workspace ↔ AWS SageMaker HyperPod Team/ComputeQuota 映射
- `namespace_spec` · K8s namespace 命名规范 + NetworkPolicy / ResourceQuota 契约

禁止在此层做任何副作用: 任何 `await db.*` / `await client.*` / `raise HTTPException`
都属于 orchestration 层的职责。
"""
