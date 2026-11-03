from app.adapters.ddb import tables


def test_share_key_encoding():
    assert tables.share_key("dev", "abc-123", "alice") == "SHARE#dev#abc-123#USER#alice"
    assert tables.share_key("train", "xyz-456", "bob") == "SHARE#train#xyz-456#USER#bob"


def test_share_prefix_encoding():
    assert tables.share_prefix("dev", "abc-123") == "SHARE#dev#abc-123#USER#"


def test_share_prefix_is_key_prefix():
    # share_key 必须以对应 prefix 开头 (begins_with 查询依赖)
    k = tables.share_key("dev", "abc-123", "alice")
    p = tables.share_prefix("dev", "abc-123")
    assert k.startswith(p)


def test_shares_table_and_gsi_constants():
    assert tables.RESOURCE_SHARES_TABLE.endswith("ResourceShares")
    assert tables.RESOURCE_SHARES_GSI_USER == "target-username-index"
    assert tables.RESOURCE_SHARES_TABLE in tables.ALL_TABLES
