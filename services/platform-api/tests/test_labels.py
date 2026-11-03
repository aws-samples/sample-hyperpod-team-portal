import pytest
from fastapi import HTTPException

from app.core.labels import validate_user_labels


def test_empty_returns_empty():
    assert validate_user_labels(None) == {}
    assert validate_user_labels({}) == {}


def test_valid_labels_pass():
    out = validate_user_labels({"project": "nlp-q3", "team": "search", "exp": "ablation-1"})
    assert out == {"project": "nlp-q3", "team": "search", "exp": "ablation-1"}


def test_empty_value_allowed():
    assert validate_user_labels({"archived": ""}) == {"archived": ""}


def test_reserved_prefix_rejected():
    for key in (
        "platform.hyperpod.io/inference-id",
        "kueue.x-k8s.io/queue-name",
        "sagemaker.foo",
        "kubernetes.io/role",
        "app.kubernetes.io/name",
    ):
        with pytest.raises(HTTPException) as e:
            validate_user_labels({key: "x"})
        assert e.value.status_code == 422


def test_illegal_chars_rejected():
    for bad in ({"项目": "v"}, {"k": "有空格 值"}, {"-bad": "v"}, {"k": "中文值"}):
        with pytest.raises(HTTPException):
            validate_user_labels(bad)


def test_too_long_rejected():
    with pytest.raises(HTTPException):
        validate_user_labels({"k": "a" * 64})


def test_over_limit_rejected():
    with pytest.raises(HTTPException):
        validate_user_labels({f"k{i}": "v" for i in range(11)})


def test_empty_key_rejected():
    with pytest.raises(HTTPException):
        validate_user_labels({"  ": "v"})
