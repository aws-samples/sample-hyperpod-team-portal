"""Manual smoke test - real AWS call. Run once to prove client works."""

import asyncio

from app.core.logging import setup_logging
from app.services.hyperpod_client import HyperPodClient

CLUSTER = "hp-cluster-hypd-0507-9390"


async def main() -> None:
    setup_logging()
    client = HyperPodClient(region="us-west-2")

    info = await client.describe_cluster(CLUSTER)
    print("cluster_status:", info["cluster_status"])
    print("arn:", info["cluster_arn"])
    print("creation_time:", info["creation_time"])
    print("instance_groups:", len(info["instance_groups"]))
    for ig in info["instance_groups"]:
        print(f"  - {ig['instance_group_name']} / {ig['instance_type']} / current={ig['current_count']}")

    nodes = await client.list_cluster_nodes(CLUSTER)
    print(f"nodes: {len(nodes)}")
    for n in nodes[:5]:
        print(f"  - {n['node_id']} / {n['instance_type']} / {n['status']}")


if __name__ == "__main__":
    asyncio.run(main())
