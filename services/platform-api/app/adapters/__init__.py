"""adapters · 对外部系统 (K8s / AWS / Prometheus / ...) 的封装层.

每个子包对应一种外部系统, 暴露平台侧需要的最小异步调用集。
业务逻辑 (策略判断 / 解析 / 重试) 不放在这里。

当前子包:
    - k8s: Kubernetes 异步客户端, 按 CR kind 分文件组织
    - aws: CloudWatch Logs Insights / SageMaker 等 (boto3 async 封装)
    - prometheus: AMP 查询客户端
"""
