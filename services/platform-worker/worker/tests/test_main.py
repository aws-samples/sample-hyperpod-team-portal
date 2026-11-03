from kubernetes_asyncio.client.exceptions import ApiException

from worker.main import is_fatal


def test_auth_errors_are_fatal():
    assert is_fatal(ApiException(status=401)) is True
    assert is_fatal(ApiException(status=403)) is True


def test_transient_errors_not_fatal():
    assert is_fatal(ApiException(status=500)) is False
    assert is_fatal(ConnectionError("reset")) is False


def test_programming_errors_are_fatal():
    assert is_fatal(TypeError("bug")) is True
    assert is_fatal(KeyError("bug")) is True


def test_informer_runners_has_three():
    from worker.main import _INFORMER_RUNNERS
    names = {r.__name__ for r in _INFORMER_RUNNERS}
    assert names == {
        "run_training_informer",
        "run_inference_informer",
        "run_devinstance_informer",
    }
    assert len(_INFORMER_RUNNERS) == 3
