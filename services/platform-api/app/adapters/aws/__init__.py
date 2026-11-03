"""adapters/aws · AWS SDK 封装层 (aioboto3 异步).

每个 AWS service 一个文件，只暴露平台需要的最小调用集，签名稳定。
业务逻辑 (如 JSON 解析 / 策略判断) 不放在这里。

当前子模块:
    - cloudwatch_logs: CloudWatch Logs Insights 查询 (供 logs 模块使用)
"""
