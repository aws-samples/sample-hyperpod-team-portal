"""domain/hyperpodrun.py 单元测试 · 纯函数不依赖 IO."""

from __future__ import annotations

from app.modules.training.domain.hyperpodrun import wrap_with_hyperpodrun


class TestWrapWithHyperpodrun:
    def test_passthrough_when_user_already_uses_hyperpodrun(self) -> None:
        """用户自己写了 hyperpodrun, 尊重用户, 原样返回."""
        cmd = "hyperpodrun --nnodes=2 --nproc-per-node=4 train.py"
        assert wrap_with_hyperpodrun(cmd, gpu_per_node=4) == cmd

    def test_pure_python_command_passed_directly(self) -> None:
        """纯 'python xxx.py args' · 直接当 hyperpodrun training_script."""
        wrapped = wrap_with_hyperpodrun(
            "python -u /workspace/train.py --epochs 10", gpu_per_node=2
        )
        assert "pip install -q hyperpod-elastic-agent" in wrapped
        assert "exec hyperpodrun" in wrapped
        assert "--nproc-per-node=2" in wrapped
        assert "--server-port=8080" in wrapped
        # 纯 python 分支 不走 --no-python
        assert "--no-python" not in wrapped
        assert "/workspace/train.py" in wrapped
        assert "--epochs 10" in wrapped

    def test_shell_command_with_pip_install_uses_no_python_branch(self) -> None:
        """含 '&&' 的复合 shell 命令必走 --no-python + /bin/bash -c."""
        wrapped = wrap_with_hyperpodrun(
            "pip install -r /code/requirements.txt && python /code/train.py --max_steps 500",
            gpu_per_node=4,
        )
        assert "--no-python" in wrapped
        assert "/bin/bash -c" in wrapped
        assert "--nproc-per-node=4" in wrapped
        assert "pip install -r /code/requirements.txt" in wrapped

    def test_shell_only_command_falls_into_shell_branch(self) -> None:
        """纯 shell 命令 · 走 --no-python + bash -c."""
        wrapped = wrap_with_hyperpodrun("echo hello && sleep 10", gpu_per_node=0)
        assert "--no-python" in wrapped
        assert "/bin/bash -c" in wrapped
        # gpu=0 时 nproc 退化为 1
        assert "--nproc-per-node=1" in wrapped

    def test_gpu_zero_defaults_nproc_to_one(self) -> None:
        """GPU=0 (CPU-only 训练) · nproc 必须 ≥1, 退化为 1."""
        wrapped = wrap_with_hyperpodrun("python train.py", gpu_per_node=0)
        assert "--nproc-per-node=1" in wrapped

    def test_gpu_eight_maps_to_nproc_eight(self) -> None:
        """GPU=8 典型 HyperPod 节点规格."""
        wrapped = wrap_with_hyperpodrun("python train.py", gpu_per_node=8)
        assert "--nproc-per-node=8" in wrapped

    def test_default_log_dir_is_tmp(self) -> None:
        """不传 log_dir → 默 /tmp/hyperpod (临时, 随 pod 删)."""
        wrapped = wrap_with_hyperpodrun("python train.py", gpu_per_node=1)
        assert "--log_dir=/tmp/hyperpod" in wrapped

    def test_custom_log_dir_for_fsx_archive(self) -> None:
        """传 log_dir=FSx 路径 → 日志落 FSx (持久归档) + mkdir -p 先建多层目录."""
        wrapped = wrap_with_hyperpodrun(
            "python train.py",
            gpu_per_node=2,
            log_dir="/fsx/outputs/my-job/logs",
        )
        assert "--log_dir=/fsx/outputs/my-job/logs" in wrapped
        assert "mkdir -p /fsx/outputs/my-job/logs" in wrapped
        assert "--log_dir=/tmp/hyperpod" not in wrapped
        # umask 0007 + chmod 2770: 让 torch 建的日志目录组(team)可进, 开发机同组可读
        assert "umask 0007" in wrapped
        assert "chmod 2770 /fsx/outputs/my-job/logs" in wrapped
        # 后台 chmod 循环: 掰开 torch mkdtemp 的 0700 (none_xxx 层), 仅 FSx log_dir 启
        assert "setsid sh -c" in wrapped
        assert "chmod -R g+rwX /fsx/outputs/my-job/logs" in wrapped

    def test_no_chmod_daemon_for_tmp_logdir(self) -> None:
        """默认 /tmp log_dir → 不启后台 chmod 循环 (临时盘无需开放给开发机)."""
        wrapped = wrap_with_hyperpodrun("python train.py", gpu_per_node=1)
        assert "setsid sh -c" not in wrapped
        assert "chmod -R g+rwX" not in wrapped

    def test_custom_log_dir_shell_branch(self) -> None:
        """shell 分支 (pip && python) 也用自定义 log_dir."""
        wrapped = wrap_with_hyperpodrun(
            "pip install -r /fsx/code/req.txt && python /fsx/code/train.py",
            gpu_per_node=2,
            log_dir="/fsx/outputs/j/logs",
        )
        assert "--log_dir=/fsx/outputs/j/logs" in wrapped
        assert "mkdir -p /fsx/outputs/j/logs" in wrapped
