from backend.modules.safeguards import SafeguardConfig, is_emergency_stopped


def test_kill_switch_off_by_default(monkeypatch):
    monkeypatch.delenv("OLLAMA_CLOUD_EMERGENCY_STOP", raising=False)
    assert is_emergency_stopped(SafeguardConfig.from_env()) is False


def test_kill_switch_on(monkeypatch):
    monkeypatch.setenv("OLLAMA_CLOUD_EMERGENCY_STOP", "true")
    assert is_emergency_stopped(SafeguardConfig.from_env()) is True
