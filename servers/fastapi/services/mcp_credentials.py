from dataclasses import dataclass
import base64
from datetime import datetime, timedelta, timezone
import hashlib
import secrets
import uuid
import re

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy.ext.asyncio import AsyncSession

from api.v1.auth.config import get_or_create_auth_secret
from api.v1.auth.users import PASSWORD_HELPER
from models.sql.mcp_credential import McpCredential
from models.sql.user import User
from utils.datetime_utils import get_current_utc_datetime


MCP_KEY_PREFIX = "sk-presenton-mcp-"
DEFAULT_EXPIRY_DAYS = 90
MAX_EXPIRY_DAYS = 365
MCP_CREDENTIAL_ID_PATTERN = re.compile(r"^[0-9a-f]{16}$")


@dataclass(frozen=True)
class VerifiedMcpCredential:
    credential_id: str
    user: User


def _utc_aware(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def build_mcp_key(credential_id: str, secret: str) -> str:
    return f"{MCP_KEY_PREFIX}{credential_id}.{secret}"


def _credential_cipher() -> Fernet:
    encryption_key = hashlib.sha256(
        get_or_create_auth_secret().encode("utf-8")
    ).digest()
    return Fernet(base64.urlsafe_b64encode(encryption_key))


def encrypt_mcp_key(token: str) -> str:
    return _credential_cipher().encrypt(token.encode("utf-8")).decode("ascii")


def reveal_mcp_key(credential: McpCredential) -> str | None:
    if not credential.token_encrypted:
        return None
    try:
        token = _credential_cipher().decrypt(
            credential.token_encrypted.encode("ascii")
        ).decode("utf-8")
    except (InvalidToken, UnicodeError, ValueError):
        return None
    parsed = parse_mcp_key(token)
    if parsed is None or parsed[0] != credential.id:
        return None
    return token


def parse_mcp_key(token: str) -> tuple[str, str] | None:
    if not token.startswith(MCP_KEY_PREFIX):
        return None
    body = token[len(MCP_KEY_PREFIX) :]
    credential_id, separator, secret = body.partition(".")
    if (
        not separator
        or not MCP_CREDENTIAL_ID_PATTERN.fullmatch(credential_id)
        or len(secret) < 32
    ):
        return None
    return credential_id, secret


async def issue_mcp_credential(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    created_by_id: uuid.UUID,
    label: str,
    expiry_days: int = DEFAULT_EXPIRY_DAYS,
) -> tuple[McpCredential, str]:
    if expiry_days < 1 or expiry_days > MAX_EXPIRY_DAYS:
        raise ValueError(f"expiry_days must be between 1 and {MAX_EXPIRY_DAYS}")
    secret = secrets.token_urlsafe(40)
    credential_id = secrets.token_hex(8)
    token = build_mcp_key(credential_id, secret)
    credential = McpCredential(
        id=credential_id,
        user_id=user_id,
        created_by_id=created_by_id,
        label=label.strip() or "MCP client",
        secret_hash=PASSWORD_HELPER.hash(secret),
        token_encrypted=encrypt_mcp_key(token),
        expires_at=get_current_utc_datetime() + timedelta(days=expiry_days),
    )
    session.add(credential)
    await session.commit()
    await session.refresh(credential)
    return credential, token


async def verify_mcp_credential(
    session: AsyncSession, token: str
) -> VerifiedMcpCredential | None:
    parsed = parse_mcp_key(token)
    if parsed is None:
        return None
    credential_id, secret = parsed
    credential = await session.get(McpCredential, credential_id)
    if credential is None or credential.revoked_at is not None:
        return None
    now = get_current_utc_datetime()
    if _utc_aware(credential.expires_at) <= _utc_aware(now):
        return None
    verified, replacement_hash = PASSWORD_HELPER.verify_and_update(
        secret, credential.secret_hash
    )
    if not verified:
        return None
    user = await session.get(User, credential.user_id)
    if user is None or not user.is_active:
        return None
    credential.last_used_at = now
    if replacement_hash:
        credential.secret_hash = replacement_hash
    session.add(credential)
    await session.commit()
    return VerifiedMcpCredential(credential_id=credential.id, user=user)
