"""
HyperPod (SageMaker) async client - aioboto3 wrapper.

Scope: read-only describe/list for cluster management module.
NOT a generic SageMaker SDK; only exposes what platform-api needs.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

import aioboto3
from botocore.exceptions import BotoCoreError, ClientError

from app.core.logging import get_logger

logger = get_logger(__name__)


class HyperPodAPIError(Exception):
    """SageMaker HyperPod API 调用失败的统一异常."""

    def __init__(self, code: str, message: str, cluster_name: str | None = None) -> None:
        self.code = code
        self.message = message
        self.cluster_name = cluster_name
        super().__init__(f"[{code}] {message} (cluster={cluster_name})")


def _iso(value: Any) -> Any:
    """datetime -> ISO string; 其他原样返回."""
    if isinstance(value, datetime):
        return value.isoformat()
    return value


def _normalize_instance_group(ig: dict[str, Any]) -> dict[str, Any]:
    """SageMaker describe_cluster 的 InstanceGroups 字段标准化."""
    return {
        "instance_group_name": ig.get("InstanceGroupName"),
        "instance_type": ig.get("InstanceType"),
        "current_count": ig.get("CurrentCount"),
        "target_count": ig.get("TargetCount"),
        "life_cycle_config": ig.get("LifeCycleConfig"),
        "execution_role": ig.get("ExecutionRole"),
        "threads_per_core": ig.get("ThreadsPerCore"),
        "status": ig.get("Status"),
    }


def _normalize_node(node: dict[str, Any]) -> dict[str, Any]:
    """list_cluster_nodes 返回的 ClusterNodeSummary 字段标准化."""
    instance_status = node.get("InstanceStatus") or {}
    return {
        "node_id": node.get("InstanceId"),
        "instance_group_name": node.get("InstanceGroupName"),
        "instance_type": node.get("InstanceType"),
        "launch_time": _iso(node.get("LaunchTime")),
        "status": instance_status.get("Status"),
        "status_message": instance_status.get("Message"),
        "last_software_update_time": _iso(node.get("LastSoftwareUpdateTime")),
    }


class HyperPodClient:
    """SageMaker HyperPod 异步客户端 (aioboto3).

    使用方式(每次调用建一个短命 client,不 cache session):
        client = HyperPodClient(region="us-west-2")
        info = await client.describe_cluster("my-cluster")
    """

    def __init__(self, region: str, profile: str | None = None) -> None:
        self._region = region
        self._profile = profile

    def _session(self) -> aioboto3.Session:
        if self._profile:
            return aioboto3.Session(profile_name=self._profile, region_name=self._region)
        return aioboto3.Session(region_name=self._region)

    async def describe_cluster(self, cluster_name: str) -> dict[str, Any]:
        """调 SageMaker DescribeCluster,返标准化 dict."""
        session = self._session()
        try:
            async with session.client("sagemaker", region_name=self._region) as sm:
                resp = await sm.describe_cluster(ClusterName=cluster_name)
        except ClientError as exc:
            err_code = exc.response.get("Error", {}).get("Code", "Unknown")
            err_msg = exc.response.get("Error", {}).get("Message", str(exc))
            logger.warning(
                "hyperpod.describe_cluster.client_error",
                cluster=cluster_name,
                code=err_code,
                message=err_msg,
            )
            raise HyperPodAPIError(err_code, err_msg, cluster_name) from exc
        except BotoCoreError as exc:
            logger.error("hyperpod.describe_cluster.botocore_error", cluster=cluster_name, err=str(exc))
            raise HyperPodAPIError("BotoCoreError", str(exc), cluster_name) from exc

        instance_groups = [_normalize_instance_group(ig) for ig in resp.get("InstanceGroups", [])]

        result = {
            "cluster_arn": resp.get("ClusterArn"),
            "cluster_name": resp.get("ClusterName"),
            "cluster_status": resp.get("ClusterStatus"),
            "creation_time": _iso(resp.get("CreationTime")),
            "failure_message": resp.get("FailureMessage"),
            "instance_groups": instance_groups,
            "vpc_config": resp.get("VpcConfig"),
            "orchestrator": resp.get("Orchestrator"),
            "node_recovery": resp.get("NodeRecovery"),
        }
        logger.info(
            "hyperpod.describe_cluster.ok",
            cluster=cluster_name,
            status=result["cluster_status"],
            ig_count=len(instance_groups),
        )
        return result

    # ------------------------------------------------------------------
    # ComputeQuota (Task Governance) APIs
    # 所有返回保留 AWS 原字段大小写(PascalCase),由上层 service 层翻译.
    # ------------------------------------------------------------------

    async def describe_compute_quota(self, compute_quota_id: str) -> dict[str, Any]:
        """调 DescribeComputeQuota,返回 AWS 原 PascalCase dict."""
        session = self._session()
        try:
            async with session.client("sagemaker", region_name=self._region) as sm:
                resp = await sm.describe_compute_quota(ComputeQuotaId=compute_quota_id)
        except ClientError as exc:
            err_code = exc.response.get("Error", {}).get("Code", "Unknown")
            err_msg = exc.response.get("Error", {}).get("Message", str(exc))
            logger.warning(
                "hyperpod.describe_compute_quota.client_error",
                quota_id=compute_quota_id,
                code=err_code,
                message=err_msg,
            )
            raise HyperPodAPIError(err_code, err_msg, None) from exc
        except BotoCoreError as exc:
            logger.error(
                "hyperpod.describe_compute_quota.botocore_error",
                quota_id=compute_quota_id,
                err=str(exc),
            )
            raise HyperPodAPIError("BotoCoreError", str(exc), None) from exc

        resp.pop("ResponseMetadata", None)
        logger.info(
            "hyperpod.describe_compute_quota.ok",
            quota_id=compute_quota_id,
            status=resp.get("Status"),
        )
        return resp

    async def list_compute_quotas(
        self,
        cluster_arn: str | None = None,
        max_results: int = 100,
    ) -> list[dict[str, Any]]:
        """调 ListComputeQuotas + 分页聚合.可选按 ClusterArn 过滤."""
        session = self._session()
        quotas: list[dict[str, Any]] = []
        next_token: str | None = None

        try:
            async with session.client("sagemaker", region_name=self._region) as sm:
                while True:
                    kwargs: dict[str, Any] = {"MaxResults": max_results}
                    if cluster_arn:
                        kwargs["ClusterArn"] = cluster_arn
                    if next_token:
                        kwargs["NextToken"] = next_token
                    resp = await sm.list_compute_quotas(**kwargs)
                    for q in resp.get("ComputeQuotaSummaries", []):
                        quotas.append(q)
                    next_token = resp.get("NextToken")
                    if not next_token:
                        break
        except ClientError as exc:
            err_code = exc.response.get("Error", {}).get("Code", "Unknown")
            err_msg = exc.response.get("Error", {}).get("Message", str(exc))
            logger.warning(
                "hyperpod.list_compute_quotas.client_error",
                cluster_arn=cluster_arn,
                code=err_code,
                message=err_msg,
            )
            raise HyperPodAPIError(err_code, err_msg, None) from exc
        except BotoCoreError as exc:
            logger.error(
                "hyperpod.list_compute_quotas.botocore_error",
                cluster_arn=cluster_arn,
                err=str(exc),
            )
            raise HyperPodAPIError("BotoCoreError", str(exc), None) from exc

        logger.info(
            "hyperpod.list_compute_quotas.ok",
            cluster_arn=cluster_arn,
            count=len(quotas),
        )
        return quotas

    async def create_compute_quota(self, payload: dict[str, Any]) -> dict[str, Any]:
        """调 CreateComputeQuota.payload 字段按 AWS PascalCase,上层负责格式化."""
        session = self._session()
        try:
            async with session.client("sagemaker", region_name=self._region) as sm:
                resp = await sm.create_compute_quota(**payload)
        except ClientError as exc:
            err_code = exc.response.get("Error", {}).get("Code", "Unknown")
            err_msg = exc.response.get("Error", {}).get("Message", str(exc))
            logger.warning(
                "hyperpod.create_compute_quota.client_error",
                name=payload.get("Name"),
                code=err_code,
                message=err_msg,
            )
            raise HyperPodAPIError(err_code, err_msg, None) from exc
        except BotoCoreError as exc:
            logger.error(
                "hyperpod.create_compute_quota.botocore_error",
                name=payload.get("Name"),
                err=str(exc),
            )
            raise HyperPodAPIError("BotoCoreError", str(exc), None) from exc

        resp.pop("ResponseMetadata", None)
        logger.info(
            "hyperpod.create_compute_quota.ok",
            name=payload.get("Name"),
            quota_id=resp.get("ComputeQuotaId"),
        )
        return resp

    async def update_compute_quota(
        self, compute_quota_id: str, target_version: int, payload: dict[str, Any]
    ) -> dict[str, Any]:
        """调 UpdateComputeQuota(乐观锁 · TargetVersion 必须等于当前版本).

        payload 已是 AWS PascalCase,调用方**必须先 describe 拿 target_version**.
        """
        session = self._session()
        kwargs: dict[str, Any] = {
            "ComputeQuotaId": compute_quota_id,
            "TargetVersion": target_version,
            **payload,
        }
        try:
            async with session.client("sagemaker", region_name=self._region) as sm:
                resp = await sm.update_compute_quota(**kwargs)
        except ClientError as exc:
            err_code = exc.response.get("Error", {}).get("Code", "Unknown")
            err_msg = exc.response.get("Error", {}).get("Message", str(exc))
            # 兜底: AWS 对"数据与现有完全相同"的更新抛 ValidationException
            # ("The update data is the same as the existing one")。视为幂等成功,
            # 不报错 (主防线在 orchestration 的无变化短路; 此处接住其比对漏掉的字段)。
            if (
                err_code == "ValidationException"
                and "same as the existing" in err_msg
            ):
                logger.info(
                    "hyperpod.update_compute_quota.noop_same_data",
                    quota_id=compute_quota_id,
                )
                return {"ComputeQuotaId": compute_quota_id}
            logger.warning(
                "hyperpod.update_compute_quota.client_error",
                quota_id=compute_quota_id,
                code=err_code,
                message=err_msg,
            )
            raise HyperPodAPIError(err_code, err_msg, None) from exc
        except BotoCoreError as exc:
            logger.error(
                "hyperpod.update_compute_quota.botocore_error",
                quota_id=compute_quota_id,
                err=str(exc),
            )
            raise HyperPodAPIError("BotoCoreError", str(exc), None) from exc

        resp.pop("ResponseMetadata", None)
        logger.info(
            "hyperpod.update_compute_quota.ok",
            quota_id=compute_quota_id,
            target_version=target_version,
        )
        return resp

    async def delete_compute_quota(self, compute_quota_id: str) -> None:
        """调 DeleteComputeQuota.

        ⚠️ 实测 (boto3 1.x · 2026-05-11): DeleteComputeQuota **不接受 TargetVersion**,
        只有 ComputeQuotaId. 和 cheatsheet §1.5 的旧版描述不一致.
        """
        session = self._session()
        try:
            async with session.client("sagemaker", region_name=self._region) as sm:
                await sm.delete_compute_quota(ComputeQuotaId=compute_quota_id)
        except ClientError as exc:
            err_code = exc.response.get("Error", {}).get("Code", "Unknown")
            err_msg = exc.response.get("Error", {}).get("Message", str(exc))
            logger.warning(
                "hyperpod.delete_compute_quota.client_error",
                quota_id=compute_quota_id,
                code=err_code,
                message=err_msg,
            )
            raise HyperPodAPIError(err_code, err_msg, None) from exc
        except BotoCoreError as exc:
            logger.error(
                "hyperpod.delete_compute_quota.botocore_error",
                quota_id=compute_quota_id,
                err=str(exc),
            )
            raise HyperPodAPIError("BotoCoreError", str(exc), None) from exc

        logger.info(
            "hyperpod.delete_compute_quota.ok",
            quota_id=compute_quota_id,
        )

    # ------------------------------------------------------------------
    # ClusterSchedulerConfig API (集群级 PriorityClass + FairShare)
    # ------------------------------------------------------------------

    async def describe_cluster_scheduler_config(
        self, config_id: str
    ) -> dict[str, Any]:
        session = self._session()
        try:
            async with session.client("sagemaker", region_name=self._region) as sm:
                resp = await sm.describe_cluster_scheduler_config(
                    ClusterSchedulerConfigId=config_id
                )
        except ClientError as exc:
            err_code = exc.response.get("Error", {}).get("Code", "Unknown")
            err_msg = exc.response.get("Error", {}).get("Message", str(exc))
            raise HyperPodAPIError(err_code, err_msg, None) from exc
        except BotoCoreError as exc:
            raise HyperPodAPIError("BotoCoreError", str(exc), None) from exc

        resp.pop("ResponseMetadata", None)
        return resp

    async def list_cluster_scheduler_configs(
        self, cluster_arn: str | None = None, max_results: int = 100
    ) -> list[dict[str, Any]]:
        session = self._session()
        configs: list[dict[str, Any]] = []
        next_token: str | None = None

        try:
            async with session.client("sagemaker", region_name=self._region) as sm:
                while True:
                    kwargs: dict[str, Any] = {"MaxResults": max_results}
                    if cluster_arn:
                        kwargs["ClusterArn"] = cluster_arn
                    if next_token:
                        kwargs["NextToken"] = next_token
                    resp = await sm.list_cluster_scheduler_configs(**kwargs)
                    configs.extend(resp.get("ClusterSchedulerConfigSummaries", []))
                    next_token = resp.get("NextToken")
                    if not next_token:
                        break
        except ClientError as exc:
            err_code = exc.response.get("Error", {}).get("Code", "Unknown")
            err_msg = exc.response.get("Error", {}).get("Message", str(exc))
            raise HyperPodAPIError(err_code, err_msg, None) from exc
        except BotoCoreError as exc:
            raise HyperPodAPIError("BotoCoreError", str(exc), None) from exc

        return configs

    async def list_cluster_nodes(
        self, cluster_name: str, max_results: int = 100
    ) -> list[dict[str, Any]]:
        """调 SageMaker ListClusterNodes,返标准化 list.单页够用;超页循环 NextToken."""
        session = self._session()
        nodes: list[dict[str, Any]] = []
        next_token: str | None = None

        try:
            async with session.client("sagemaker", region_name=self._region) as sm:
                while True:
                    kwargs: dict[str, Any] = {
                        "ClusterName": cluster_name,
                        "MaxResults": max_results,
                    }
                    if next_token:
                        kwargs["NextToken"] = next_token
                    resp = await sm.list_cluster_nodes(**kwargs)
                    for n in resp.get("ClusterNodeSummaries", []):
                        nodes.append(_normalize_node(n))
                    next_token = resp.get("NextToken")
                    if not next_token:
                        break
        except ClientError as exc:
            err_code = exc.response.get("Error", {}).get("Code", "Unknown")
            err_msg = exc.response.get("Error", {}).get("Message", str(exc))
            logger.warning(
                "hyperpod.list_cluster_nodes.client_error",
                cluster=cluster_name,
                code=err_code,
                message=err_msg,
            )
            raise HyperPodAPIError(err_code, err_msg, cluster_name) from exc
        except BotoCoreError as exc:
            logger.error("hyperpod.list_cluster_nodes.botocore_error", cluster=cluster_name, err=str(exc))
            raise HyperPodAPIError("BotoCoreError", str(exc), cluster_name) from exc

        logger.info("hyperpod.list_cluster_nodes.ok", cluster=cluster_name, count=len(nodes))
        return nodes
