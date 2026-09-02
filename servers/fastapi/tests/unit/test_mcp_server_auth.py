import asyncio
from types import SimpleNamespace
import uuid

import httpx
import pytest

import mcp_server
from models.sql.access_token import AccessToken as DatabaseAccessToken
from models.sql.user import User


def test_is_mcp_server_enabled_in_server_deployments(monkeypatch):
    monkeypatch.setattr(mcp_server, "is_presenton_electron_desktop", lambda: False)

    assert mcp_server.is_mcp_server_enabled() is True


def test_is_mcp_server_disabled_in_electron_desktop(monkeypatch):
    monkeypatch.setattr(mcp_server, "is_presenton_electron_desktop", lambda: True)

    assert mcp_server.is_mcp_server_enabled() is False


def test_create_mcp_auth_provider_disabled_when_auth_is_disabled(monkeypatch):
    monkeypatch.setattr(mcp_server, "is_disable_auth_enabled", lambda: True)

    assert mcp_server.create_mcp_auth_provider() is None


def test_create_mcp_auth_provider_enabled_for_server_auth(monkeypatch):
    monkeypatch.setattr(mcp_server, "is_disable_auth_enabled", lambda: False)

    provider = mcp_server.create_mcp_auth_provider()
    assert isinstance(provider, mcp_server.PresentonTokenVerifier)


def _mock_token_database(monkeypatch, token: str | None):
    user_id = uuid.uuid4()
    user = User(
        id=user_id,
        username="admin",
        hashed_password="unused",
        is_active=True,
        is_superuser=True,
        is_verified=True,
    )
    access_token = (
        DatabaseAccessToken(token=token, user_id=user_id) if token else None
    )

    class FakeSession:
        async def get(self, model, key):
            if model is DatabaseAccessToken and access_token and key == token:
                return access_token
            if model is User and key == user_id:
                return user
            return None

    class SessionContext:
        async def __aenter__(self):
            return FakeSession()

        async def __aexit__(self, *_args):
            return None

    monkeypatch.setattr(mcp_server, "async_session_maker", SessionContext)
    return user


def test_presenton_token_verifier_accepts_valid_admin_access_key(monkeypatch):
    token = "sk-presenton-valid"
    user = _mock_token_database(monkeypatch, token)
    verifier = mcp_server.PresentonTokenVerifier()

    access_token = asyncio.run(verifier.verify_token(token))

    assert access_token is not None
    assert access_token.token == token
    assert access_token.client_id == str(user.id)
    assert access_token.claims["u"] == "admin"


def test_presenton_token_verifier_uses_generation_length_internal_session(monkeypatch):
    token = "sk-presenton-valid"
    _mock_token_database(monkeypatch, token)
    captured = {}

    class Strategy:
        async def write_token(self, _user):
            return "internal-session"

    def strategy(*, lifetime_seconds):
        captured["lifetime_seconds"] = lifetime_seconds
        return Strategy()

    monkeypatch.setattr(mcp_server, "get_jwt_strategy", strategy)

    access_token = asyncio.run(mcp_server.PresentonTokenVerifier().verify_token(token))

    assert access_token is not None
    assert access_token.claims["internal_session_token"] == "internal-session"
    assert captured["lifetime_seconds"] == 60 * 60


def test_presenton_token_verifier_rejects_invalid_token(monkeypatch):
    _mock_token_database(monkeypatch, None)
    verifier = mcp_server.PresentonTokenVerifier()

    access_token = asyncio.run(
        verifier.verify_token("sk-presenton-invalid-token")
    )

    assert access_token is None


def test_attach_request_auth_header_uses_authenticated_mcp_token(monkeypatch):
    monkeypatch.setattr(mcp_server, "get_http_headers", lambda include=None: {})
    monkeypatch.setattr(
        mcp_server,
        "get_access_token",
        lambda: SimpleNamespace(token="session-abc"),
    )
    request = httpx.Request("POST", "http://127.0.0.1:8000/api/v1/example")

    asyncio.run(mcp_server.attach_request_auth_header(request))

    assert request.headers["Authorization"] == "Bearer session-abc"


def test_attach_request_auth_header_uses_internal_session_without_forwarding_key(
    monkeypatch,
):
    monkeypatch.setattr(mcp_server, "get_http_headers", lambda include=None: {})
    monkeypatch.setattr(
        mcp_server,
        "get_access_token",
        lambda: SimpleNamespace(
            token="sk-presenton-mcp-secret",
            claims={
                "user_id": str(uuid.uuid4()),
                "internal_session_token": "short-lived-session",
            },
        ),
    )
    request = httpx.Request("POST", "http://127.0.0.1:8000/api/v1/example")

    asyncio.run(mcp_server.attach_request_auth_header(request))

    assert "Authorization" not in request.headers
    assert "short-lived-session" in request.headers["Cookie"]
    assert "sk-presenton" not in request.headers["Cookie"]


def test_attach_request_auth_header_keeps_existing_auth_header(monkeypatch):
    monkeypatch.setattr(mcp_server, "get_http_headers", lambda include=None: {})
    monkeypatch.setattr(
        mcp_server,
        "get_access_token",
        lambda: SimpleNamespace(token="session-abc"),
    )
    request = httpx.Request(
        "POST",
        "http://127.0.0.1:8000/api/v1/example",
        headers={"Authorization": "Bearer existing"},
    )

    asyncio.run(mcp_server.attach_request_auth_header(request))

    assert request.headers["Authorization"] == "Bearer existing"


def test_attach_request_auth_header_skips_when_no_mcp_access_token(monkeypatch):
    monkeypatch.setattr(mcp_server, "get_access_token", lambda: None)
    monkeypatch.setattr(mcp_server, "get_http_headers", lambda include=None: {})
    request = httpx.Request("POST", "http://127.0.0.1:8000/api/v1/example")

    asyncio.run(mcp_server.attach_request_auth_header(request))

    assert "Authorization" not in request.headers


def test_attach_request_auth_header_forwards_incoming_authorization_header(monkeypatch):
    monkeypatch.setattr(mcp_server, "get_access_token", lambda: None)
    monkeypatch.setattr(
        mcp_server,
        "get_http_headers",
        lambda include=None: {"authorization": "Basic YWRtaW46c2VjcmV0MTIz"},
    )
    request = httpx.Request("POST", "http://127.0.0.1:8000/api/v1/example")

    asyncio.run(mcp_server.attach_request_auth_header(request))

    assert request.headers["Authorization"].startswith("Basic ")


def test_attach_request_auth_header_forwards_public_origin(monkeypatch):
    monkeypatch.setattr(mcp_server, "get_access_token", lambda: None)
    monkeypatch.setattr(
        mcp_server,
        "get_http_headers",
        lambda include=None: {
            "host": "internal.example",
            "x-forwarded-host": "presenton.example.com",
            "x-forwarded-proto": "https",
        },
    )
    request = httpx.Request("GET", "http://127.0.0.1:8000/api/v1/ppt/template/all")

    asyncio.run(mcp_server.attach_request_auth_header(request))

    assert request.headers["X-Forwarded-Host"] == "presenton.example.com"
    assert request.headers["X-Forwarded-Proto"] == "https"


def test_get_mcp_api_timeout_supports_long_running_requests():
    timeout = mcp_server.get_mcp_api_timeout()

    assert timeout.read >= 300
    assert timeout.write >= 300
    assert timeout.pool >= 300
    assert timeout.connect == mcp_server.MCP_API_CONNECT_TIMEOUT_SECONDS


@pytest.mark.parametrize(
    ("generation_mode", "expected_tools"),
    [
        (
            "both",
            {
                "start_standard_presentation",
                "start_smart_presentation",
                "generate_smart_presentation",
                "list_templates",
                "upload_template_assets",
                "initialize_template",
                "start_template_generation",
                "get_job_status",
            },
        ),
        (
            "standard",
            {
                "start_standard_presentation",
                "list_templates",
                "upload_template_assets",
                "initialize_template",
                "start_template_generation",
                "get_job_status",
            },
        ),
        (
            "smart",
            {
                "start_smart_presentation",
                "generate_smart_presentation",
                "get_job_status",
            },
        ),
        (
            "invalid",
            {
                "start_standard_presentation",
                "start_smart_presentation",
                "generate_smart_presentation",
                "list_templates",
                "upload_template_assets",
                "initialize_template",
                "start_template_generation",
                "get_job_status",
            },
        ),
    ],
)
def test_mcp_tools_follow_presentation_generation_mode(
    monkeypatch, generation_mode, expected_tools
):
    monkeypatch.setenv("PRESENTATION_GENERATION_MODE", generation_mode)

    async def list_tool_names():
        async with httpx.AsyncClient(base_url="http://127.0.0.1:8000") as client:
            server = mcp_server.create_mcp_server(client)
            return {tool.name for tool in await server.list_tools()}

    assert asyncio.run(list_tool_names()) == expected_tools
