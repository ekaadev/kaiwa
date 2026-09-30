import asyncio

import pytest

from app.livekit_practice import LiveKitGateway, LiveKitPracticeStarter, livekit_practice_from_env
from app.practice import PracticeIssue, PracticeUnavailable


class FakeGateway:
    url = "wss://example.livekit.cloud"

    def __init__(self):
        self.created = []
        self.deleted = []
        self.tokens = []
        self.available = True

    async def ready(self):
        return self.available

    async def create_room(self, name):
        self.created.append(name)

    async def delete_room(self, name):
        self.deleted.append(name)

    def join_token(self, name, *, bot):
        self.tokens.append((name, bot))
        return "bot-token" if bot else "client-token"


def test_returns_credentials_only_after_bot_connects_and_cleans_on_shutdown(monkeypatch):
    connected = asyncio.Event()

    async def connected_bot(url, token, name, ready):
        connected.set()
        ready.set()
        await asyncio.Event().wait()

    monkeypatch.setattr("app.livekit_practice.run_transport_bot", connected_bot)

    async def scenario():
        gateway = FakeGateway()
        starter = LiveKitPracticeStarter(gateway, max_active_calls=1)
        assert (await starter.ready()).ready

        call = await starter.start(eot_method="adaptive")

        assert connected.is_set()
        assert call.room_url == gateway.url
        assert call.join_token == "client-token"
        assert gateway.created == [f"practice-{call.call_id.hex}"]
        assert gateway.tokens == [(gateway.created[0], True), (gateway.created[0], False)]
        assert (await starter.ready()).reason == PracticeIssue.CAPACITY_FULL

        with pytest.raises(PracticeUnavailable) as exc:
            await starter.start(eot_method="adaptive")
        assert exc.value.reason == PracticeIssue.CAPACITY_FULL
        assert gateway.created == [f"practice-{call.call_id.hex}"]

        await starter.aclose()
        assert gateway.deleted == gateway.created
        assert (await starter.ready()).ready

    asyncio.run(scenario())


def test_bot_failure_does_not_return_a_client_token_and_deletes_room(monkeypatch):
    async def failed_bot(url, token, name, ready):
        raise RuntimeError("bot failed before joining")

    monkeypatch.setattr("app.livekit_practice.run_transport_bot", failed_bot)

    async def scenario():
        gateway = FakeGateway()
        starter = LiveKitPracticeStarter(gateway)

        with pytest.raises(PracticeUnavailable):
            await starter.start(eot_method="adaptive")

        assert gateway.deleted == gateway.created
        assert gateway.tokens == [(gateway.created[0], True)]
        assert (await starter.ready()).ready

    asyncio.run(scenario())


def test_tutor_not_ready_fails_before_room_is_created():
    class UnavailableTutor:
        async def ready(self):
            return False

    async def scenario():
        gateway = FakeGateway()
        starter = LiveKitPracticeStarter(gateway, tutor=UnavailableTutor())

        assert (await starter.ready()).reason == PracticeIssue.SERVICE_UNAVAILABLE
        with pytest.raises(PracticeUnavailable):
            await starter.start(eot_method="adaptive")
        assert gateway.created == gateway.deleted == gateway.tokens == []

    asyncio.run(scenario())


def test_tutor_setup_failure_deletes_room_before_issuing_client_token(monkeypatch):
    class AvailableTutor:
        async def ready(self):
            return True

    async def failed_bot(url, token, name, ready, tutor=None, **kwargs):
        raise RuntimeError("tutor models could not be loaded")

    monkeypatch.setattr("app.livekit_practice.run_transport_bot", failed_bot)

    async def scenario():
        gateway = FakeGateway()
        starter = LiveKitPracticeStarter(gateway, tutor=AvailableTutor())

        with pytest.raises(PracticeUnavailable):
            await starter.start(eot_method="adaptive")

        assert gateway.deleted == gateway.created
        assert gateway.tokens == [(gateway.created[0], True)]

    asyncio.run(scenario())


def test_bot_join_timeout_removes_room_and_releases_capacity(monkeypatch):
    async def never_joins(url, token, name, ready):
        await asyncio.Event().wait()

    monkeypatch.setattr("app.livekit_practice.run_transport_bot", never_joins)
    monkeypatch.setattr("app.livekit_practice.BOT_JOIN_TIMEOUT_SECONDS", 0.01)

    async def scenario():
        gateway = FakeGateway()
        starter = LiveKitPracticeStarter(gateway, max_active_calls=1)

        with pytest.raises(PracticeUnavailable):
            await starter.start(eot_method="adaptive")

        assert gateway.deleted == gateway.created
        assert (await starter.ready()).ready

    asyncio.run(scenario())


def test_room_creation_failure_cannot_issue_tokens_or_reserve_capacity():
    class UnavailableGateway(FakeGateway):
        async def create_room(self, name):
            self.created.append(name)
            raise RuntimeError("LiveKit unavailable")

    async def scenario():
        gateway = UnavailableGateway()
        starter = LiveKitPracticeStarter(gateway, max_active_calls=1)

        with pytest.raises(PracticeUnavailable):
            await starter.start(eot_method="adaptive")

        assert gateway.tokens == []
        assert gateway.deleted == gateway.created
        assert (await starter.ready()).ready

    asyncio.run(scenario())


def test_livekit_api_failure_reports_service_unavailable_without_creating_room():
    async def scenario():
        gateway = FakeGateway()
        gateway.available = False
        starter = LiveKitPracticeStarter(gateway)

        assert (await starter.ready()).reason == PracticeIssue.SERVICE_UNAVAILABLE
        assert gateway.created == []

    asyncio.run(scenario())


def test_readiness_times_out_if_livekit_api_never_responds(monkeypatch):
    class HangingGateway(FakeGateway):
        async def ready(self):
            await asyncio.Event().wait()

    monkeypatch.setattr("app.livekit_practice.READINESS_TIMEOUT_SECONDS", 0.01)

    async def scenario():
        gateway = HangingGateway()
        starter = LiveKitPracticeStarter(gateway)

        assert (await starter.ready()).reason == PracticeIssue.SERVICE_UNAVAILABLE
        assert gateway.created == []

    asyncio.run(scenario())


def test_missing_livekit_configuration_disables_practice(monkeypatch):
    monkeypatch.delenv("LIVEKIT_API_SECRET", raising=False)
    monkeypatch.setenv("LIVEKIT_URL", "wss://example.livekit.cloud")
    monkeypatch.setenv("LIVEKIT_API_KEY", "test-key")

    assert livekit_practice_from_env() is None


def test_livekit_alone_does_not_enable_a_silent_practice_bot(monkeypatch):
    monkeypatch.setenv("LIVEKIT_URL", "wss://example.livekit.cloud")
    monkeypatch.setenv("LIVEKIT_API_KEY", "test-key")
    monkeypatch.setenv("LIVEKIT_API_SECRET", "test-secret")
    monkeypatch.delenv("TUTOR_LLM_BASE_URL", raising=False)

    assert livekit_practice_from_env() is None


def test_client_token_is_scoped_to_one_room_and_cannot_manage_it():
    jwt = pytest.importorskip("jwt")
    pytest.importorskip("livekit.api")
    gateway = LiveKitGateway(
        "wss://example.livekit.cloud",
        "test-api-key",
        "test-secret-value-with-at-least-32-characters",
    )

    token = gateway.join_token("practice-test-room", bot=False)
    claims = jwt.decode(token, options={"verify_signature": False})

    assert claims["video"]["room"] == "practice-test-room"
    assert claims["video"]["roomJoin"] is True
    assert claims["video"]["canPublishSources"] == ["microphone"]
    assert claims["video"].get("roomAdmin") is not True
