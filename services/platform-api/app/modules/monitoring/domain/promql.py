"""PromQL templates for training jobs and dev instances.

Template variables (substituted by backend before sending to the frontend):
  $namespace     - k8s namespace (e.g. hyperpod-ns-team-ddp)
  $job_name      - k8s Job / HPJ CR name (e.g. hpj-e2e-38dceb)
  $pod_name      - pod name (e.g. workspace-linnjia-gpu-test-c8922a-...)
  $pod_regex     - pod name regex (e.g. "hpj-e2e-38dceb-pods-.*")
  $node_regex    - alternation of node names hosting this job's pods
                   (e.g. "hyperpod-i-aaa|hyperpod-i-bbb"), or ".*" when none

The training template set covers 3 concerns:
1. GPU hardware (DCGM): util / memory / temperature / power / NVLink health
2. Pod resources (cAdvisor): CPU / memory / network
3. Training-level (HyperPod Training Operator `training_*` metrics,
   only populated when the training script uses hyperpod-elastic-agent
   hooks; shows "暂无数据" for plain-python jobs — expected).
"""

from __future__ import annotations

from typing import Any

from app.modules.monitoring.api.schemas import QueryTemplate


def _tpl(**kw: Any) -> QueryTemplate:
    """模板定义只含结构字段; title / description / group 展示名由 template_subst.localize_template
    按请求语言从文案表 (app/locales/*/monitoring.json, key=monitoring.tpl.<key>.*) 填入。
    unit 一般是语言无关的符号; 文案表里有 monitoring.tpl.<key>.unit 时 (原为中文单位) 以文案表为准。"""
    return QueryTemplate(title="", **kw)


# ============================================================
# 训练任务 · Training Job (11 指标 · 3 组: GPU 硬件 · 训练状态 · Pod 资源)
# ============================================================

TRAINING_TEMPLATES: list[QueryTemplate] = [
    # ============================================================
    # Job 维度 (整任务聚合 · 一条线/一组数字)
    # ============================================================
    _tpl(
        key="job_gpu_util_avg",
        unit="%",
        category="gpu",
        dimension="job",
        promql='avg(DCGM_FI_DEV_GPU_UTIL{namespace="$namespace",pod=~"$pod_regex"})',
    ),
    _tpl(
        key="job_gpu_mem_used_gib_sum",
        unit="GiB",
        category="gpu",
        dimension="job",
        promql='sum(DCGM_FI_DEV_FB_USED{namespace="$namespace",pod=~"$pod_regex"}) / 1024',
    ),
    _tpl(
        key="job_cpu_usage_cores",
        unit="cores",
        category="cpu",
        dimension="job",
        promql=(
            'sum(rate('
            'container_cpu_usage_seconds_total{'
            'namespace="$namespace",pod=~"$pod_regex",container!=""}[2m]))'
        ),
    ),
    _tpl(
        key="job_mem_usage_gib",
        unit="GiB",
        category="memory",
        dimension="job",
        promql=(
            'sum(container_memory_working_set_bytes{'
            'namespace="$namespace",pod=~"$pod_regex",container!=""}) '
            '/ 1024 / 1024 / 1024'
        ),
    ),
    _tpl(
        key="job_network_rx_bytes",
        unit="bytes/s",
        category="network",
        dimension="job",
        promql=(
            'sum(rate('
            'container_network_receive_bytes_total{'
            'namespace="$namespace",pod=~"$pod_regex"}[2m]))'
        ),
    ),
    # ---------- HyperPod Training Operator 任务级指标 ----------
    _tpl(
        key="training_uptime_percentage",
        unit="%",
        category="training",
        dimension="job",
        promql='training_uptime_percentage{job_name="$job_name"}',
    ),
    _tpl(
        key="training_fault_count",
        unit="count",
        category="training",
        dimension="job",
        promql='training_fault_count{job_name="$job_name"}',
    ),
    # Training Operator 自身指标 (hyperpod_training_operator_*, label jobName 大小写敏感)
    _tpl(
        key="training_operator_jobs_created",
        unit="count",
        category="training",
        dimension="job",
        promql='hyperpod_training_operator_jobs_created_total{jobName="$job_name"}',
    ),
    _tpl(
        key="training_operator_jobs_successful",
        unit="count",
        category="training",
        dimension="job",
        promql='hyperpod_training_operator_jobs_successful_total{jobName="$job_name"}',
    ),
    _tpl(
        key="training_operator_jobs_deleted",
        unit="count",
        category="training",
        dimension="job",
        promql='hyperpod_training_operator_jobs_deleted_total{jobName="$job_name"}',
    ),
    _tpl(
        key="training_operator_jobs_managed_by_kueue",
        unit="count",
        category="training",
        dimension="job",
        promql='hyperpod_training_operator_jobs_managed_by_kueue_total{jobName="$job_name"}',
    ),

    # ============================================================
    # Pod 维度 (按 Pod 分线 · DDP 每 rank 一条)
    # ============================================================
    _tpl(
        key="pod_cpu_usage_cores",
        unit="cores",
        category="cpu",
        dimension="pod",
        promql=(
            'sum by (pod) (rate('
            'container_cpu_usage_seconds_total{'
            'namespace="$namespace",pod=~"$pod_regex",container!=""}[2m]))'
        ),
    ),
    _tpl(
        key="pod_mem_usage_gib",
        unit="GiB",
        category="memory",
        dimension="pod",
        promql=(
            'sum by (pod) ('
            'container_memory_working_set_bytes{'
            'namespace="$namespace",pod=~"$pod_regex",container!=""}) '
            '/ 1024 / 1024 / 1024'
        ),
    ),
    _tpl(
        key="pod_network_rx_bytes",
        unit="bytes/s",
        category="network",
        dimension="pod",
        promql=(
            'sum by (pod) (rate('
            'container_network_receive_bytes_total{'
            'namespace="$namespace",pod=~"$pod_regex"}[2m]))'
        ),
    ),
    _tpl(
        key="pod_network_tx_bytes",
        unit="bytes/s",
        category="network",
        dimension="pod",
        promql=(
            'sum by (pod) (rate('
            'container_network_transmit_bytes_total{'
            'namespace="$namespace",pod=~"$pod_regex"}[2m]))'
        ),
    ),

    # ============================================================
    # GPUCard 维度 (按 GPU 卡分线 · 每节点 4-8 卡)
    # ============================================================
    _tpl(
        key="gpu_card_util",
        unit="%",
        category="gpu",
        dimension="gpu_card",
        promql='DCGM_FI_DEV_GPU_UTIL{namespace="$namespace",pod=~"$pod_regex"}',
    ),
    _tpl(
        key="gpu_card_mem_used_gib",
        unit="GiB",
        category="gpu",
        dimension="gpu_card",
        promql='DCGM_FI_DEV_FB_USED{namespace="$namespace",pod=~"$pod_regex"} / 1024',
    ),
    _tpl(
        key="gpu_card_temp",
        unit="°C",
        category="gpu",
        dimension="gpu_card",
        promql='DCGM_FI_DEV_GPU_TEMP{namespace="$namespace",pod=~"$pod_regex"}',
    ),
    _tpl(
        key="gpu_card_power",
        unit="W",
        category="gpu",
        dimension="gpu_card",
        promql='DCGM_FI_DEV_POWER_USAGE{namespace="$namespace",pod=~"$pod_regex"}',
    ),
    _tpl(
        key="gpu_card_nvlink_errors",
        unit="count",
        category="gpu",
        dimension="gpu_card",
        promql=(
            '(DCGM_FI_DEV_NVLINK_RECOVERY_ERROR_COUNT_TOTAL{namespace="$namespace",pod=~"$pod_regex"} '
            'or on(Hostname,gpu) '
            'DCGM_FI_DEV_NVLINK_REPLAY_ERROR_COUNT_TOTAL{namespace="$namespace",pod=~"$pod_regex"} * 0)'
            ' + on(Hostname,gpu) '
            '(DCGM_FI_DEV_NVLINK_REPLAY_ERROR_COUNT_TOTAL{namespace="$namespace",pod=~"$pod_regex"} '
            'or on(Hostname,gpu) '
            'DCGM_FI_DEV_NVLINK_RECOVERY_ERROR_COUNT_TOTAL{namespace="$namespace",pod=~"$pod_regex"} * 0)'
        ),
    ),

    # ============================================================
    # 扩展: Job 维度 (网络出 / 显存占比 / 磁盘 IO / Pod 数)
    # ============================================================
    _tpl(
        key="job_network_tx_bytes",
        unit="bytes/s",
        category="network",
        dimension="job",
        promql=(
            'sum(rate('
            'container_network_transmit_bytes_total{'
            'namespace="$namespace",pod=~"$pod_regex"}[2m]))'
        ),
    ),
    _tpl(
        key="job_gpu_mem_util_avg",
        unit="%",
        category="gpu",
        dimension="job",
        promql='avg(DCGM_FI_DEV_MEM_COPY_UTIL{namespace="$namespace",pod=~"$pod_regex"})',
    ),
    _tpl(
        key="job_disk_read_bytes",
        unit="bytes/s",
        category="disk",
        dimension="job",
        promql=(
            'sum(rate('
            'container_fs_reads_bytes_total{'
            'namespace="$namespace",pod=~"$pod_regex",container!=""}[2m]))'
        ),
    ),
    _tpl(
        key="job_disk_write_bytes",
        unit="bytes/s",
        category="disk",
        dimension="job",
        promql=(
            'sum(rate('
            'container_fs_writes_bytes_total{'
            'namespace="$namespace",pod=~"$pod_regex",container!=""}[2m]))'
        ),
    ),
    _tpl(
        key="job_oom_events",
        unit="count/s",
        category="memory",
        dimension="job",
        promql=(
            'sum(rate('
            'container_oom_events_total{'
            'namespace="$namespace",pod=~"$pod_regex"}[5m]))'
        ),
    ),
    _tpl(
        key="job_cpu_throttled_seconds",
        unit="s/s",
        category="cpu",
        dimension="job",
        promql=(
            'sum(rate('
            'container_cpu_cfs_throttled_seconds_total{'
            'namespace="$namespace",pod=~"$pod_regex",container!=""}[2m]))'
        ),
    ),
    _tpl(
        key="job_net_rx_dropped",
        unit="pkts/s",
        category="network",
        dimension="job",
        promql=(
            'sum(rate('
            'container_network_receive_packets_dropped_total{'
            'namespace="$namespace",pod=~"$pod_regex"}[2m]))'
        ),
    ),
    _tpl(
        key="job_net_tx_dropped",
        unit="pkts/s",
        category="network",
        dimension="job",
        promql=(
            'sum(rate('
            'container_network_transmit_packets_dropped_total{'
            'namespace="$namespace",pod=~"$pod_regex"}[2m]))'
        ),
    ),
    _tpl(
        key="job_pod_count",
        unit="count",
        category="status",
        dimension="job",
        promql=(
            'count(kube_pod_info{'
            'namespace="$namespace",pod=~"$pod_regex"})'
        ),
    ),

    # ============================================================
    # 扩展: Pod 维度 (磁盘 IO / 重启次数)
    # ============================================================
    _tpl(
        key="pod_disk_read_bytes",
        unit="bytes/s",
        category="disk",
        dimension="pod",
        promql=(
            'sum by (pod) (rate('
            'container_fs_reads_bytes_total{'
            'namespace="$namespace",pod=~"$pod_regex",container!=""}[2m]))'
        ),
    ),
    _tpl(
        key="pod_disk_write_bytes",
        unit="bytes/s",
        category="disk",
        dimension="pod",
        promql=(
            'sum by (pod) (rate('
            'container_fs_writes_bytes_total{'
            'namespace="$namespace",pod=~"$pod_regex",container!=""}[2m]))'
        ),
    ),
    _tpl(
        key="pod_restart_count",
        unit="count",
        category="status",
        dimension="pod",
        promql=(
            'sum by (pod) ('
            'kube_pod_container_status_restarts_total{'
            'namespace="$namespace",pod=~"$pod_regex"})'
        ),
    ),

    # ============================================================
    # 扩展: GPUCard 维度 (显存占比 / SM 活跃 / PCIe / XID 错)
    # ============================================================
    _tpl(
        key="gpu_card_mem_util",
        unit="%",
        category="gpu",
        dimension="gpu_card",
        promql='DCGM_FI_DEV_MEM_COPY_UTIL{namespace="$namespace",pod=~"$pod_regex"}',
    ),
    _tpl(
        key="gpu_card_sm_active",
        unit="ratio",
        category="gpu",
        dimension="gpu_card",
        promql='DCGM_FI_PROF_SM_ACTIVE{namespace="$namespace",pod=~"$pod_regex"}',
    ),
    _tpl(
        key="gpu_card_tensor_active",
        unit="ratio",
        category="gpu",
        dimension="gpu_card",
        promql='DCGM_FI_PROF_PIPE_TENSOR_ACTIVE{namespace="$namespace",pod=~"$pod_regex"}',
    ),
    _tpl(
        key="gpu_card_gr_engine_active",
        unit="ratio",
        category="gpu",
        dimension="gpu_card",
        promql='DCGM_FI_PROF_GR_ENGINE_ACTIVE{namespace="$namespace",pod=~"$pod_regex"}',
    ),
    _tpl(
        key="gpu_card_pcie_rx_bytes",
        unit="bytes/s",
        category="gpu",
        dimension="gpu_card",
        promql='DCGM_FI_PROF_PCIE_RX_BYTES{namespace="$namespace",pod=~"$pod_regex"}',
    ),
    _tpl(
        key="gpu_card_pcie_tx_bytes",
        unit="bytes/s",
        category="gpu",
        dimension="gpu_card",
        promql='DCGM_FI_PROF_PCIE_TX_BYTES{namespace="$namespace",pod=~"$pod_regex"}',
    ),
    _tpl(
        key="gpu_card_xid_errors",
        unit="count",
        category="gpu",
        dimension="gpu_card",
        promql='DCGM_FI_DEV_XID_ERRORS{namespace="$namespace",pod=~"$pod_regex"}',
    ),

    # ============================================================
    # 全量指标扩 (~150 个)
    # ============================================================
    _tpl(
        key="pod_cpu_user_cores",
        unit="cores",
        category="cpu",
        dimension="pod",
        promql='sum by (pod) (rate(container_cpu_user_seconds_total{namespace="$namespace",pod=~"$pod_regex",container!=""}[2m]))',
    ),
    _tpl(
        key="pod_cpu_system_cores",
        unit="cores",
        category="cpu",
        dimension="pod",
        promql='sum by (pod) (rate(container_cpu_system_seconds_total{namespace="$namespace",pod=~"$pod_regex",container!=""}[2m]))',
    ),
    _tpl(
        key="pod_cpu_throttled_seconds",
        unit="seconds/s",
        category="cpu",
        dimension="pod",
        promql='sum by (pod) (rate(container_cpu_cfs_throttled_seconds_total{namespace="$namespace",pod=~"$pod_regex",container!=""}[2m]))',
    ),
    _tpl(
        key="pod_cpu_throttled_periods",
        unit="periods/s",
        category="cpu",
        dimension="pod",
        promql='sum by (pod) (rate(container_cpu_cfs_throttled_periods_total{namespace="$namespace",pod=~"$pod_regex",container!=""}[2m]))',
    ),
    _tpl(
        key="pod_cpu_load_avg_10s",
        unit="load",
        category="cpu",
        dimension="pod",
        promql='avg by (pod) (container_cpu_load_average_10s{namespace="$namespace",pod=~"$pod_regex",container!=""})',
    ),
    _tpl(
        key="pod_mem_usage_bytes",
        unit="bytes",
        category="memory",
        dimension="pod",
        promql='sum by (pod) (container_memory_usage_bytes{namespace="$namespace",pod=~"$pod_regex",container!=""})',
    ),
    _tpl(
        key="pod_mem_rss_bytes",
        unit="bytes",
        category="memory",
        dimension="pod",
        promql='sum by (pod) (container_memory_rss{namespace="$namespace",pod=~"$pod_regex",container!=""})',
    ),
    _tpl(
        key="pod_mem_cache_bytes",
        unit="bytes",
        category="memory",
        dimension="pod",
        promql='sum by (pod) (container_memory_cache{namespace="$namespace",pod=~"$pod_regex",container!=""})',
    ),
    _tpl(
        key="pod_mem_swap_bytes",
        unit="bytes",
        category="memory",
        dimension="pod",
        promql='sum by (pod) (container_memory_swap{namespace="$namespace",pod=~"$pod_regex",container!=""})',
    ),
    _tpl(
        key="pod_mem_max_usage",
        unit="bytes",
        category="memory",
        dimension="pod",
        promql='sum by (pod) (container_memory_max_usage_bytes{namespace="$namespace",pod=~"$pod_regex",container!=""})',
    ),
    _tpl(
        key="pod_mem_failures",
        unit="events/s",
        category="memory",
        dimension="pod",
        promql='sum by (pod) (rate(container_memory_failures_total{namespace="$namespace",pod=~"$pod_regex",container!=""}[2m]))',
    ),
    _tpl(
        key="pod_oom_events",
        unit="events/s",
        category="memory",
        dimension="pod",
        promql='sum by (pod) (rate(container_oom_events_total{namespace="$namespace",pod=~"$pod_regex"}[5m]))',
    ),
    _tpl(
        key="pod_fs_reads_iops",
        unit="ops/s",
        category="disk",
        dimension="pod",
        promql='sum by (pod) (rate(container_fs_reads_total{namespace="$namespace",pod=~"$pod_regex",container!=""}[2m]))',
    ),
    _tpl(
        key="pod_fs_writes_iops",
        unit="ops/s",
        category="disk",
        dimension="pod",
        promql='sum by (pod) (rate(container_fs_writes_total{namespace="$namespace",pod=~"$pod_regex",container!=""}[2m]))',
    ),
    _tpl(
        key="pod_fs_io_time",
        unit="seconds/s",
        category="disk",
        dimension="pod",
        promql='sum by (pod) (rate(container_fs_io_time_seconds_total{namespace="$namespace",pod=~"$pod_regex",container!=""}[2m]))',
    ),
    _tpl(
        key="pod_fs_usage_bytes",
        unit="bytes",
        category="disk",
        dimension="pod",
        promql='sum by (pod) (container_fs_usage_bytes{namespace="$namespace",pod=~"$pod_regex",container!=""})',
    ),
    _tpl(
        key="pod_fs_limit_bytes",
        unit="bytes",
        category="disk",
        dimension="pod",
        promql='sum by (pod) (container_fs_limit_bytes{namespace="$namespace",pod=~"$pod_regex",container!=""})',
    ),
    _tpl(
        key="pod_net_rx_packets",
        unit="packets/s",
        category="network",
        dimension="pod",
        promql='sum by (pod) (rate(container_network_receive_packets_total{namespace="$namespace",pod=~"$pod_regex"}[2m]))',
    ),
    _tpl(
        key="pod_net_tx_packets",
        unit="packets/s",
        category="network",
        dimension="pod",
        promql='sum by (pod) (rate(container_network_transmit_packets_total{namespace="$namespace",pod=~"$pod_regex"}[2m]))',
    ),
    _tpl(
        key="pod_net_rx_errors",
        unit="errors/s",
        category="network",
        dimension="pod",
        promql='sum by (pod) (rate(container_network_receive_errors_total{namespace="$namespace",pod=~"$pod_regex"}[2m]))',
    ),
    _tpl(
        key="pod_net_tx_errors",
        unit="errors/s",
        category="network",
        dimension="pod",
        promql='sum by (pod) (rate(container_network_transmit_errors_total{namespace="$namespace",pod=~"$pod_regex"}[2m]))',
    ),
    _tpl(
        key="pod_net_rx_dropped",
        unit="drops/s",
        category="network",
        dimension="pod",
        promql='sum by (pod) (rate(container_network_receive_packets_dropped_total{namespace="$namespace",pod=~"$pod_regex"}[2m]))',
    ),
    _tpl(
        key="pod_net_tx_dropped",
        unit="drops/s",
        category="network",
        dimension="pod",
        promql='sum by (pod) (rate(container_network_transmit_packets_dropped_total{namespace="$namespace",pod=~"$pod_regex"}[2m]))',
    ),
    _tpl(
        key="pod_processes",
        unit="count",
        category="process",
        dimension="pod",
        promql='sum by (pod) (container_processes{namespace="$namespace",pod=~"$pod_regex",container!=""})',
    ),
    _tpl(
        key="pod_threads",
        unit="count",
        category="process",
        dimension="pod",
        promql='sum by (pod) (container_threads{namespace="$namespace",pod=~"$pod_regex",container!=""})',
    ),
    _tpl(
        key="pod_threads_max",
        unit="count",
        category="process",
        dimension="pod",
        promql='avg by (pod) (container_threads_max{namespace="$namespace",pod=~"$pod_regex",container!=""})',
    ),
    _tpl(
        key="pod_sockets",
        unit="count",
        category="process",
        dimension="pod",
        promql='sum by (pod) (container_sockets{namespace="$namespace",pod=~"$pod_regex",container!=""})',
    ),
    _tpl(
        key="pod_file_descriptors",
        unit="count",
        category="process",
        dimension="pod",
        promql='sum by (pod) (container_file_descriptors{namespace="$namespace",pod=~"$pod_regex",container!=""})',
    ),
    _tpl(
        key="pod_spec_cpu_quota",
        unit="cores",
        category="cpu",
        dimension="pod",
        promql='avg by (pod) (container_spec_cpu_quota{namespace="$namespace",pod=~"$pod_regex",container!=""}) / 100000',
    ),
    _tpl(
        key="pod_spec_mem_limit",
        unit="bytes",
        category="memory",
        dimension="pod",
        promql='avg by (pod) (container_spec_memory_limit_bytes{namespace="$namespace",pod=~"$pod_regex",container!=""})',
    ),
    _tpl(
        key="pod_phase_running",
        unit="0/1",
        category="status",
        dimension="pod",
        promql='sum by (pod) (kube_pod_status_phase{namespace="$namespace",pod=~"$pod_regex",phase="Running"})',
    ),
    _tpl(
        key="pod_phase_pending",
        unit="0/1",
        category="status",
        dimension="pod",
        promql='sum by (pod) (kube_pod_status_phase{namespace="$namespace",pod=~"$pod_regex",phase="Pending"})',
    ),
    _tpl(
        key="pod_phase_failed",
        unit="0/1",
        category="status",
        dimension="pod",
        promql='sum by (pod) (kube_pod_status_phase{namespace="$namespace",pod=~"$pod_regex",phase="Failed"})',
    ),
    _tpl(
        key="pod_ready",
        unit="0/1",
        category="status",
        dimension="pod",
        promql='sum by (pod) (kube_pod_status_ready{namespace="$namespace",pod=~"$pod_regex",condition="true"})',
    ),
    _tpl(
        key="pod_scheduled",
        unit="0/1",
        category="status",
        dimension="pod",
        promql='sum by (pod) (kube_pod_status_scheduled{namespace="$namespace",pod=~"$pod_regex",condition="true"})',
    ),
    _tpl(
        key="pod_initialized",
        unit="0/1",
        category="status",
        dimension="pod",
        promql='sum by (pod) (kube_pod_status_initialized{namespace="$namespace",pod=~"$pod_regex",condition="true"})',
    ),
    _tpl(
        key="pod_container_ready",
        unit="count",
        category="status",
        dimension="pod",
        promql='sum by (pod) (kube_pod_container_status_ready{namespace="$namespace",pod=~"$pod_regex"})',
    ),
    _tpl(
        key="pod_unschedulable",
        unit="0/1",
        category="status",
        dimension="pod",
        promql='sum by (pod) (kube_pod_status_unschedulable{namespace="$namespace",pod=~"$pod_regex"})',
    ),
    _tpl(
        key="pod_container_waiting_crashloop",
        unit="count",
        category="event",
        dimension="pod",
        promql='sum by (pod) (kube_pod_container_status_waiting_reason{namespace="$namespace",pod=~"$pod_regex",reason="CrashLoopBackOff"})',
    ),
    _tpl(
        key="pod_container_waiting_imagepull",
        unit="count",
        category="event",
        dimension="pod",
        promql='sum by (pod) (kube_pod_container_status_waiting_reason{namespace="$namespace",pod=~"$pod_regex",reason="ImagePullBackOff"})',
    ),
    _tpl(
        key="pod_container_waiting_creating",
        unit="count",
        category="event",
        dimension="pod",
        promql='sum by (pod) (kube_pod_container_status_waiting_reason{namespace="$namespace",pod=~"$pod_regex",reason="ContainerCreating"})',
    ),
    _tpl(
        key="pod_container_terminated_oom",
        unit="count",
        category="event",
        dimension="pod",
        promql='sum by (pod) (kube_pod_container_status_terminated_reason{namespace="$namespace",pod=~"$pod_regex",reason="OOMKilled"})',
    ),
    _tpl(
        key="pod_container_terminated_error",
        unit="count",
        category="event",
        dimension="pod",
        promql='sum by (pod) (kube_pod_container_status_terminated_reason{namespace="$namespace",pod=~"$pod_regex",reason="Error"})',
    ),
    _tpl(
        key="pod_last_terminated_exitcode",
        unit="code",
        category="event",
        dimension="pod",
        promql='avg by (pod) (kube_pod_container_status_last_terminated_exitcode{namespace="$namespace",pod=~"$pod_regex"})',
    ),
    _tpl(
        key="pod_resource_request_cpu",
        unit="cores",
        category="cpu",
        dimension="pod",
        promql='sum by (pod) (kube_pod_container_resource_requests{namespace="$namespace",pod=~"$pod_regex",resource="cpu"})',
    ),
    _tpl(
        key="pod_resource_limit_cpu",
        unit="cores",
        category="cpu",
        dimension="pod",
        promql='sum by (pod) (kube_pod_container_resource_limits{namespace="$namespace",pod=~"$pod_regex",resource="cpu"})',
    ),
    _tpl(
        key="pod_resource_request_mem",
        unit="bytes",
        category="memory",
        dimension="pod",
        promql='sum by (pod) (kube_pod_container_resource_requests{namespace="$namespace",pod=~"$pod_regex",resource="memory"})',
    ),
    _tpl(
        key="pod_resource_limit_mem",
        unit="bytes",
        category="memory",
        dimension="pod",
        promql='sum by (pod) (kube_pod_container_resource_limits{namespace="$namespace",pod=~"$pod_regex",resource="memory"})',
    ),
    _tpl(
        key="pod_resource_request_gpu",
        unit="count",
        category="gpu",
        dimension="pod",
        promql='sum by (pod) (kube_pod_container_resource_requests{namespace="$namespace",pod=~"$pod_regex",resource="nvidia_com_gpu"})',
    ),
    _tpl(
        key="pod_age_seconds",
        unit="seconds",
        category="status",
        dimension="pod",
        promql='(time() - kube_pod_start_time{namespace="$namespace",pod=~"$pod_regex"})',
    ),
    _tpl(
        key="pod_gpu_util",
        unit="%",
        category="gpu",
        dimension="pod",
        promql='avg by (pod) (DCGM_FI_DEV_GPU_UTIL{namespace="$namespace",pod=~"$pod_regex"})',
    ),
    _tpl(
        key="pod_gpu_mem_used_gib",
        unit="GiB",
        category="gpu",
        dimension="pod",
        promql='sum by (pod) (DCGM_FI_DEV_FB_USED{namespace="$namespace",pod=~"$pod_regex"}) / 1024',
    ),
    _tpl(
        key="pod_gpu_tensor_active",
        unit="%",
        category="gpu",
        dimension="pod",
        promql='avg by (pod) (DCGM_FI_PROF_PIPE_TENSOR_ACTIVE{namespace="$namespace",pod=~"$pod_regex"}) * 100',
    ),
    _tpl(
        key="pod_gpu_sm_active",
        unit="%",
        category="gpu",
        dimension="pod",
        promql='avg by (pod) (DCGM_FI_PROF_SM_ACTIVE{namespace="$namespace",pod=~"$pod_regex"}) * 100',
    ),
    _tpl(
        key="pod_gpu_gr_engine_active",
        unit="%",
        category="gpu",
        dimension="pod",
        promql='avg by (pod) (DCGM_FI_PROF_GR_ENGINE_ACTIVE{namespace="$namespace",pod=~"$pod_regex"}) * 100',
    ),
    _tpl(
        key="gpu_card_enc_util",
        unit="%",
        category="gpu",
        dimension="gpu_card",
        promql='DCGM_FI_DEV_ENC_UTIL{namespace="$namespace",pod=~"$pod_regex"}',
    ),
    _tpl(
        key="gpu_card_dec_util",
        unit="%",
        category="gpu",
        dimension="gpu_card",
        promql='DCGM_FI_DEV_DEC_UTIL{namespace="$namespace",pod=~"$pod_regex"}',
    ),
    _tpl(
        key="gpu_card_sm_occupancy",
        unit="ratio",
        category="gpu",
        dimension="gpu_card",
        promql='DCGM_FI_PROF_SM_OCCUPANCY{namespace="$namespace",pod=~"$pod_regex"}',
    ),
    _tpl(
        key="gpu_card_dram_active",
        unit="ratio",
        category="gpu",
        dimension="gpu_card",
        promql='DCGM_FI_PROF_DRAM_ACTIVE{namespace="$namespace",pod=~"$pod_regex"}',
    ),
    _tpl(
        key="gpu_card_fp64_active",
        unit="ratio",
        category="gpu",
        dimension="gpu_card",
        promql='DCGM_FI_PROF_PIPE_FP64_ACTIVE{namespace="$namespace",pod=~"$pod_regex"}',
    ),
    _tpl(
        key="gpu_card_fp32_active",
        unit="ratio",
        category="gpu",
        dimension="gpu_card",
        promql='DCGM_FI_PROF_PIPE_FP32_ACTIVE{namespace="$namespace",pod=~"$pod_regex"}',
    ),
    _tpl(
        key="gpu_card_fp16_active",
        unit="ratio",
        category="gpu",
        dimension="gpu_card",
        promql='DCGM_FI_PROF_PIPE_FP16_ACTIVE{namespace="$namespace",pod=~"$pod_regex"}',
    ),
    _tpl(
        key="gpu_card_fb_free",
        unit="MB",
        category="gpu",
        dimension="gpu_card",
        promql='DCGM_FI_DEV_FB_FREE{namespace="$namespace",pod=~"$pod_regex"}',
    ),
    _tpl(
        key="gpu_card_memory_temp",
        unit="°C",
        category="gpu",
        dimension="gpu_card",
        promql='DCGM_FI_DEV_MEMORY_TEMP{namespace="$namespace",pod=~"$pod_regex"}',
    ),
    _tpl(
        key="gpu_card_total_energy",
        unit="mJ",
        category="gpu",
        dimension="gpu_card",
        promql='DCGM_FI_DEV_TOTAL_ENERGY_CONSUMPTION{namespace="$namespace",pod=~"$pod_regex"}',
    ),
    _tpl(
        key="gpu_card_power_violation",
        unit="us",
        category="gpu",
        dimension="gpu_card",
        promql='DCGM_FI_DEV_POWER_VIOLATION{namespace="$namespace",pod=~"$pod_regex"}',
    ),
    _tpl(
        key="gpu_card_thermal_violation",
        unit="us",
        category="gpu",
        dimension="gpu_card",
        promql='DCGM_FI_DEV_THERMAL_VIOLATION{namespace="$namespace",pod=~"$pod_regex"}',
    ),
    _tpl(
        key="gpu_card_sync_boost_violation",
        unit="us",
        category="gpu",
        dimension="gpu_card",
        promql='DCGM_FI_DEV_SYNC_BOOST_VIOLATION{namespace="$namespace",pod=~"$pod_regex"}',
    ),
    _tpl(
        key="gpu_card_board_limit_violation",
        unit="us",
        category="gpu",
        dimension="gpu_card",
        promql='DCGM_FI_DEV_BOARD_LIMIT_VIOLATION{namespace="$namespace",pod=~"$pod_regex"}',
    ),
    _tpl(
        key="gpu_card_low_util_violation",
        unit="us",
        category="gpu",
        dimension="gpu_card",
        promql='DCGM_FI_DEV_LOW_UTIL_VIOLATION{namespace="$namespace",pod=~"$pod_regex"}',
    ),
    _tpl(
        key="gpu_card_reliability_violation",
        unit="us",
        category="gpu",
        dimension="gpu_card",
        promql='DCGM_FI_DEV_RELIABILITY_VIOLATION{namespace="$namespace",pod=~"$pod_regex"}',
    ),
    _tpl(
        key="gpu_card_sm_clock",
        unit="MHz",
        category="gpu",
        dimension="gpu_card",
        promql='DCGM_FI_DEV_SM_CLOCK{namespace="$namespace",pod=~"$pod_regex"}',
    ),
    _tpl(
        key="gpu_card_mem_clock",
        unit="MHz",
        category="gpu",
        dimension="gpu_card",
        promql='DCGM_FI_DEV_MEM_CLOCK{namespace="$namespace",pod=~"$pod_regex"}',
    ),
    _tpl(
        key="gpu_card_ecc_sbe_vol",
        unit="count",
        category="gpu",
        dimension="gpu_card",
        promql='DCGM_FI_DEV_ECC_SBE_VOL_TOTAL{namespace="$namespace",pod=~"$pod_regex"}',
    ),
    _tpl(
        key="gpu_card_ecc_dbe_vol",
        unit="count",
        category="gpu",
        dimension="gpu_card",
        promql='DCGM_FI_DEV_ECC_DBE_VOL_TOTAL{namespace="$namespace",pod=~"$pod_regex"}',
    ),
    _tpl(
        key="gpu_card_ecc_sbe_agg",
        unit="count",
        category="gpu",
        dimension="gpu_card",
        promql='DCGM_FI_DEV_ECC_SBE_AGG_TOTAL{namespace="$namespace",pod=~"$pod_regex"}',
    ),
    _tpl(
        key="gpu_card_ecc_dbe_agg",
        unit="count",
        category="gpu",
        dimension="gpu_card",
        promql='DCGM_FI_DEV_ECC_DBE_AGG_TOTAL{namespace="$namespace",pod=~"$pod_regex"}',
    ),
    _tpl(
        key="gpu_card_retired_sbe",
        unit="count",
        category="gpu",
        dimension="gpu_card",
        promql='DCGM_FI_DEV_RETIRED_SBE{namespace="$namespace",pod=~"$pod_regex"}',
    ),
    _tpl(
        key="gpu_card_retired_dbe",
        unit="count",
        category="gpu",
        dimension="gpu_card",
        promql='DCGM_FI_DEV_RETIRED_DBE{namespace="$namespace",pod=~"$pod_regex"}',
    ),
    _tpl(
        key="gpu_card_retired_pending",
        unit="count",
        category="gpu",
        dimension="gpu_card",
        promql='DCGM_FI_DEV_RETIRED_PENDING{namespace="$namespace",pod=~"$pod_regex"}',
    ),
    _tpl(
        key="gpu_card_remap_correctable",
        unit="count",
        category="gpu",
        dimension="gpu_card",
        promql='DCGM_FI_DEV_CORRECTABLE_REMAPPED_ROWS{namespace="$namespace",pod=~"$pod_regex"}',
    ),
    _tpl(
        key="gpu_card_remap_uncorrectable",
        unit="count",
        category="gpu",
        dimension="gpu_card",
        promql='DCGM_FI_DEV_UNCORRECTABLE_REMAPPED_ROWS{namespace="$namespace",pod=~"$pod_regex"}',
    ),
    _tpl(
        key="gpu_card_remap_failure",
        unit="count",
        category="gpu",
        dimension="gpu_card",
        promql='DCGM_FI_DEV_ROW_REMAP_FAILURE{namespace="$namespace",pod=~"$pod_regex"}',
    ),
    _tpl(
        key="gpu_card_pcie_replay",
        unit="count",
        category="gpu",
        dimension="gpu_card",
        promql='DCGM_FI_DEV_PCIE_REPLAY_COUNTER{namespace="$namespace",pod=~"$pod_regex"}',
    ),
    _tpl(
        key="gpu_card_nvlink_bandwidth_total",
        unit="bytes",
        category="gpu",
        dimension="gpu_card",
        promql='DCGM_FI_DEV_NVLINK_BANDWIDTH_TOTAL{namespace="$namespace",pod=~"$pod_regex"}',
    ),
    _tpl(
        key="gpu_card_nvlink_replay",
        unit="count",
        category="gpu",
        dimension="gpu_card",
        promql='DCGM_FI_DEV_NVLINK_REPLAY_ERROR_COUNT_TOTAL{namespace="$namespace",pod=~"$pod_regex"}',
    ),
    _tpl(
        key="gpu_card_nvlink_recovery",
        unit="count",
        category="gpu",
        dimension="gpu_card",
        promql='DCGM_FI_DEV_NVLINK_RECOVERY_ERROR_COUNT_TOTAL{namespace="$namespace",pod=~"$pod_regex"}',
    ),
    _tpl(
        key="gpu_card_nvlink_flit_crc",
        unit="count",
        category="gpu",
        dimension="gpu_card",
        promql='DCGM_FI_DEV_NVLINK_CRC_FLIT_ERROR_COUNT_TOTAL{namespace="$namespace",pod=~"$pod_regex"}',
    ),
    _tpl(
        key="gpu_card_nvlink_data_crc",
        unit="count",
        category="gpu",
        dimension="gpu_card",
        promql='DCGM_FI_DEV_NVLINK_CRC_DATA_ERROR_COUNT_TOTAL{namespace="$namespace",pod=~"$pod_regex"}',
    ),
    _tpl(
        key="gpu_card_nvlink_bandwidth_l0",
        unit="bytes",
        category="gpu",
        dimension="gpu_card",
        promql='DCGM_FI_DEV_NVLINK_BANDWIDTH_L0{namespace="$namespace",pod=~"$pod_regex"}',
    ),
    _tpl(
        key="training_time_ms",
        unit="ms",
        category="training",
        dimension="job",
        promql='training_time_ms{job_name="$job_name"}',
    ),
    _tpl(
        key="training_manual_restart",
        unit="count",
        category="training",
        dimension="job",
        promql='training_manual_restart_count{job_name="$job_name"}',
    ),
    _tpl(
        key="training_manual_downtime",
        unit="ms",
        category="training",
        dimension="job",
        promql='training_manual_downtime_ms{job_name="$job_name"}',
    ),
    _tpl(
        key="training_auto_restart",
        unit="count",
        category="training",
        dimension="job",
        promql='training_auto_restart_count{job_name="$job_name"}',
    ),
    _tpl(
        key="training_auto_restart_downtime",
        unit="ms",
        category="training",
        dimension="job",
        promql='training_auto_restart_downtime_ms{job_name="$job_name"}',
    ),
    _tpl(
        key="job_active_pods",
        unit="count",
        category="status",
        dimension="job",
        promql='sum by (job_name) (kube_job_status_active{namespace="$namespace"})',
    ),
    _tpl(
        key="job_succeeded_pods",
        unit="count",
        category="status",
        dimension="job",
        promql='sum by (job_name) (kube_job_status_succeeded{namespace="$namespace"})',
    ),
    _tpl(
        key="job_failed_pods",
        unit="count",
        category="status",
        dimension="job",
        promql='sum by (job_name) (kube_job_status_failed{namespace="$namespace"})',
    ),
    _tpl(
        key="job_total_restarts",
        unit="count",
        category="event",
        dimension="job",
        promql='sum(kube_pod_container_status_restarts_total{namespace="$namespace",pod=~"$pod_regex"})',
    ),
    _tpl(
        key="job_total_oom",
        unit="events/s",
        category="event",
        dimension="job",
        promql='sum(rate(container_oom_events_total{namespace="$namespace",pod=~"$pod_regex"}[10m]))',
    ),
    _tpl(
        key="job_energy_total",
        unit="mJ/s",
        category="gpu",
        dimension="job",
        promql='sum(rate(DCGM_FI_DEV_TOTAL_ENERGY_CONSUMPTION{namespace="$namespace",pod=~"$pod_regex"}[5m]))',
    ),
    _tpl(
        key="job_tensor_active_avg",
        unit="%",
        category="gpu",
        dimension="job",
        promql='avg(DCGM_FI_PROF_PIPE_TENSOR_ACTIVE{namespace="$namespace",pod=~"$pod_regex"}) * 100',
    ),
    _tpl(
        key="job_sm_active_avg",
        unit="%",
        category="gpu",
        dimension="job",
        promql='avg(DCGM_FI_PROF_SM_ACTIVE{namespace="$namespace",pod=~"$pod_regex"}) * 100',
    ),
    _tpl(
        key="job_gpu_dram_active_avg",
        unit="%",
        category="gpu",
        dimension="job",
        promql='avg(DCGM_FI_PROF_DRAM_ACTIVE{namespace="$namespace",pod=~"$pod_regex"}) * 100',
    ),
    _tpl(
        key="job_total_power",
        unit="W",
        category="gpu",
        dimension="job",
        promql='sum(DCGM_FI_DEV_POWER_USAGE{namespace="$namespace",pod=~"$pod_regex"})',
    ),
    # 以下 job 维度 GPU 指标按 DT-20 聚合补全 (General Utils / Power / Violations / HW Warning)
    _tpl(key="job_gr_engine_avg",
        unit="ratio", category="gpu", dimension="job",
        promql='avg(DCGM_FI_PROF_GR_ENGINE_ACTIVE{namespace="$namespace",pod=~"$pod_regex"})'),
    _tpl(key="job_sm_occupancy_avg",
        unit="ratio", category="gpu", dimension="job",
        promql='avg(DCGM_FI_PROF_SM_OCCUPANCY{namespace="$namespace",pod=~"$pod_regex"})'),
    _tpl(key="job_gpu_temp_max",
        unit="°C", category="gpu", dimension="job",
        promql='max(DCGM_FI_DEV_GPU_TEMP{namespace="$namespace",pod=~"$pod_regex"})'),
    _tpl(key="job_sm_clock_avg",
        unit="MHz", category="gpu", dimension="job",
        promql='avg(DCGM_FI_DEV_SM_CLOCK{namespace="$namespace",pod=~"$pod_regex"})'),
    _tpl(key="job_thermal_violation",
        unit="us", category="gpu", dimension="job",
        promql='sum(increase(DCGM_FI_DEV_THERMAL_VIOLATION{namespace="$namespace",pod=~"$pod_regex"}[5m]))'),
    _tpl(key="job_power_violation",
        unit="us", category="gpu", dimension="job",
        promql='sum(increase(DCGM_FI_DEV_POWER_VIOLATION{namespace="$namespace",pod=~"$pod_regex"}[5m]))'),
    _tpl(key="job_board_limit_violation",
        unit="us", category="gpu", dimension="job",
        promql='sum(increase(DCGM_FI_DEV_BOARD_LIMIT_VIOLATION{namespace="$namespace",pod=~"$pod_regex"}[5m]))'),
    _tpl(key="job_ecc_dbe_total",
        unit="count", category="gpu", dimension="job",
        promql='max(DCGM_FI_DEV_ECC_DBE_AGG_TOTAL{namespace="$namespace",pod=~"$pod_regex"})'),
    _tpl(key="job_ecc_sbe_total",
        unit="count", category="gpu", dimension="job",
        promql='sum(increase(DCGM_FI_DEV_ECC_SBE_AGG_TOTAL{namespace="$namespace",pod=~"$pod_regex"}[5m]))'),
    _tpl(key="job_remap_uncorrectable",
        unit="count", category="gpu", dimension="job",
        promql='sum(increase(DCGM_FI_DEV_UNCORRECTABLE_REMAPPED_ROWS{namespace="$namespace",pod=~"$pod_regex"}[5m]))'),
    _tpl(key="job_remap_failure",
        unit="bool", category="gpu", dimension="job",
        promql='max(DCGM_FI_DEV_ROW_REMAP_FAILURE{namespace="$namespace",pod=~"$pod_regex"})'),
    # EFA 网卡指标 (node_amazonefa_*, aws-efa exporter, node 级无 pod label),
    # 按任务 pod 所在节点聚合 (node=~node_regex)。带宽/RDMA 走 rate, 健康事件走 increase。
    # g6 无 EFA 硬件应为 0, B300/p5 等多节点高速网才有。
    # --- 带宽 ---
    _tpl(key="job_efa_rx_bytes",
        unit="bytes/s", category="efa", dimension="job",
        promql='sum(rate(node_amazonefa_rx_bytes{node=~"$node_regex"}[2m]))'),
    _tpl(key="job_efa_tx_bytes",
        unit="bytes/s", category="efa", dimension="job",
        promql='sum(rate(node_amazonefa_tx_bytes{node=~"$node_regex"}[2m]))'),
    _tpl(key="job_efa_rx_pkts",
        unit="pkts/s", category="efa", dimension="job",
        promql='sum(rate(node_amazonefa_rx_pkts{node=~"$node_regex"}[2m]))'),
    _tpl(key="job_efa_tx_pkts",
        unit="pkts/s", category="efa", dimension="job",
        promql='sum(rate(node_amazonefa_tx_pkts{node=~"$node_regex"}[2m]))'),
    _tpl(key="job_efa_recv_bytes",
        unit="bytes/s", category="efa", dimension="job",
        promql='sum(rate(node_amazonefa_recv_bytes{node=~"$node_regex"}[2m]))'),
    _tpl(key="job_efa_send_bytes",
        unit="bytes/s", category="efa", dimension="job",
        promql='sum(rate(node_amazonefa_send_bytes{node=~"$node_regex"}[2m]))'),
    _tpl(key="job_efa_recv_wrs",
        unit="wr/s", category="efa", dimension="job",
        promql='sum(rate(node_amazonefa_recv_wrs{node=~"$node_regex"}[2m]))'),
    _tpl(key="job_efa_send_wrs",
        unit="wr/s", category="efa", dimension="job",
        promql='sum(rate(node_amazonefa_send_wrs{node=~"$node_regex"}[2m]))'),
    # --- RDMA ---
    _tpl(key="job_efa_rdma_total",
        unit="bytes/s", category="efa", dimension="job",
        promql='sum(rate(node_amazonefa_rdma_read_bytes{node=~"$node_regex"}[2m])) + sum(rate(node_amazonefa_rdma_write_bytes{node=~"$node_regex"}[2m]))'),
    _tpl(key="job_efa_rdma_read_bytes",
        unit="bytes/s", category="efa", dimension="job",
        promql='sum(rate(node_amazonefa_rdma_read_bytes{node=~"$node_regex"}[2m]))'),
    _tpl(key="job_efa_rdma_write_bytes",
        unit="bytes/s", category="efa", dimension="job",
        promql='sum(rate(node_amazonefa_rdma_write_bytes{node=~"$node_regex"}[2m]))'),
    _tpl(key="job_efa_rdma_read_resp_bytes",
        unit="bytes/s", category="efa", dimension="job",
        promql='sum(rate(node_amazonefa_rdma_read_resp_bytes{node=~"$node_regex"}[2m]))'),
    _tpl(key="job_efa_rdma_write_recv_bytes",
        unit="bytes/s", category="efa", dimension="job",
        promql='sum(rate(node_amazonefa_rdma_write_recv_bytes{node=~"$node_regex"}[2m]))'),
    _tpl(key="job_efa_rdma_read_wrs",
        unit="wr/s", category="efa", dimension="job",
        promql='sum(rate(node_amazonefa_rdma_read_wrs{node=~"$node_regex"}[2m]))'),
    _tpl(key="job_efa_rdma_write_wrs",
        unit="wr/s", category="efa", dimension="job",
        promql='sum(rate(node_amazonefa_rdma_write_wrs{node=~"$node_regex"}[2m]))'),
    # --- 健康 (事件累计, increase 看增量; > 0 即互联异常) ---
    _tpl(key="job_efa_retrans_bytes",
        unit="bytes", category="efa", dimension="job",
        promql='sum(increase(node_amazonefa_retrans_bytes{node=~"$node_regex"}[5m]))'),
    _tpl(key="job_efa_retrans_pkts",
        unit="pkts", category="efa", dimension="job",
        promql='sum(increase(node_amazonefa_retrans_pkts{node=~"$node_regex"}[5m]))'),
    _tpl(key="job_efa_retrans_timeout",
        unit="events", category="efa", dimension="job",
        promql='sum(increase(node_amazonefa_retrans_timeout_events{node=~"$node_regex"}[5m]))'),
    _tpl(key="job_efa_rx_drops",
        unit="drops", category="efa", dimension="job",
        promql='sum(increase(node_amazonefa_rx_drops{node=~"$node_regex"}[5m]))'),
    _tpl(key="job_efa_impaired_remote",
        unit="events", category="efa", dimension="job",
        promql='sum(increase(node_amazonefa_impaired_remote_conn_events{node=~"$node_regex"}[5m]))'),
    _tpl(key="job_efa_unresponsive_remote",
        unit="events", category="efa", dimension="job",
        promql='sum(increase(node_amazonefa_unresponsive_remote_events{node=~"$node_regex"}[5m]))'),
    _tpl(key="job_efa_rdma_read_wr_err",
        unit="errors", category="efa", dimension="job",
        promql='sum(increase(node_amazonefa_rdma_read_wr_err{node=~"$node_regex"}[5m]))'),
    _tpl(key="job_efa_rdma_write_wr_err",
        unit="errors", category="efa", dimension="job",
        promql='sum(increase(node_amazonefa_rdma_write_wr_err{node=~"$node_regex"}[5m]))'),
    # --- 元信息 (gauge, 暂接) ---
    _tpl(key="job_efa_lifespan",
        unit="s", category="efa", dimension="job",
        promql='max(node_amazonefa_lifespan{node=~"$node_regex"})'),
    _tpl(key="job_efa_info",
        unit="count", category="efa", dimension="job",
        promql='count(node_amazonefa_info{node=~"$node_regex"})'),
    # FSx (aws_fsx_*) / MLflow (mlflow_metric_value) 模板已删: 集群 AMP 未接这些数据源
    # (实测 Prometheus 0 series)。需要时先把 CloudWatch FSx / MLflow 接入 AMP 再加回。
]


# ============================================================
# 开发机 · DevInstance (4 默认指标 + 3 KPI)
# ============================================================

DEV_INSTANCE_TEMPLATES: list[QueryTemplate] = [
    # ============================================================
    # GPU 维度 (DCGM, 按 namespace+pod_regex 精确定位本开发机占用的卡)
    # DCGM series 带 namespace+pod 标签 (dcgm-exporter pod-mapping), 按 pod 过滤
    # 只剩这台开发机实际占的卡, 自动排除同节点别的开发机/训练任务/空闲卡。
    # ============================================================
    _tpl(
        key="gpu_util",
        unit="%",
        category="gpu",
        dimension="gpu_card",
        promql='DCGM_FI_DEV_GPU_UTIL{namespace="$namespace",pod=~"$pod_regex"}',
    ),
    _tpl(
        key="gpu_mem_used_gib",
        unit="GiB",
        category="gpu",
        dimension="gpu_card",
        promql='DCGM_FI_DEV_FB_USED{namespace="$namespace",pod=~"$pod_regex"} / 1024',
    ),
    _tpl(
        key="gpu_temp",
        unit="°C",
        category="gpu",
        dimension="gpu_card",
        promql='DCGM_FI_DEV_GPU_TEMP{namespace="$namespace",pod=~"$pod_regex"}',
    ),
    _tpl(
        key="gpu_mem_copy_util",
        unit="%",
        category="gpu",
        dimension="gpu_card",
        promql='DCGM_FI_DEV_MEM_COPY_UTIL{namespace="$namespace",pod=~"$pod_regex"}',
    ),
    # ============================================================
    # CPU / 内存 维度 (cAdvisor, 按 namespace+pod_regex 定位开发机 Pod)
    # ============================================================
    _tpl(
        key="cpu_usage_cores",
        unit="cores",
        category="cpu",
        dimension="pod",
        promql=(
            'sum by (pod) (rate('
            'container_cpu_usage_seconds_total{'
            'namespace="$namespace",pod=~"$pod_regex",container!=""}[2m]))'
        ),
    ),
    _tpl(
        key="mem_usage_gib",
        unit="GiB",
        category="memory",
        dimension="pod",
        promql=(
            'sum by (pod) ('
            'container_memory_working_set_bytes{'
            'namespace="$namespace",pod=~"$pod_regex",container!=""}) '
            '/ 1024 / 1024 / 1024'
        ),
    ),
    # ============================================================
    # 磁盘 I/O 维度 (数据加载 / checkpoint 写盘场景)
    # ============================================================
    _tpl(
        key="disk_read_bytes",
        unit="bytes/s",
        category="disk",
        dimension="pod",
        promql=(
            'sum by (pod) (rate('
            'container_fs_reads_bytes_total{'
            'namespace="$namespace",pod=~"$pod_regex",container!=""}[2m]))'
        ),
    ),
    _tpl(
        key="disk_write_bytes",
        unit="bytes/s",
        category="disk",
        dimension="pod",
        promql=(
            'sum by (pod) (rate('
            'container_fs_writes_bytes_total{'
            'namespace="$namespace",pod=~"$pod_regex",container!=""}[2m]))'
        ),
    ),
    # ============================================================
    # 网络 维度 (下载数据集 / 拉镜像 / 推送结果)
    # ============================================================
    _tpl(
        key="network_rx_bytes",
        unit="bytes/s",
        category="network",
        dimension="pod",
        promql=(
            'sum by (pod) (rate('
            'container_network_receive_bytes_total{'
            'namespace="$namespace",pod=~"$pod_regex"}[2m]))'
        ),
    ),
    _tpl(
        key="network_tx_bytes",
        unit="bytes/s",
        category="network",
        dimension="pod",
        promql=(
            'sum by (pod) (rate('
            'container_network_transmit_bytes_total{'
            'namespace="$namespace",pod=~"$pod_regex"}[2m]))'
        ),
    ),
]


# ============================================================
# 开发机 KPI · 顶部 3 数字卡
# ============================================================

DEV_INSTANCE_KPI_TEMPLATES: list[QueryTemplate] = [
    _tpl(
        key="kpi_cpu_core_hours_30d",
        unit="core·h",
        category="cpu",
        # subquery 步长用 1h 而非 1m: 30d×1m=43200 点会超 AMP 单查询上限
        # (502); 1h=720 点 AMP 可承受. 每点代表 1h 的瞬时 cores, sum 即
        # core·小时, 无需再 /60 (1m 步长版才需要 /60 把 core·分钟换算).
        promql=(
            'sum_over_time('
            '(sum by (pod) (rate('
            'container_cpu_usage_seconds_total{'
            'namespace="$namespace",pod=~"$pod_regex",container!=""}[5m])))'
            '[30d:1h])'
        ),
    ),
    _tpl(
        key="kpi_gpu_mem_peak_gib",
        unit="GiB",
        category="gpu",
        promql=(
            'max_over_time('
            '(DCGM_FI_DEV_FB_USED{namespace="$namespace",pod=~"$pod_regex"} / 1024)[24h:1m])'
        ),
    ),
    _tpl(
        key="kpi_idle_minutes",
        unit="min",
        category="gpu",
        promql=(
            'count_over_time(('
            'max(DCGM_FI_DEV_GPU_UTIL{namespace="$namespace",pod=~"$pod_regex"}) < bool 5'
            ')[1h:1m])'
        ),
    ),
]


# ============================================================
# 推理服务 · Inference Endpoint (SGLang + cAdvisor + DCGM)
# 占位变量: $namespace / $pod_regex / $node_regex
# ============================================================

INFERENCE_TEMPLATES: list[QueryTemplate] = [
    # ===== Pod 资源 (cAdvisor) =====
    _tpl(
        key="inf_cpu_usage_cores",
        unit="cores",
        category="cpu",
        dimension="pod",
        promql=(
            'sum(rate(container_cpu_usage_seconds_total{'
            'namespace="$namespace",pod=~"$pod_regex",container!=""}[2m])) by (pod)'
        ),
    ),
    _tpl(
        key="inf_mem_usage_gib",
        unit="GiB",
        category="memory",
        dimension="pod",
        promql=(
            'sum(container_memory_working_set_bytes{'
            'namespace="$namespace",pod=~"$pod_regex",container!=""}) by (pod) '
            '/ 1024 / 1024 / 1024'
        ),
    ),
    _tpl(
        key="inf_net_rx_bytes",
        unit="bytes/s",
        category="network",
        dimension="pod",
        promql=(
            'sum(rate(container_network_receive_bytes_total{'
            'namespace="$namespace",pod=~"$pod_regex"}[2m])) by (pod)'
        ),
    ),
    _tpl(
        key="inf_net_tx_bytes",
        unit="bytes/s",
        category="network",
        dimension="pod",
        promql=(
            'sum(rate(container_network_transmit_bytes_total{'
            'namespace="$namespace",pod=~"$pod_regex"}[2m])) by (pod)'
        ),
    ),
    # ===== GPU (DCGM) =====
    _tpl(
        key="inf_gpu_util",
        unit="%",
        category="gpu",
        dimension="gpu_card",
        promql='DCGM_FI_DEV_GPU_UTIL{namespace="$namespace",pod=~"$pod_regex"}',
    ),
    _tpl(
        key="inf_gpu_mem_used_gib",
        unit="GiB",
        category="gpu",
        dimension="gpu_card",
        promql='DCGM_FI_DEV_FB_USED{namespace="$namespace",pod=~"$pod_regex"} / 1024',
    ),
    _tpl(
        key="inf_gpu_temp",
        unit="C",
        category="gpu",
        dimension="gpu_card",
        promql='DCGM_FI_DEV_GPU_TEMP{namespace="$namespace",pod=~"$pod_regex"}',
    ),
    _tpl(
        key="inf_gpu_power",
        unit="W",
        category="gpu",
        dimension="gpu_card",
        promql='DCGM_FI_DEV_POWER_USAGE{namespace="$namespace",pod=~"$pod_regex"}',
    ),
    # ===== SGLang 性能 (推理引擎自带 /metrics) =====
    _tpl(
        key="inf_sgl_gen_throughput",
        unit="tokens/s",
        category="sglang",
        dimension="pod",
        promql=(
            'sum(sglang:gen_throughput{'
            'namespace="$namespace",resource_name="$endpoint_name"}) by (pod_name)'
        ),
    ),
    _tpl(
        key="inf_sgl_cache_hit_rate",
        unit="ratio",
        category="sglang",
        dimension="pod",
        promql=(
            'avg(sglang:cache_hit_rate{'
            'namespace="$namespace",resource_name="$endpoint_name"}) by (pod_name)'
        ),
    ),
    _tpl(
        key="inf_sgl_running_reqs",
        unit="reqs",
        category="sglang",
        dimension="pod",
        promql=(
            'sum(sglang:num_running_reqs{'
            'namespace="$namespace",resource_name="$endpoint_name"}) by (pod_name)'
        ),
    ),
    _tpl(
        key="inf_sgl_queue_reqs",
        unit="reqs",
        category="sglang",
        dimension="pod",
        promql=(
            'sum(sglang:num_queue_reqs{'
            'namespace="$namespace",resource_name="$endpoint_name"}) by (pod_name)'
        ),
    ),
    _tpl(
        key="inf_sgl_token_usage",
        unit="ratio",
        category="sglang",
        dimension="pod",
        promql=(
            'avg(sglang:token_usage{'
            'namespace="$namespace",resource_name="$endpoint_name"}) by (pod_name)'
        ),
    ),
    _tpl(
        key="inf_sgl_prompt_tokens_rate",
        unit="tokens/s",
        category="sglang",
        dimension="pod",
        promql=(
            'sum(rate(sglang:prompt_tokens_total{'
            'namespace="$namespace",resource_name="$endpoint_name"}[2m])) by (pod_name)'
        ),
    ),
    _tpl(
        key="inf_sgl_request_rate",
        unit="reqs/s",
        category="sglang",
        dimension="pod",
        promql=(
            'sum(rate(sglang:num_requests_total{'
            'namespace="$namespace",resource_name="$endpoint_name"}[2m])) by (pod_name)'
        ),
    ),
    # ===== Latency histograms (P50/P95) =====
    _tpl(
        key="inf_sgl_ttft_p95",
        unit="s",
        category="sglang",
        dimension="pod",
        promql=(
            'histogram_quantile(0.95, sum(rate('
            'sglang:time_to_first_token_seconds_bucket{'
            'namespace="$namespace",resource_name="$endpoint_name"}[2m])) by (le, pod_name))'
        ),
    ),
    _tpl(
        key="inf_sgl_ttft_p50",
        unit="s",
        category="sglang",
        dimension="pod",
        promql=(
            'histogram_quantile(0.50, sum(rate('
            'sglang:time_to_first_token_seconds_bucket{'
            'namespace="$namespace",resource_name="$endpoint_name"}[2m])) by (le, pod_name))'
        ),
    ),
    _tpl(
        key="inf_sgl_e2e_p95",  # gitleaks:allow
        unit="s",
        category="sglang",
        dimension="pod",
        promql=(
            'histogram_quantile(0.95, sum(rate('
            'sglang:e2e_request_latency_seconds_bucket{'
            'namespace="$namespace",resource_name="$endpoint_name"}[2m])) by (le, pod_name))'
        ),
    ),
    _tpl(
        key="inf_sgl_queue_p95",
        unit="s",
        category="sglang",
        dimension="pod",
        promql=(
            'histogram_quantile(0.95, sum(rate('
            'sglang:queue_time_seconds_bucket{'
            'namespace="$namespace",resource_name="$endpoint_name"}[2m])) by (le, pod_name))'
        ),
    ),
    _tpl(
        key="inf_sgl_queue_p50",
        unit="s",
        category="sglang",
        dimension="pod",
        promql=(
            'histogram_quantile(0.50, sum(rate('
            'sglang:queue_time_seconds_bucket{'
            'namespace="$namespace",resource_name="$endpoint_name"}[2m])) by (le, pod_name))'
        ),
    ),
    _tpl(
        key="inf_sgl_e2e_p50",
        unit="s",
        category="sglang",
        dimension="pod",
        promql=(
            'histogram_quantile(0.50, sum(rate('
            'sglang:e2e_request_latency_seconds_bucket{'
            'namespace="$namespace",resource_name="$endpoint_name"}[2m])) by (le, pod_name))'
        ),
    ),
    _tpl(
        key="inf_sgl_e2e_p99",
        unit="s",
        category="sglang",
        dimension="pod",
        promql=(
            'histogram_quantile(0.99, sum(rate('
            'sglang:e2e_request_latency_seconds_bucket{'
            'namespace="$namespace",resource_name="$endpoint_name"}[2m])) by (le, pod_name))'
        ),
    ),
    _tpl(
        key="inf_sgl_ttft_p99",
        unit="s",
        category="sglang",
        dimension="pod",
        promql=(
            'histogram_quantile(0.99, sum(rate('
            'sglang:time_to_first_token_seconds_bucket{'
            'namespace="$namespace",resource_name="$endpoint_name"}[2m])) by (le, pod_name))'
        ),
    ),
    _tpl(
        key="inf_sgl_prefill_forward_p95",  # gitleaks:allow
        unit="s",
        category="sglang",
        dimension="pod",
        promql=(
            'histogram_quantile(0.95, sum(rate('
            'sglang:per_stage_req_latency_seconds_bucket{'
            'namespace="$namespace",resource_name="$endpoint_name",stage="prefill_forward"}[2m])) '
            'by (le, pod_name))'
        ),
    ),
    _tpl(
        key="inf_sgl_request_process_p95",
        unit="s",
        category="sglang",
        dimension="pod",
        promql=(
            'histogram_quantile(0.95, sum(rate('
            'sglang:per_stage_req_latency_seconds_bucket{'
            'namespace="$namespace",resource_name="$endpoint_name",stage="request_process"}[2m])) '
            'by (le, pod_name))'
        ),
    ),
    # ===== Token 分布 histograms (mean) =====
    _tpl(
        key="inf_sgl_prompt_tokens_avg",
        unit="tokens",
        category="sglang",
        dimension="pod",
        promql=(
            'sum(sglang:prompt_tokens_histogram_sum{'
            'namespace="$namespace",resource_name="$endpoint_name"}) by (pod_name) / '
            'sum(sglang:prompt_tokens_histogram_count{'
            'namespace="$namespace",resource_name="$endpoint_name"}) by (pod_name)'
        ),
    ),
    _tpl(
        key="inf_sgl_uncached_prompt_tokens_avg",
        unit="tokens",
        category="sglang",
        dimension="pod",
        promql=(
            'sum(sglang:uncached_prompt_tokens_histogram_sum{'
            'namespace="$namespace",resource_name="$endpoint_name"}) by (pod_name) / '
            'sum(sglang:uncached_prompt_tokens_histogram_count{'
            'namespace="$namespace",resource_name="$endpoint_name"}) by (pod_name)'
        ),
    ),
    _tpl(
        key="inf_sgl_generation_tokens_avg",
        unit="tokens",
        category="sglang",
        dimension="pod",
        promql=(
            'sum(sglang:generation_tokens_histogram_sum{'
            'namespace="$namespace",resource_name="$endpoint_name"}) by (pod_name) / '
            'sum(sglang:generation_tokens_histogram_count{'
            'namespace="$namespace",resource_name="$endpoint_name"}) by (pod_name)'
        ),
    ),
    # ===== KV pool 详细 (大 KV 时调试用) =====
    _tpl(
        key="inf_sgl_kv_used_tokens",
        unit="tokens",
        category="sglang",
        dimension="pod",
        promql=(
            'sum(sglang:kv_used_tokens{'
            'namespace="$namespace",resource_name="$endpoint_name"}) by (pod_name)'
        ),
    ),
    _tpl(
        key="inf_sgl_kv_evictable_tokens",
        unit="tokens",
        category="sglang",
        dimension="pod",
        promql=(
            'sum(sglang:kv_evictable_tokens{'
            'namespace="$namespace",resource_name="$endpoint_name"}) by (pod_name)'
        ),
    ),
    _tpl(
        key="inf_sgl_kv_available_tokens",
        unit="tokens",
        category="sglang",
        dimension="pod",
        promql=(
            'sum(sglang:kv_available_tokens{'
            'namespace="$namespace",resource_name="$endpoint_name"}) by (pod_name)'
        ),
    ),
    # ===== 累计 counter (rate) =====
    _tpl(
        key="inf_sgl_generation_tokens_rate",
        unit="tokens/s",
        category="sglang",
        dimension="pod",
        promql=(
            'sum(rate(sglang:generation_tokens_total{'
            'namespace="$namespace",resource_name="$endpoint_name"}[2m])) by (pod_name)'
        ),
    ),
    # ===== HTTP 请求统计 =====
    _tpl(
        key="inf_sgl_http_requests_rate",
        unit="reqs/s",
        category="sglang",
        dimension="pod",
        # sglang: 前缀来自 worker :8000, label 用 endpoint; gateway 的 smg_ 用 path
        promql=(
            'sum(rate(sglang:http_requests_total{'
            'namespace="$namespace",resource_name="$endpoint_name",'
            'endpoint=~"/generate|/v1/.*"'
            '}[2m])) by (endpoint, pod_name)'
        ),
    ),
    _tpl(
        key="inf_sgl_http_responses_rate",
        unit="reqs/s",
        category="sglang",
        dimension="pod",
        promql=(
            'sum(rate(sglang:http_responses_total{'
            'namespace="$namespace",resource_name="$endpoint_name",'
            'endpoint=~"/generate|/v1/.*"'
            '}[2m])) by (status_code, pod_name)'
        ),
    ),

    # ============================================================
    # Inference Operator 网关指标 (reverse-proxy / nginx-lua 在入口测,
    # 对外 SLA 视角; sglang:* 是引擎内部视角, 两者互补. 全经 DT-20 实测有数据).
    # 过滤用 resource_name=endpoint 名; nginx_metric_errors 无 resource_name,
    # 改用 model_name (实测 model_name == resource_name == endpoint 名).
    # ============================================================
    _tpl(
        key="inf_model_qps",
        unit="reqs/s",
        category="inference",
        dimension="pod",
        promql=(
            'sum(rate(model_invocations_total{'
            'resource_name="$endpoint_name",method="POST"}[2m]))'
        ),
    ),
    _tpl(
        key="inf_model_success_rate",
        unit="%",
        category="inference",
        dimension="pod",
        promql=(
            '(1 - (sum(rate(model_errors_total{resource_name="$endpoint_name",method="POST"}[5m])) or vector(0))'
            ' / sum(rate(model_invocations_total{resource_name="$endpoint_name",method="POST"}[5m]))) * 100'
        ),
    ),
    _tpl(
        key="inf_model_concurrent",
        unit="count",
        category="inference",
        dimension="pod",
        promql=(
            'sum(model_concurrent_requests{'
            'resource_name="$endpoint_name",method="POST"})'
        ),
    ),
    _tpl(
        key="inf_model_latency_p90",
        unit="ms",
        category="inference",
        dimension="pod",
        promql=(
            'histogram_quantile(0.90, sum(rate(model_latency_milliseconds_bucket{'
            'resource_name="$endpoint_name",method="POST",status=~"2.*"}[5m])) by (le))'
        ),
    ),
    _tpl(
        key="inf_model_ttfb_p90",
        unit="ms",
        category="inference",
        dimension="pod",
        promql=(
            'histogram_quantile(0.90, sum(rate(model_ttfb_milliseconds_bucket{'
            'resource_name="$endpoint_name",method="POST",status=~"2.*"}[5m])) by (le))'
        ),
    ),
    _tpl(
        key="inf_nginx_errors",
        unit="count",
        category="inference",
        dimension="pod",
        promql='increase(nginx_metric_errors_total{model_name="$endpoint_name"}[5m])',
    ),
    _tpl(
        key="inf_sgl_http_active",
        unit="count",
        category="sglang",
        dimension="pod",
        promql=(
            'max(sglang:http_requests_active{'
            'namespace="$namespace",resource_name="$endpoint_name"}) by (pod_name)'
        ),
    ),
    _tpl(
        key="inf_sgl_utilization",
        unit="%",
        category="sglang",
        dimension="pod",
        promql=(
            'avg(sglang:utilization{'
            'namespace="$namespace",resource_name="$endpoint_name"}) by (pod_name)'
        ),
    ),
    _tpl(
        key="inf_sgl_kv_capacity",
        unit="tokens",
        category="sglang",
        dimension="pod",
        promql=(
            'max(sglang:max_total_num_tokens{'
            'namespace="$namespace",resource_name="$endpoint_name"}) by (pod_name)'
        ),
    ),
    _tpl(
        key="inf_model_replicas_total",
        unit="count",
        category="inference",
        dimension="pod",
        promql=(
            'count(count by (pod_name)(max_over_time('
            'model_invocations_total{resource_name="$endpoint_name"}[5m])))'
        ),
    ),
    _tpl(
        key="inf_model_replicas_active",
        unit="count",
        category="inference",
        dimension="pod",
        promql=(
            'count(count by (pod_name)('
            'rate(model_invocations_total{resource_name="$endpoint_name"}[5m]) > 0))'
        ),
    ),
]


# ============================================================
# Dynamo 引擎指标 (dynamo_*, 9090 + frontend:8000)
# 占位变量: $namespace / $resource_name (sidecar static 注入 = CR 名)
# 指标名实测 (2026-07-14 curl): worker dynamo_component_*/dynamo_work_handler_*,
# frontend dynamo_component_router_*/dynamo_frontend_*。全用 resource_name 过滤 (sidecar 注入)。
# ============================================================

DYNAMO_ENGINE_TEMPLATES: list[QueryTemplate] = [
    _tpl(
        key="dyn_request_rate",
        unit="reqs/s",
        category="dynamo",
        dimension="pod",
        promql=(
            'sum(rate(dynamo_component_requests_total{'
            'resource_name="$resource_name"}[2m]))'
        ),
    ),
    _tpl(
        key="dyn_inflight",
        unit="reqs",
        category="dynamo",
        dimension="pod",
        promql='sum(dynamo_component_inflight_requests{resource_name="$resource_name"})',
    ),
    _tpl(
        key="dyn_queue_depth",
        unit="reqs",
        category="dynamo",
        dimension="pod",
        promql='sum(dynamo_work_handler_queue_depth{resource_name="$resource_name"})',
    ),
    _tpl(
        key="dyn_gpu_cache_usage",
        unit="%",
        category="dynamo",
        dimension="pod",
        promql='avg(dynamo_component_gpu_cache_usage_percent{resource_name="$resource_name"})',
    ),
    _tpl(
        key="dyn_ttft_p95",
        unit="s",
        category="dynamo",
        dimension="pod",
        promql=(
            'histogram_quantile(0.95, sum(rate('
            'dynamo_component_router_time_to_first_token_seconds_bucket{'
            'resource_name="$resource_name"}[2m])) by (le))'
        ),
    ),
    _tpl(
        key="dyn_itl_p95",
        unit="s",
        category="dynamo",
        dimension="pod",
        promql=(
            'histogram_quantile(0.95, sum(rate('
            'dynamo_component_router_inter_token_latency_seconds_bucket{'
            'resource_name="$resource_name"}[2m])) by (le))'
        ),
    ),
    _tpl(
        key="dyn_request_duration_p95",
        unit="s",
        category="dynamo",
        dimension="pod",
        promql=(
            'histogram_quantile(0.95, sum(rate('
            'dynamo_component_request_duration_seconds_bucket{'
            'resource_name="$resource_name"}[2m])) by (le))'
        ),
    ),
    _tpl(
        key="dyn_kv_hit_rate",
        unit="ratio",
        category="dynamo",
        dimension="pod",
        promql=(
            'sum(rate(dynamo_component_router_kv_hit_rate_sum{resource_name="$resource_name"}[2m])) '
            '/ clamp_min(sum(rate(dynamo_component_router_kv_hit_rate_count{'
            'resource_name="$resource_name"}[2m])), 1)'
        ),
    ),
    _tpl(
        key="dyn_frontend_qps",
        unit="reqs/s",
        category="dynamo",
        dimension="pod",
        promql=(
            'sum(rate(dynamo_component_router_requests_total{'
            'resource_name="$resource_name"}[2m]))'
        ),
    ),
    _tpl(
        key="dyn_uptime",
        unit="seconds",
        category="dynamo",
        dimension="pod",
        promql='max(dynamo_component_uptime_seconds{resource_name="$resource_name"})',
    ),
    # ---- worker 引擎: 请求/队列/资源池 (dynamo_component_* / dynamo_work_handler_*) ----
    _tpl(
        key="dyn_cancellation_rate",
        unit="reqs/s",
        category="dynamo",
        dimension="pod",
        promql=(
            'sum(rate(dynamo_component_cancellation_total{'
            'resource_name="$resource_name"}[2m]))'
        ),
    ),
    _tpl(
        key="dyn_model_load_time",
        unit="seconds",
        category="dynamo",
        dimension="pod",
        promql='max(dynamo_component_model_load_time_seconds{resource_name="$resource_name"})',
    ),
    _tpl(
        key="dyn_total_blocks",
        unit="blocks",
        category="dynamo",
        dimension="pod",
        promql='sum(dynamo_component_total_blocks{resource_name="$resource_name"})',
    ),
    _tpl(
        key="dyn_queue_capacity",
        unit="reqs",
        category="dynamo",
        dimension="pod",
        promql='sum(dynamo_work_handler_queue_capacity{resource_name="$resource_name"})',
    ),
    _tpl(
        key="dyn_enqueue_rejected",
        unit="reqs/s",
        category="dynamo",
        dimension="pod",
        promql=(
            'sum(rate(dynamo_work_handler_enqueue_rejected_total{'
            'resource_name="$resource_name"}[2m]))'
        ),
    ),
    _tpl(
        key="dyn_pool_active",
        unit="tasks",
        category="dynamo",
        dimension="pod",
        promql='sum(dynamo_work_handler_pool_active_tasks{resource_name="$resource_name"})',
    ),
    _tpl(
        key="dyn_pool_capacity",
        unit="tasks",
        category="dynamo",
        dimension="pod",
        promql='sum(dynamo_work_handler_pool_capacity{resource_name="$resource_name"})',
    ),
    _tpl(
        key="dyn_first_response_p95",
        unit="s",
        category="dynamo",
        dimension="pod",
        promql=(
            'histogram_quantile(0.95, sum(rate('
            'dynamo_work_handler_time_to_first_response_seconds_bucket{'
            'resource_name="$resource_name"}[2m])) by (le))'
        ),
    ),
    _tpl(
        key="dyn_permit_wait_p95",
        unit="s",
        category="dynamo",
        dimension="pod",
        promql=(
            'histogram_quantile(0.95, sum(rate('
            'dynamo_work_handler_permit_wait_seconds_bucket{'
            'resource_name="$resource_name"}[2m])) by (le))'
        ),
    ),
    # ---- frontend/router: token 序列 (dynamo_component_router_*) ----
    _tpl(
        key="dyn_input_seq_p95",
        unit="tokens",
        category="dynamo",
        dimension="pod",
        promql=(
            'histogram_quantile(0.95, sum(rate('
            'dynamo_component_router_input_sequence_tokens_bucket{'
            'resource_name="$resource_name"}[2m])) by (le))'
        ),
    ),
    _tpl(
        key="dyn_output_seq_p95",
        unit="tokens",
        category="dynamo",
        dimension="pod",
        promql=(
            'histogram_quantile(0.95, sum(rate('
            'dynamo_component_router_output_sequence_tokens_bucket{'
            'resource_name="$resource_name"}[2m])) by (le))'
        ),
    ),
    # ---- 可选: router 深度调优 + frontend 前处理 (深度诊断才看) ----
    _tpl(
        key="dyn_shared_cache_hit",
        unit="%",
        category="dynamo",
        dimension="pod",
        promql=(
            'sum(rate(dynamo_component_router_shared_cache_hit_rate_sum{'
            'resource_name="$resource_name"}[5m])) / '
            'sum(rate(dynamo_component_router_shared_cache_hit_rate_count{'
            'resource_name="$resource_name"}[5m]))'
        ),
    ),
    _tpl(
        key="dyn_kv_transfer_p95",
        unit="s",
        category="dynamo",
        dimension="pod",
        promql=(
            'histogram_quantile(0.95, sum(rate('
            'dynamo_component_router_kv_transfer_estimated_latency_seconds_bucket{'
            'resource_name="$resource_name"}[2m])) by (le))'
        ),
    ),
    _tpl(
        key="dyn_tokenize_p95",
        unit="s",
        category="dynamo",
        dimension="pod",
        promql=(
            'histogram_quantile(0.95, sum(rate('
            'dynamo_frontend_tokenize_seconds_bucket{'
            'resource_name="$resource_name"}[2m])) by (le))'
        ),
    ),
    _tpl(
        key="dyn_detokenize_us_per_token",
        unit="us",
        category="dynamo",
        dimension="pod",
        promql=(
            'sum(rate(dynamo_frontend_detokenize_total_us{'
            'resource_name="$resource_name"}[5m])) / '
            'sum(rate(dynamo_frontend_detokenize_token_count{'
            'resource_name="$resource_name"}[5m]))'
        ),
    ),
    _tpl(
        key="dyn_disconnected_clients",
        unit="count",
        category="dynamo",
        dimension="pod",
        promql='sum(dynamo_frontend_disconnected_clients{resource_name="$resource_name"})',
    ),
    _tpl(
        key="dyn_router_sched_p95",
        unit="ms",
        category="dynamo",
        dimension="pod",
        promql=(
            'histogram_quantile(0.95, sum(rate('
            'dynamo_router_overhead_scheduling_ms_bucket{'
            'resource_name="$resource_name"}[2m])) by (le))'
        ),
    ),
    _tpl(
        key="dyn_router_overhead_p95",
        unit="ms",
        category="dynamo",
        dimension="pod",
        promql=(
            'histogram_quantile(0.95, sum(rate('
            'dynamo_router_overhead_total_ms_bucket{'
            'resource_name="$resource_name"}[2m])) by (le))'
        ),
    ),
    _tpl(
        key="dyn_model_context_len",
        unit="tokens",
        category="dynamo",
        dimension="pod",
        promql='max(dynamo_frontend_model_context_length{resource_name="$resource_name"})',
    ),
    _tpl(
        key="dyn_model_total_kv_blocks",
        unit="blocks",
        category="dynamo",
        dimension="pod",
        promql='max(dynamo_frontend_model_total_kv_blocks{resource_name="$resource_name"})',
    ),
]


# Ray 引擎指标 (ray_*, Observability add-on 采到 AMP), 按 ray_io_cluster 过滤 (RayCluster 名)。
RAY_ENGINE_TEMPLATES: list[QueryTemplate] = [
    _tpl(
        key="ray_cpu_used",
        unit="cores",
        category="ray",
        dimension="pod",
        group_key="ray_resources",
        promql='sum(ray_resources{ray_io_cluster="$ray_cluster",Name="CPU",State="USED"})',
    ),
    _tpl(
        key="ray_gpu_used",
        unit="GPUs",
        category="ray",
        dimension="pod",
        group_key="ray_resources",
        promql='sum(ray_resources{ray_io_cluster="$ray_cluster",Name="GPU",State="USED"})',
    ),
    _tpl(
        key="ray_object_store_used",
        unit="bytes",
        category="ray",
        dimension="pod",
        group_key="ray_object_store",
        promql='sum(ray_object_store_used_memory{ray_io_cluster="$ray_cluster"})',
    ),
    _tpl(
        key="ray_object_store_avail",
        unit="bytes",
        category="ray",
        dimension="pod",
        group_key="ray_object_store",
        promql='sum(ray_object_store_available_memory{ray_io_cluster="$ray_cluster"})',
    ),
    _tpl(
        key="ray_spilled_bytes",
        unit="bytes",
        category="ray",
        dimension="pod",
        group_key="ray_object_store",
        promql='sum(ray_spill_manager_objects_bytes{ray_io_cluster="$ray_cluster"})',
    ),
    _tpl(
        key="ray_component_cpu",
        unit="%",
        category="ray",
        dimension="pod",
        group_key="ray_components",
        promql='sum by (Component) (ray_component_cpu_percentage{ray_io_cluster="$ray_cluster"})',
    ),
    _tpl(
        key="ray_component_mem",
        unit="MiB",
        category="ray",
        dimension="pod",
        group_key="ray_components",
        promql='sum by (Component) (ray_component_rss_mb{ray_io_cluster="$ray_cluster"})',
    ),
    _tpl(
        key="ray_dashboard_qps",
        unit="req/s",
        category="ray",
        dimension="pod",
        group_key="ray_components",
        promql=(
            'sum(rate(ray_dashboard_api_requests_count_requests_total{'
            'ray_io_cluster="$ray_cluster"}[2m]))'
        ),
    ),
    _tpl(
        key="ray_worker_failures",
        unit="count",
        category="ray",
        dimension="pod",
        group_key="ray_reliability",
        promql='sum(ray_unintentional_worker_failures_total{ray_io_cluster="$ray_cluster"})',
    ),
    _tpl(
        key="ray_worker_startup_fail",
        unit="count",
        category="ray",
        dimension="pod",
        group_key="ray_reliability",
        promql='sum(ray_scheduler_failed_worker_startup_total{ray_io_cluster="$ray_cluster"})',
    ),
]


# Ray 节点级监控复用 TRAINING_TEMPLATES 通用子集 (见 templates.py), 此处不单列。
