from app import llm


def test_existing_cli_status_does_not_claim_verified(monkeypatch):
    monkeypatch.setenv('KEPU_LLM_MODE', 'live')
    monkeypatch.setattr(llm.shutil, 'which', lambda name: '/bin/claude')
    state = llm.provider_status()
    assert state['configured'] and state['provider'] == 'claude_cli'
    assert state['model'] == llm.MODEL and state['verified'] is False


def test_sdk_status_never_contains_credentials(monkeypatch):
    monkeypatch.setenv('KEPU_LLM_MODE', 'live')
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-only-private-key')
    monkeypatch.setenv('ANTHROPIC_BASE_URL', 'https://user:password@example.test/?secret=private')
    state = llm.provider_status()
    assert state['provider'] == 'anthropic_sdk'
    assert 'private' not in str(state) and 'password' not in str(state)
    assert state['base_url'] is None


def test_unconfigured_and_replay_are_distinct(monkeypatch):
    monkeypatch.setattr(llm.shutil, 'which', lambda name: None)
    monkeypatch.setenv('KEPU_LLM_MODE', 'live')
    assert not llm.provider_status()['configured']
    monkeypatch.setenv('KEPU_LLM_MODE', 'replay')
    state = llm.provider_status()
    assert state['configured'] and state['provider'] == 'replay'
    assert '离线' in state['note'] and not state['verified']
    monkeypatch.setenv('KEPU_LLM_MODE', 'invalid')
    assert not llm.provider_status()['configured']
