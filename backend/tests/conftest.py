import pytest


@pytest.fixture(autouse=True)
def isolate_background_title_models(monkeypatch):
    import app.services.conversation_titles as titles
    class StubSupervisor:
        def __init__(self, config):
            pass
        def run(self, first_turn):
            return {"approved": False, "attempts": [], "usage": []}
    monkeypatch.setattr(titles, "TitleSupervisor", StubSupervisor)
    monkeypatch.setattr(titles, "require_runtime_model", lambda *args: None)


@pytest.fixture(autouse=True)
def isolate_background_memory_models(monkeypatch):
    from app.services.long_term_memory import LongTermMemory
    # Background generation is exercised explicitly with controlled model responses.
    monkeypatch.setattr(LongTermMemory, "start", lambda self: self.files.policy())
