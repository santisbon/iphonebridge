

def test_set_cod_gives_btmgmt_a_pipe_stdin(monkeypatch):
    """btmgmt hangs forever if stdin is /dev/null (epoll EPERM); the run
    call must pass input="" so stdin is a pipe. Regression guard."""
    from iphonebridge import bluez_setup

    seen = {}

    def fake_run(cmd, **kwargs):
        seen.update(kwargs)
        class R:
            returncode = 0
            stdout = "Set Dev Class succeeded"
            stderr = ""
        return R()

    monkeypatch.setattr(bluez_setup.subprocess, "run", fake_run)
    assert bluez_setup.set_cod() is True
    assert seen.get("input") == ""
