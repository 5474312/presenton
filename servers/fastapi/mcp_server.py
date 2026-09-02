import sys
import argparse
import asyncio
import json
import logging
import traceback
from pathlib import Path

import httpx
import httpx2
from fastmcp import FastMCP
from fastmcp.server.auth import AccessToken, TokenVerifier
from fastmcp.server.dependencies import get_access_token, get_http_headers
from fastmcp.server.providers.openapi import MCPType, RouteMap

from utils.get_env import (
    PresentationGenerationMode,
    get_presentation_generation_mode,
    is_disable_auth_enabled,
    is_presenton_electron_desktop,
)
from models.sql.access_token import AccessToken as DatabaseAccessToken
from models.sql.user import User
from services.database import async_session_maker
from services.mcp_credentials import MCP_KEY_PREFIX, verify_mcp_credential
from api.v1.auth.config import SESSION_COOKIE_NAME
from api.v1.auth.users import get_jwt_strategy
from utils.mcp_public_urls import MCP_REQUEST_HEADER

OPENAPI_SPEC_PATH = Path(__file__).with_name("openai_spec.json")
MCP_API_BASE_URL = "http://127.0.0.1:8000"
# Presentation generation can take several minutes; keep MCP upstream reads open.
MCP_API_TIMEOUT_SECONDS = 600.0
MCP_API_CONNECT_TIMEOUT_SECONDS = 15.0
# The session is copied into an in-process background generation job and used
# again by the exporter after all slides are ready. A five-minute token could
# expire during a perfectly healthy 10-20 minute deck generation, especially
# on first boot while models are being downloaded.
MCP_INTERNAL_SESSION_TTL_SECONDS = 60 * 60
LOGGER = logging.getLogger(__name__)

# The HTTP API contains many internal and administrative routes that are useful to
# the web app but should not be advertised to an MCP client. Keep this allowlist
# intentionally small so an LLM can reliably select the presentation workflow.
MCP_STANDARD_ROUTE_MAPS = [
    RouteMap(
        methods=["POST"],
        pattern=r"^/api/v1/ppt/presentation/generate/async$",
        mcp_type=MCPType.TOOL,
    ),
]

MCP_SMART_ROUTE_MAPS = [
    RouteMap(
        methods=["POST"],
        pattern=r"^/api/v2/ppt/presentation/generate/smart$",
        mcp_type=MCPType.TOOL,
    ),
    RouteMap(
        methods=["POST"],
        pattern=r"^/api/v2/ppt/presentation/generate/smart/async$",
        mcp_type=MCPType.TOOL,
    ),
]

MCP_TEMPLATE_ROUTE_MAPS = [
    RouteMap(
        methods=["GET"],
        pattern=r"^/api/v1/ppt/template/all$",
        mcp_type=MCPType.TOOL,
    ),
    RouteMap(
        methods=["POST"],
        pattern=r"^/api/v1/ppt/template/mcp-upload$",
        mcp_type=MCPType.TOOL,
    ),
    RouteMap(
        methods=["POST"],
        pattern=r"^/api/v1/ppt/template/init$",
        mcp_type=MCPType.TOOL,
    ),
    RouteMap(
        methods=["POST"],
        pattern=r"^/api/v1/ppt/template/async$",
        mcp_type=MCPType.TOOL,
    ),
]

MCP_SHARED_ROUTE_MAPS = [
    RouteMap(
        methods=["GET"],
        pattern=r"^/api/v1/async-tasks/status/\{id\}$",
        mcp_type=MCPType.TOOL,
    ),
]

MCP_TOOL_NAMES = {
    "generate_presentation_async_api_v1_ppt_presentation_generate_async_post": (
        "start_standard_presentation"
    ),
    "generate_smart_presentation_async": "start_smart_presentation",
    "generate_smart_presentation": "generate_smart_presentation",
    "template_list": "list_templates",
    "mcp_template_upload": "upload_template_assets",
    "init_template_api_v1_ppt_template_init_post": "initialize_template",
    "create_template_api_v1_ppt_template_async_post": "start_template_generation",
    "check_async_task_status_api_v1_async_tasks_status__id__get": "get_job_status",
}

def get_mcp_route_maps(
    generation_mode: PresentationGenerationMode,
) -> list[RouteMap]:
    """Expose only workflows enabled by PRESENTATION_GENERATION_MODE."""
    route_maps: list[RouteMap] = []
    if generation_mode in {"both", "standard"}:
        route_maps.extend(MCP_STANDARD_ROUTE_MAPS)
        route_maps.extend(MCP_TEMPLATE_ROUTE_MAPS)
    if generation_mode in {"both", "smart"}:
        route_maps.extend(MCP_SMART_ROUTE_MAPS)
    route_maps.extend(MCP_SHARED_ROUTE_MAPS)
    route_maps.append(RouteMap(mcp_type=MCPType.EXCLUDE))
    return route_maps


def get_mcp_instructions(generation_mode: PresentationGenerationMode) -> str:
    enabled_workflows = {
        "both": "Standard, Smart, and template generation",
        "standard": "Standard and template generation",
        "smart": "Smart generation",
    }[generation_mode]
    instructions = f"""Create presentations with Presenton.

{enabled_workflows} support asynchronous jobs. Start a generation, then poll
get_job_status with the returned task ID until its status is completed or error.
A pending status with a generation progress message means the job is actively
processing, not that it failed to start. Continue polling every 10-15 seconds;
first-run model downloads and larger decks can take several minutes.
"""
    if generation_mode in {"both", "smart"}:
        instructions += """For Smart generation, generate_smart_presentation is the
blocking alternative and returns the exported presentation without polling.
"""
    if generation_mode in {"both", "standard"}:
        instructions += """Template listing is immediate. Custom-template upload,
initialization, and generation create templates scoped to the authenticated user.
For a custom template, call upload_template_assets once, then pass its response
to initialize_template or start_template_generation. When a user wants to inspect
a template visually, share the preview_url returned by list_templates.
"""
    return instructions + "Never ask a user to paste their Presenton key into chat.\n"

with OPENAPI_SPEC_PATH.open("r", encoding="utf-8") as f:
    openapi_spec = json.load(f)


class PresentonTokenVerifier(TokenVerifier):
    """Validate user-scoped MCP keys, with one-release legacy-key support."""

    async def verify_token(self, token: str) -> AccessToken | None:
        if not token.startswith("sk-presenton-"):
            return None
        async with async_session_maker() as session:
            if token.startswith(MCP_KEY_PREFIX):
                verified = await verify_mcp_credential(session, token)
                if verified is None:
                    return None
                user = verified.user
                credential_id = verified.credential_id
                legacy = False
            else:
                access_key = await session.get(DatabaseAccessToken, token)
                if access_key is None:
                    return None
                user = await session.get(User, access_key.user_id)
                if user is None or not user.is_active or not user.is_superuser:
                    return None
                credential_id = None
                legacy = True
                LOGGER.warning(
                    "A legacy administrator API key authenticated to MCP; "
                    "replace it with a user-scoped MCP credential"
                )
            try:
                internal_session_token = await get_jwt_strategy(
                    lifetime_seconds=MCP_INTERNAL_SESSION_TTL_SECONDS
                ).write_token(user)
            except ValueError:
                # Unit tests and incomplete development shells may not have a
                # USER_CONFIG_PATH. Production startup always creates it.
                internal_session_token = None

        return AccessToken(
            token=token,
            client_id=str(user.id),
            scopes=[],
            claims={
                "u": user.username,
                "role": "admin" if user.is_superuser else "user",
                "user_id": str(user.id),
                "credential_id": credential_id,
                "legacy": legacy,
                "internal_session_token": internal_session_token,
            },
        )


def is_mcp_server_enabled() -> bool:
    """MCP is only supported in server/Docker deployments, not the Electron app."""
    return not is_presenton_electron_desktop()


def create_mcp_auth_provider() -> TokenVerifier | None:
    """Require user-scoped bearer auth whenever server auth is enabled."""
    if is_disable_auth_enabled():
        return None
    return PresentonTokenVerifier()


def get_mcp_api_timeout() -> httpx2.Timeout:
    return httpx2.Timeout(
        timeout=MCP_API_TIMEOUT_SECONDS,
        connect=MCP_API_CONNECT_TIMEOUT_SECONDS,
    )


def create_openapi_api_client() -> httpx2.AsyncClient:
    return httpx2.AsyncClient(
        base_url=MCP_API_BASE_URL,
        timeout=get_mcp_api_timeout(),
        event_hooks={"request": [attach_request_auth_header]},
    )


def create_mcp_server(
    api_client: httpx.AsyncClient | httpx2.AsyncClient,
    *,
    name: str = "Presenton",
    auth: TokenVerifier | None = None,
) -> FastMCP:
    """Create the MCP server with only the public presentation workflow exposed."""
    generation_mode = get_presentation_generation_mode()
    return FastMCP.from_openapi(
        openapi_spec=openapi_spec,
        client=api_client,
        name=name,
        auth=auth,
        route_maps=get_mcp_route_maps(generation_mode),
        mcp_names=MCP_TOOL_NAMES,
        instructions=get_mcp_instructions(generation_mode),
    )


async def attach_request_auth_header(request: httpx.Request | httpx2.Request) -> None:
    """Exchange the MCP key for an internal session when calling FastAPI.

    The long-lived MCP credential is deliberately never forwarded to an API
    endpoint. The fallback paths exist for auth-disabled development and for
    older tests which provide a token object without verified claims.
    """
    incoming_headers = get_http_headers(
        include={
            "authorization",
            "host",
            "x-forwarded-host",
            "x-forwarded-proto",
        }
    )
    request.headers[MCP_REQUEST_HEADER] = "1"

    # Preserve the public origin across the MCP -> internal FastAPI request so
    # API responses can expose browser links for the host the client connected to.
    forwarded_host = incoming_headers.get("x-forwarded-host") or incoming_headers.get(
        "host"
    )
    if forwarded_host:
        request.headers["X-Forwarded-Host"] = forwarded_host
    forwarded_proto = incoming_headers.get("x-forwarded-proto")
    if forwarded_proto:
        request.headers["X-Forwarded-Proto"] = forwarded_proto

    if "authorization" in request.headers or "cookie" in request.headers:
        return

    access_token = get_access_token()
    if access_token:
        claims = getattr(access_token, "claims", None) or {}
        internal_session_token = claims.get("internal_session_token")
        if internal_session_token:
            request.headers["Cookie"] = (
                f"{SESSION_COOKIE_NAME}={internal_session_token}"
            )
            return
        if claims.get("user_id"):
            raise RuntimeError(
                "Unable to create an internal Presenton session for the MCP request"
            )
        request.headers["Authorization"] = f"Bearer {access_token.token}"
        return

    incoming_auth_header = incoming_headers.get("authorization")
    if incoming_auth_header:
        request.headers["Authorization"] = incoming_auth_header


async def main():
    try:
        if not is_mcp_server_enabled():
            print(
                "INFO: MCP server is disabled in the Presenton Electron desktop app "
                "(PRESENTON_ELECTRON=true)."
            )
            return

        print("DEBUG: MCP (OpenAPI) Server startup initiated")
        parser = argparse.ArgumentParser(
            description="Run the MCP server (from OpenAPI)"
        )
        parser.add_argument(
            "--port", type=int, default=8001, help="Port for the MCP HTTP server"
        )

        parser.add_argument(
            "--name",
            type=str,
            default="Presenton API (OpenAPI)",
            help="Display name for the generated MCP server",
        )
        args = parser.parse_args()
        print(f"DEBUG: Parsed args - port={args.port}")

        async with create_openapi_api_client() as api_client:
            # Build MCP server from OpenAPI
            print("DEBUG: Creating FastMCP server from OpenAPI spec...")
            mcp_auth_provider = create_mcp_auth_provider()
            mcp = create_mcp_server(
                api_client,
                name=args.name,
                auth=mcp_auth_provider,
            )
            print("DEBUG: MCP server created from OpenAPI successfully")

            # Start the MCP server
            uvicorn_config = {"reload": False}
            print(f"DEBUG: Starting MCP server on host=127.0.0.1, port={args.port}")
            await mcp.run_async(
                transport="http",
                host="127.0.0.1",
                port=args.port,
                uvicorn_config=uvicorn_config,
            )
            print("DEBUG: MCP server run_async completed")
    except Exception as e:
        print(f"ERROR: MCP server startup failed: {e}")
        print(f"ERROR: Traceback: {traceback.format_exc()}")
        raise


if __name__ == "__main__":
    print("DEBUG: Starting MCP (OpenAPI) main function")
    try:
        asyncio.run(main())
    except Exception as e:
        print(f"FATAL ERROR: {e}")
        print(f"FATAL TRACEBACK: {traceback.format_exc()}")
        sys.exit(1)
