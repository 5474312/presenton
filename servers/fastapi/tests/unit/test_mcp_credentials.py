import asyncio
from datetime import timedelta
from types import SimpleNamespace
import uuid

from models.sql.mcp_credential import McpCredential
from models.sql.user import User
from services import mcp_credentials
from utils.datetime_utils import get_current_utc_datetime


def test_mcp_key_format_and_parser():
    token = mcp_credentials.build_mcp_key("0123456789abcdef", "s" * 40)

    assert token.startswith("sk-presenton-mcp-")
    assert mcp_credentials.parse_mcp_key(token) == (
        "0123456789abcdef",
        "s" * 40,
    )
    assert mcp_credentials.parse_mcp_key("sk-presenton-old") is None


def test_mcp_key_can_be_securely_revealed_by_admin(monkeypatch):
    monkeypatch.setattr(
        mcp_credentials,
        "get_or_create_auth_secret",
        lambda: "deployment-auth-secret",
    )
    token = mcp_credentials.build_mcp_key("0123456789abcdef", "s" * 40)
    credential = McpCredential(
        id="0123456789abcdef",
        secret_hash="hashed",
        token_encrypted=mcp_credentials.encrypt_mcp_key(token),
        user_id=uuid.uuid4(),
        created_by_id=uuid.uuid4(),
        expires_at=get_current_utc_datetime() + timedelta(days=1),
    )

    assert token not in credential.token_encrypted
    assert mcp_credentials.reveal_mcp_key(credential) == token


def test_verify_mcp_credential_accepts_active_normal_user(monkeypatch):
    user = User(
        id=uuid.uuid4(),
        username="normal-user",
        hashed_password="unused",
        is_active=True,
        is_superuser=False,
        is_verified=True,
    )
    credential = McpCredential(
        id="0123456789abcdef",
        secret_hash="hashed",
        user_id=user.id,
        created_by_id=uuid.uuid4(),
        expires_at=get_current_utc_datetime() + timedelta(days=1),
    )

    class Session:
        committed = False

        async def get(self, model, key):
            if model is McpCredential and key == credential.id:
                return credential
            if model is User and key == user.id:
                return user
            return None

        def add(self, _value):
            return None

        async def commit(self):
            self.committed = True

    monkeypatch.setattr(
        mcp_credentials,
        "PASSWORD_HELPER",
        SimpleNamespace(verify_and_update=lambda plain, hashed: (plain == "s" * 40, None)),
    )
    session = Session()

    verified = asyncio.run(
        mcp_credentials.verify_mcp_credential(
            session,
            mcp_credentials.build_mcp_key(credential.id, "s" * 40),
        )
    )

    assert verified is not None
    assert verified.user is user
    assert session.committed is True
