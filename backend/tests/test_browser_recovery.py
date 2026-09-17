from app.drivers.base.base_driver import BaseDriver


def test_context_is_alive_false_when_missing():
    driver = BaseDriver()
    assert driver._context_is_alive() is False
