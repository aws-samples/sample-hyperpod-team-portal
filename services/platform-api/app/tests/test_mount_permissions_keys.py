from app.adapters.ddb import tables


def test_mount_perm_key_format():
    assert tables.mount_perm_key("data1", "alice") == "MOUNT#data1#USER#alice"


def test_mount_perm_prefix_is_key_prefix():
    key = tables.mount_perm_key("data1", "alice")
    prefix = tables.mount_perm_prefix("data1")
    assert key.startswith(prefix)


def test_mount_perm_prefix_distinguishes_mounts():
    # 不同 mount 的前缀不互相命中
    assert not tables.mount_perm_key("data2", "alice").startswith(
        tables.mount_perm_prefix("data1")
    )
