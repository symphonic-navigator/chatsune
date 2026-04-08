from backend.modules.safeguards import SafeguardConfig


_ENV_VARS = [
    "OLLAMA_CLOUD_EMERGENCY_STOP",
    "JOB_RATE_LIMIT_WINDOW_SECONDS",
    "JOB_RATE_LIMIT_MAX_CALLS",
    "JOB_QUEUE_CAP_PER_USER",
    "JOB_DAILY_TOKEN_BUDGET",
    "JOB_CIRCUIT_FAILURE_THRESHOLD",
    "JOB_CIRCUIT_WINDOW_SECONDS",
    "JOB_CIRCUIT_OPEN_SECONDS",
]


def _clear_env(monkeypatch):
    for v in _ENV_VARS:
        monkeypatch.delenv(v, raising=False)


def test_defaults_when_env_empty(monkeypatch):
    _clear_env(monkeypatch)
    c = SafeguardConfig.from_env()
    assert c.emergency_stop is False
    assert c.rate_limit_window_seconds == 60
    assert c.rate_limit_max_calls == 50
    assert c.queue_cap_per_user == 10
    assert c.daily_token_budget == 5_000_000
    assert c.circuit_failure_threshold == 5
    assert c.circuit_window_seconds == 300
    assert c.circuit_open_seconds == 900
    assert c.queue_cap_enabled is True
    assert c.budget_enabled is True


def test_env_vars_coerced(monkeypatch):
    _clear_env(monkeypatch)
    monkeypatch.setenv("OLLAMA_CLOUD_EMERGENCY_STOP", "true")
    monkeypatch.setenv("JOB_RATE_LIMIT_WINDOW_SECONDS", "30")
    monkeypatch.setenv("JOB_RATE_LIMIT_MAX_CALLS", "7")
    monkeypatch.setenv("JOB_QUEUE_CAP_PER_USER", "3")
    monkeypatch.setenv("JOB_DAILY_TOKEN_BUDGET", "1234")
    monkeypatch.setenv("JOB_CIRCUIT_FAILURE_THRESHOLD", "2")
    monkeypatch.setenv("JOB_CIRCUIT_WINDOW_SECONDS", "120")
    monkeypatch.setenv("JOB_CIRCUIT_OPEN_SECONDS", "600")
    c = SafeguardConfig.from_env()
    assert c.emergency_stop is True
    assert c.rate_limit_window_seconds == 30
    assert c.rate_limit_max_calls == 7
    assert c.queue_cap_per_user == 3
    assert c.daily_token_budget == 1234
    assert c.circuit_failure_threshold == 2
    assert c.circuit_window_seconds == 120
    assert c.circuit_open_seconds == 600


def test_queue_cap_zero_disables(monkeypatch):
    _clear_env(monkeypatch)
    monkeypatch.setenv("JOB_QUEUE_CAP_PER_USER", "0")
    assert SafeguardConfig.from_env().queue_cap_enabled is False


def test_budget_zero_disables(monkeypatch):
    _clear_env(monkeypatch)
    monkeypatch.setenv("JOB_DAILY_TOKEN_BUDGET", "0")
    assert SafeguardConfig.from_env().budget_enabled is False


def test_kill_switch_accepts_various_truthy(monkeypatch):
    for truthy in ("true", "TRUE", "True", "1", "yes", "on"):
        _clear_env(monkeypatch)
        monkeypatch.setenv("OLLAMA_CLOUD_EMERGENCY_STOP", truthy)
        assert SafeguardConfig.from_env().emergency_stop is True
    for falsy in ("false", "FALSE", "0", "no", "off", ""):
        _clear_env(monkeypatch)
        monkeypatch.setenv("OLLAMA_CLOUD_EMERGENCY_STOP", falsy)
        assert SafeguardConfig.from_env().emergency_stop is False
