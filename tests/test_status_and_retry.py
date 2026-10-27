"""GetStatus's per-feature liveness, and the session reopen loop's interval."""
from iphonebridge import daemon
from iphonebridge.dbus_service import profile_status


class Sessions:
    def __init__(self, map_alive, pbap_alive):
        self._map, self._pbap = map_alive, pbap_alive

    def map_alive(self):
        return self._map

    def pbap_alive(self):
        return self._pbap


class Flag:
    def __init__(self, **attrs):
        self.__dict__.update(attrs)


def test_status_reports_every_feature():
    status = profile_status(Sessions(True, True), Flag(active=True),
                            Flag(ready=True), Flag(connected=True))
    assert status == {"map": True, "pbap": True, "ancs": True,
                      "hfp": True, "avrcp": True}


def test_status_reports_missing_calls_and_media():
    status = profile_status(Sessions(True, False), Flag(active=False),
                            Flag(ready=False), Flag(connected=False))
    assert status == {"map": True, "pbap": False, "ancs": False,
                      "hfp": False, "avrcp": False}


def test_status_without_optional_managers():
    status = profile_status(Sessions(False, False), None, None, None)
    assert status == {"map": False, "pbap": False, "ancs": False,
                      "hfp": False, "avrcp": False}


def test_retry_is_fast_at_first_then_slow():
    assert daemon.session_retry_interval(0) == daemon.SESSION_RETRY_FAST_SEC
    assert daemon.session_retry_interval(daemon.SESSION_RETRY_FAST_FOR_SEC - 1) \
        == daemon.SESSION_RETRY_FAST_SEC
    assert daemon.session_retry_interval(daemon.SESSION_RETRY_FAST_FOR_SEC) \
        == daemon.SESSION_RETRY_SEC
    assert daemon.SESSION_RETRY_FAST_SEC < daemon.SESSION_RETRY_SEC
