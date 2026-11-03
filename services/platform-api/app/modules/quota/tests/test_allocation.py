"""domain/allocation.py · Kueue status 解析器单测."""

from __future__ import annotations

from app.modules.quota.domain.allocation import parse_cluster_queue_status


class TestParseClusterQueueStatus:
    def test_empty_status_returns_zero(self) -> None:
        usage = parse_cluster_queue_status("team-a", None)
        assert usage.team_name == "team-a"
        assert usage.resources == []
        assert usage.totals.accelerators == 0
        assert usage.totals.v_cpu == 0.0
        assert usage.totals.memory_in_gi_b == 0.0

    def test_empty_dict_returns_zero(self) -> None:
        usage = parse_cluster_queue_status("team-a", {})
        # dict 是 "falsy" · 走 not status 分支
        assert usage.resources == []

    def test_single_flavor_gpu(self) -> None:
        status = {
            "flavorsUsage": [
                {
                    "name": "flavor-p4d",
                    "resources": [
                        {"name": "cpu", "total": "96"},
                        {"name": "memory", "total": "1152Gi"},
                        {"name": "nvidia.com/gpu", "total": "8"},
                    ],
                }
            ],
            "pendingWorkloads": 3,
        }
        usage = parse_cluster_queue_status("team-a", status)
        assert len(usage.resources) == 1
        r = usage.resources[0]
        assert r.instance_type == "flavor-p4d"
        assert r.v_cpu_used == 96.0
        assert r.memory_used_in_gi_b == 1152.0
        assert r.accelerators_used == 8
        # pendingWorkloads 全挂 totals
        assert usage.totals.accelerators == 8
        assert usage.totals.accelerators_pending == 3
        assert usage.totals.v_cpu == 96.0
        assert usage.totals.memory_in_gi_b == 1152.0

    def test_multiple_flavors_aggregate(self) -> None:
        status = {
            "flavorsUsage": [
                {
                    "name": "flavor-p4d",
                    "resources": [
                        {"name": "cpu", "total": "96"},
                        {"name": "nvidia.com/gpu", "total": "8"},
                    ],
                },
                {
                    "name": "flavor-g5",
                    "resources": [
                        {"name": "cpu", "total": "48"},
                        {"name": "nvidia.com/gpu", "total": "4"},
                    ],
                },
            ]
        }
        usage = parse_cluster_queue_status("team-a", status)
        assert len(usage.resources) == 2
        assert usage.totals.accelerators == 12  # 8+4
        assert usage.totals.v_cpu == 144.0      # 96+48
        assert usage.totals.accelerators_pending == 0  # 无 pending 字段

    def test_neuron_device_also_counted(self) -> None:
        status = {
            "flavorsUsage": [
                {
                    "name": "flavor-trn1",
                    "resources": [
                        {"name": "aws.amazon.com/neurondevice", "total": "16"},
                    ],
                }
            ]
        }
        usage = parse_cluster_queue_status("team-n", status)
        assert usage.resources[0].accelerators_used == 16
        assert usage.totals.accelerators == 16

    def test_falls_back_to_flavors_reservation(self) -> None:
        """flavorsUsage 空时, 用 flavorsReservation."""
        status = {
            "flavorsReservation": [
                {
                    "name": "flavor-reserved",
                    "resources": [
                        {"name": "nvidia.com/gpu", "total": "2"},
                    ],
                }
            ]
        }
        usage = parse_cluster_queue_status("team-r", status)
        assert usage.resources[0].accelerators_used == 2

    def test_memory_units_mix(self) -> None:
        status = {
            "flavorsUsage": [
                {
                    "name": "mixed",
                    "resources": [
                        {"name": "memory", "total": "1Gi"},
                    ],
                },
                {
                    "name": "mixed2",
                    "resources": [
                        {"name": "memory", "total": "1024Mi"},
                    ],
                },
            ]
        }
        usage = parse_cluster_queue_status("team-m", status)
        # 两个 flavor 各 1 GiB
        assert abs(usage.totals.memory_in_gi_b - 2.0) < 1e-3
