"""CloudWatch Logs Insights 查询串构造 (纯函数).

CloudWatch Logs Insights 不能直接解析嵌套 JSON 标签 (
``kubernetes.labels."platform.hyperpod.io/training-job-id"``),
直接 ``= <uuid>`` 会命中 0 条. 解决方案:

1) 字符串匹配 UUID: Fluent Bit 把所有标签都嵌在每条事件的 JSON envelope
   里, UUID 全局唯一, 所以 ``@message like "<uuid>"`` 能精确定位.
2) 可选 container 过滤: 匹配 ``"container_name":"<name>`` 的 JSON 切片,
   避免撞到意外包含 container 名的无关行.
3) 返回原始 ``@message``; JSON 解析留给客户端侧 ``event_parsing.py``
   处理 (Insights ``parse`` 不允许产生名为 ``log`` 的字段 - 关键字冲突).
"""

from __future__ import annotations

from app.core.i18n import t


def build_training_job_query(
    *,
    training_job_id: str,
    container: str | None = None,
    limit: int = 500,
) -> str:
    """Compose a Logs Insights query string scoped to one training job."""
    container_clause = ""
    if container:
        # CloudWatch Insights 字符串字面量: 含双引号的 payload 用单引号包裹.
        # 匹配 JSON 切片 ``"container_name":"<name>`` 避免命中正文内容.
        container_clause = (
            f" and @message like 'container_name\":\"{container}'"
        )
    return (
        'fields @timestamp, @message'
        f' | filter @message like "{training_job_id}"'
        f'{container_clause}'
        ' | sort @timestamp asc'
        f' | limit {limit}'
    )


class InsightsQueryError(ValueError):
    """用户输入的整任务搜索表达式非法 (如正则语法错)。"""


def build_whole_task_search_query(
    *,
    training_job_id: str,
    query: str,
    is_regex: bool,
    limit: int,
) -> str:
    """整任务 (跨所有 pod) 日志搜索的 Insights 查询串。

    - label 精确匹配圈定整任务 (跨所有 pod/重启; start_query 不筛 stream, 全靠 query):
        ``filter `kubernetes.labels.platform.hyperpod.io/training-job-id` = "<job_id>"``
      ⚠️ 反引号必须包**整个字段路径** (从 kubernetes 起), 因为 label key 含 '.'/'/'
      特殊字符; 只包 key 那段解析不出字段 (实测命中 0)。
      比 @message like 子串匹配更精确 (零误命中), 扫描量相同 (性能无差异)。
    - kubernetes.container_name = "trainer": 排除 pod-manager / code-sync 等 sidecar。
    - 可选内容过滤 (限定 log 字段, 即应用正文):
        keyword → ``filter log like "<kw>"`` (子串, 大小写敏感)
        regex   → ``filter log like /<regex>/`` (Insights 正则; 支持分组/(?i))
    query 为空 → 不加内容过滤 (整任务全部)。

    返回 fields 含 @logStream (前端标来源 pod) + log + stream (stdout/stderr)。
    ⚠️ Insights 单查返回上限由 limit 定 (≤10000); 命中达 limit 视为被截断。
    """
    q = query.strip()
    parts = [
        "fields @timestamp, @logStream, log, stream",
        f'| filter `kubernetes.labels.platform.hyperpod.io/training-job-id`'
        f' = "{training_job_id}"',
        '| filter kubernetes.container_name = "trainer"',
    ]
    if q:
        if is_regex:
            # 校验正则合法性 (Insights 用的是类 PCRE; 这里用 Python re 粗验语法)
            import re

            try:
                re.compile(q)
            except re.error as exc:
                raise InsightsQueryError(t("logs.regex_syntax_error", error=exc)) from exc
            if "/" in q:  # 会闭合 like /.../ 字面量, 禁止
                raise InsightsQueryError(t("logs.regex_slash_unsupported"))
            parts.append(f"| filter log like /{q}/")
        else:
            # 关键字子串: 转义双引号 (闭合字符串字面量) 避免注入
            safe = q.replace('\\', '\\\\').replace('"', '\\"')
            parts.append(f'| filter log like "{safe}"')
    parts.append("| sort @timestamp asc")
    parts.append(f"| limit {limit}")
    return " ".join(parts)


def build_inference_whole_search_query(
    *,
    endpoint_name: str,
    query: str,
    is_regex: bool,
    limit: int,
) -> str:
    """推理整任务 (跨该 endpoint 所有 pod) 搜索的 Insights 查询串。

    推理无 training-job-id label, 改用 @logStream 前缀圈定 (前缀 = stream
    命名规则中 endpoint name 那段, 见 stream_naming.py)。主容器名 = endpoint
    name, 用它排掉 otel-collector / sidecar-reverse-proxy。

    调用方须传已校验的 endpoint_name (受 AWS 命名约束, 仅 [a-zA-Z0-9-]);
    本函数不对其做转义。

    内容过滤 (query) 逻辑与 build_whole_task_search_query 完全一致。
    """
    stream_prefix = f"FluentBit/kube.var.log.containers.{endpoint_name}-"
    q = query.strip()
    parts = [
        "fields @timestamp, @logStream, log, stream",
        f'| filter @logStream like "{stream_prefix}"',
        f'| filter kubernetes.container_name = "{endpoint_name}"',
    ]
    if q:
        if is_regex:
            import re

            try:
                re.compile(q)
            except re.error as exc:
                raise InsightsQueryError(t("logs.regex_syntax_error", error=exc)) from exc
            if "/" in q:
                raise InsightsQueryError(t("logs.regex_slash_unsupported"))
            parts.append(f"| filter log like /{q}/")
        else:
            safe = q.replace('\\', '\\\\').replace('"', '\\"')
            parts.append(f'| filter log like "{safe}"')
    parts.append("| sort @timestamp asc")
    parts.append(f"| limit {limit}")
    return " ".join(parts)


def build_llmd_whole_search_query(
    *,
    k8s_name: str,
    query: str,
    is_regex: bool,
    limit: int,
) -> str:
    """llm-d 整任务 (跨 LWS worker + gateway 所有 pod) 搜索的 Insights 查询串。

    与推理/dynamo 同构, @logStream 前缀圈定 (前缀 = CR base 名那段, 见 stream_naming.py)。
    llm-d 两类主容器: LWS 的 sglang + gateway Deployment 的 gateway → 用双容器允许过滤
    排掉 sglang pod 上的 worker-otel-collector sidecar (实测 2026-07-30 零 otel)。

    调用方须传已校验的 k8s_name (受 K8s 命名约束, 仅 [a-z0-9-]); 本函数不对其做转义。
    内容过滤 (query) 逻辑与推理/训练/dynamo 完全一致。
    """
    stream_prefix = f"FluentBit/kube.var.log.containers.{k8s_name}-"
    q = query.strip()
    parts = [
        "fields @timestamp, @logStream, log, stream",
        f'| filter @logStream like "{stream_prefix}"',
        '| filter (kubernetes.container_name = "sglang" '
        'or kubernetes.container_name = "gateway")',
    ]
    if q:
        if is_regex:
            import re

            try:
                re.compile(q)
            except re.error as exc:
                raise InsightsQueryError(t("logs.regex_syntax_error", error=exc)) from exc
            if "/" in q:
                raise InsightsQueryError(t("logs.regex_slash_unsupported"))
            parts.append(f"| filter log like /{q}/")
        else:
            safe = q.replace('\\', '\\\\').replace('"', '\\"')
            parts.append(f'| filter log like "{safe}"')
    parts.append("| sort @timestamp asc")
    parts.append(f"| limit {limit}")
    return " ".join(parts)


def build_dynamo_whole_search_query(
    *,
    k8s_cr_name: str,
    query: str,
    is_regex: bool,
    limit: int,
) -> str:
    """Dynamo (多机推理) 整任务 (跨 frontend + 所有 worker pod) 搜索的 Insights 查询串。

    与推理同构 (dynamo pod 上无 dynamo-id label 可用, 实测 2026-07-15),
    改用 @logStream 前缀圈定 (前缀 = DGD CR 名那段, 见 stream_naming.py)。
    主容器名固定 "main" (frontend/worker 都是), 用它排掉 otel-collector sidecar。

    调用方须传已校验的 k8s_cr_name (受 K8s 命名约束, 仅 [a-z0-9-]);
    本函数不对其做转义。内容过滤 (query) 逻辑与推理/训练完全一致。
    """
    stream_prefix = f"FluentBit/kube.var.log.containers.{k8s_cr_name}-"
    q = query.strip()
    parts = [
        "fields @timestamp, @logStream, log, stream",
        f'| filter @logStream like "{stream_prefix}"',
        '| filter kubernetes.container_name = "main"',
    ]
    if q:
        if is_regex:
            import re

            try:
                re.compile(q)
            except re.error as exc:
                raise InsightsQueryError(t("logs.regex_syntax_error", error=exc)) from exc
            if "/" in q:
                raise InsightsQueryError(t("logs.regex_slash_unsupported"))
            parts.append(f"| filter log like /{q}/")
        else:
            safe = q.replace('\\', '\\\\').replace('"', '\\"')
            parts.append(f'| filter log like "{safe}"')
    parts.append("| sort @timestamp asc")
    parts.append(f"| limit {limit}")
    return " ".join(parts)


def build_ray_whole_search_query(
    *,
    ray_cluster_name: str,
    query: str,
    is_regex: bool,
    limit: int,
) -> str:
    """Ray (rayjob) 整任务 (跨 head + 所有 worker pod) 搜索的 Insights 查询串。

    用 @logStream 前缀 (= rayClusterName 那段) 圈定该任务全部 pod，
    容器过滤保留主容器 ray-head / ray-worker 及 head 上的 driver 日志 sidecar
    (driver-log-tailer)，排除 worker 的 wait-gcs-ready init 容器。
    调用方须传已校验的 ray_cluster_name (受 K8s 命名约束，仅 [a-z0-9-])。
    """
    stream_prefix = f"FluentBit/kube.var.log.containers.{ray_cluster_name}-"
    q = query.strip()
    parts = [
        "fields @timestamp, @logStream, log, stream",
        f'| filter @logStream like "{stream_prefix}"',
        '| filter (kubernetes.container_name = "ray-head" '
        'or kubernetes.container_name = "ray-worker" '
        'or kubernetes.container_name = "driver-log-tailer")',
    ]
    if q:
        if is_regex:
            import re

            try:
                re.compile(q)
            except re.error as exc:
                raise InsightsQueryError(t("logs.regex_syntax_error", error=exc)) from exc
            if "/" in q:
                raise InsightsQueryError(t("logs.regex_slash_unsupported"))
            parts.append(f"| filter log like /{q}/")
        else:
            safe = q.replace('\\', '\\\\').replace('"', '\\"')
            parts.append(f'| filter log like "{safe}"')
    parts.append("| sort @timestamp asc")
    parts.append(f"| limit {limit}")
    return " ".join(parts)


def build_devinstance_whole_search_query(
    *,
    k8s_workspace_name: str,
    query: str,
    is_regex: bool,
    limit: int,
) -> str:
    """开发机整任务 (跨该开发机所有 pod 代次) 搜索的 Insights 查询串。

    与推理/dynamo 同构, @logStream 前缀圈定 (前缀 = workspace-{CR名}, 见 stream_naming.py)。
    两类容器: 主容器 workspace + init 容器 direct-ssh-init, 双容器允许过滤排掉
    ssm-agent-sidecar / workspace-init-container。

    调用方须传已校验的 k8s_workspace_name (受 K8s 命名约束, 仅 [a-z0-9-]);
    本函数不对其做转义。内容过滤 (query) 逻辑与推理/训练/dynamo 完全一致。
    """
    stream_prefix = f"FluentBit/kube.var.log.containers.workspace-{k8s_workspace_name}-"
    q = query.strip()
    parts = [
        "fields @timestamp, @logStream, log, stream",
        f'| filter @logStream like "{stream_prefix}"',
        '| filter (kubernetes.container_name = "workspace" '
        'or kubernetes.container_name = "direct-ssh-init")',
    ]
    if q:
        if is_regex:
            import re

            try:
                re.compile(q)
            except re.error as exc:
                raise InsightsQueryError(t("logs.regex_syntax_error", error=exc)) from exc
            if "/" in q:
                raise InsightsQueryError(t("logs.regex_slash_unsupported"))
            parts.append(f"| filter log like /{q}/")
        else:
            safe = q.replace('\\', '\\\\').replace('"', '\\"')
            parts.append(f'| filter log like "{safe}"')
    parts.append("| sort @timestamp asc")
    parts.append(f"| limit {limit}")
    return " ".join(parts)
