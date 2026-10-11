
import asyncio
import hmac
import logging
import os
import secrets
import time
from datetime import datetime, timezone
from urllib.parse import urlencode

from aiohttp import ClientSession, ClientTimeout, web

from ai.health import get_status
from analytics.database import (
    get_daily_activity,
    get_message_count,
    get_objectives,
    get_unique_member_count,
)

logger = logging.getLogger("quasar.dashboard")

DISCORD_AUTHORIZE_URL = "https://discord.com/oauth2/authorize"
DISCORD_TOKEN_URL = "https://discord.com/api/oauth2/token"
DISCORD_USER_URL = "https://discord.com/api/users/@me"

SESSION_TTL_SECONDS = 3600
OAUTH_TICKET_TTL_SECONDS = 300
OAUTH_STATE_TTL_SECONDS = 600

OAUTH_STATE_COOKIE = "quasar_oauth_state"


def _env(name, default=""):
    return os.getenv(name, default).strip()


def _frontend_origin(request):
    return request.app["frontend_origin"]


def _api_url(request):
    return request.app["public_api_url"]


def _oauth_enabled():
    required = (
        "QUASAR_DISCORD_CLIENT_ID",
        "QUASAR_DISCORD_CLIENT_SECRET",
        "QUASAR_OWNER_DISCORD_ID",
        "QUASAR_SESSION_SECRET",
        "QUASAR_FRONTEND_ORIGIN",
        "QUASAR_PUBLIC_API_URL",
    )
    return all(_env(name) for name in required)


def _oauth_redirect_uri(request):
    return f"{_api_url(request)}/api/auth/callback"


def _local_token_authorized(request):
    expected = _env("QUASAR_DASHBOARD_TOKEN")
    authorization = request.headers.get("Authorization", "")
    supplied = authorization.removeprefix("Bearer ").strip()

    return bool(expected) and hmac.compare_digest(
        supplied,
        expected,
    )


def _valid_session(request):
    authorization = request.headers.get("Authorization", "")
    token = authorization.removeprefix("Bearer ").strip()

    if not token:
        return None

    session = request.app["sessions"].get(token)

    if not session:
        return None

    if session["expires_at"] <= time.time():
        request.app["sessions"].pop(token, None)
        return None

    if session["user_id"] != request.app["owner_id"]:
        return None

    return token


@web.middleware
async def cors_middleware(request, handler):
    origin = request.headers.get("Origin")
    allowed_origin = request.app["frontend_origin"]

    if request.method == "OPTIONS":
        response = web.Response(status=204)
    else:
        try:
            response = await handler(request)
        except web.HTTPException as error:
            response = error

    if origin and origin == allowed_origin:
        response.headers["Access-Control-Allow-Origin"] = allowed_origin
        response.headers["Access-Control-Allow-Methods"] = (
            "GET, POST, OPTIONS"
        )
        response.headers["Access-Control-Allow-Headers"] = (
            "Authorization, Content-Type, Accept"
        )
        response.headers["Access-Control-Max-Age"] = "600"
        response.headers["Vary"] = "Origin"
        response.headers["Cache-Control"] = "no-store"

    return response


@web.middleware
async def authentication_middleware(request, handler):
    protected_paths = {
        "/api/dashboard",
        "/api/auth/logout",
    }

    if request.path not in protected_paths:
        return await handler(request)

    if request.app["auth_mode"] == "local_token":
        if not _local_token_authorized(request):
            return web.json_response(
                {"error": "Unauthorized"},
                status=401,
            )
        return await handler(request)

    session_token = _valid_session(request)

    if not session_token:
        return web.json_response(
            {"error": "Please sign in with your authorized Discord account."},
            status=401,
        )

    request["quasar_session_token"] = session_token

    return await handler(request)


def _configured_guild_id():
    value = _env("QUASAR_DASHBOARD_GUILD_ID")

    if not value:
        raise ValueError("QUASAR_DASHBOARD_GUILD_ID is missing")

    return int(value)


def _oauth_configuration_error():
    required = (
        "QUASAR_DISCORD_CLIENT_ID",
        "QUASAR_DISCORD_CLIENT_SECRET",
        "QUASAR_OWNER_DISCORD_ID",
        "QUASAR_SESSION_SECRET",
        "QUASAR_FRONTEND_ORIGIN",
        "QUASAR_PUBLIC_API_URL",
    )

    missing = [name for name in required if not _env(name)]

    if missing:
        return "Missing required OAuth configuration: " + ", ".join(missing)

    if len(_env("QUASAR_SESSION_SECRET")) < 32:
        return "QUASAR_SESSION_SECRET must contain at least 32 characters."

    try:
        int(_env("QUASAR_OWNER_DISCORD_ID"))
    except ValueError:
        return "QUASAR_OWNER_DISCORD_ID must be a numeric Discord user ID."

    frontend_origin = _env("QUASAR_FRONTEND_ORIGIN").rstrip("/")
    public_api_url = _env("QUASAR_PUBLIC_API_URL").rstrip("/")

    if not frontend_origin.startswith(("http://", "https://")):
        return "QUASAR_FRONTEND_ORIGIN must be an HTTP or HTTPS origin."

    if not public_api_url.startswith(("http://", "https://")):
        return "QUASAR_PUBLIC_API_URL must be an HTTP or HTTPS URL."

    if os.getenv("RENDER") and (
        not frontend_origin.startswith("https://")
        or not public_api_url.startswith("https://")
    ):
        return "Render OAuth URLs must use HTTPS."

    return None


async def health_handler(request):
    bot = request.app["bot"]

    return web.json_response(
        {
            "status": "ok",
            "botReady": bot.is_ready(),
        }
    )


async def dashboard_handler(request):
    bot = request.app["bot"]

    if not bot.is_ready():
        return web.json_response(
            {"error": "Quasar is not ready yet"},
            status=503,
        )

    try:
        guild_id = _configured_guild_id()
    except (ValueError, TypeError):
        return web.json_response(
            {"error": "Dashboard guild ID is not configured correctly"},
            status=503,
        )

    guild = bot.get_guild(guild_id)

    if guild is None:
        return web.json_response(
            {"error": "Configured Discord server is not available to Quasar"},
            status=503,
        )

    try:
        objectives = get_objectives(guild_id, limit=50)
        daily_activity = get_daily_activity(guild_id, days=7)
        provider_status = get_status()

        return web.json_response(
            {
                "updatedAt": datetime.now(timezone.utc).isoformat(),
                "server": {
                    "name": guild.name,
                    "memberCount": guild.member_count,
                    "connected": True,
                },
                "overview": {
                    "totalMessages": get_message_count(guild_id),
                    "messagesLast7Days": get_message_count(
                        guild_id,
                        days=7,
                    ),
                    "activeMembersLast7Days": get_unique_member_count(
                        guild_id,
                        days=7,
                    ),
                    "activeObjectives": sum(
                        1
                        for objective in objectives
                        if objective["status"] == "active"
                    ),
                },
                "dailyActivity": daily_activity,
                "objectives": [
                    {
                        "id": objective["id"],
                        "objective": objective["objective"],
                        "description": objective["description"] or "",
                        "priority": objective["priority"],
                        "status": objective["status"],
                        "createdAt": objective["created_at"],
                        "updatedAt": objective["updated_at"],
                    }
                    for objective in objectives
                ],
                "aiProviders": provider_status,
            }
        )

    except Exception:
        request.app.logger.exception("Dashboard data request failed")

        return web.json_response(
            {"error": "Unable to read dashboard data"},
            status=500,
        )


async def oauth_login_handler(request):
    if request.app["auth_mode"] != "oauth":
        return web.json_response(
            {"error": "Discord OAuth is not configured."},
            status=503,
        )

    state = secrets.token_urlsafe(32)
    request.app["oauth_states"][state] = time.time() + OAUTH_STATE_TTL_SECONDS

    params = {
        "client_id": _env("QUASAR_DISCORD_CLIENT_ID"),
        "redirect_uri": _oauth_redirect_uri(request),
        "response_type": "code",
        "scope": "identify",
        "state": state,
    }

    response = web.HTTPFound(
        f"{DISCORD_AUTHORIZE_URL}?{urlencode(params)}"
    )

    response.set_cookie(
        OAUTH_STATE_COOKIE,
        state,
        max_age=OAUTH_STATE_TTL_SECONDS,
        httponly=True,
        secure=_api_url(request).startswith("https://"),
        samesite="Lax",
        path="/api/auth/callback",
    )

    return response


async def oauth_callback_handler(request):
    if request.app["auth_mode"] != "oauth":
        return web.json_response(
            {"error": "Discord OAuth is not configured."},
            status=503,
        )

    frontend = _frontend_origin(request)
    query = request.query

    if query.get("error"):
        return web.HTTPFound(
            f"{frontend}/?quasar_auth_error=cancelled"
        )

    state = query.get("state", "")
    cookie_state = request.cookies.get(OAUTH_STATE_COOKIE, "")
    expires_at = request.app["oauth_states"].pop(state, 0)

    if (
        not state
        or not cookie_state
        or not hmac.compare_digest(state, cookie_state)
        or expires_at <= time.time()
    ):
        return web.HTTPFound(
            f"{frontend}/?quasar_auth_error=invalid_state"
        )

    code = query.get("code", "")

    if not code:
        return web.HTTPFound(
            f"{frontend}/?quasar_auth_error=missing_code"
        )

    token_payload = {
        "client_id": _env("QUASAR_DISCORD_CLIENT_ID"),
        "client_secret": _env("QUASAR_DISCORD_CLIENT_SECRET"),
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": _oauth_redirect_uri(request),
    }

    timeout = ClientTimeout(total=15)

    try:
        async with ClientSession(timeout=timeout) as session:
            async with session.post(
                DISCORD_TOKEN_URL,
                data=token_payload,
                headers={"Accept": "application/json"},
            ) as response:
                if response.status != 200:
                    logger.warning(
                        "Discord OAuth token exchange returned HTTP %s",
                        response.status,
                    )
                    return web.HTTPFound(
                        f"{frontend}/?quasar_auth_error=oauth_failed"
                    )

                token_data = await response.json()

            access_token = token_data.get("access_token")

            if not access_token:
                return web.HTTPFound(
                    f"{frontend}/?quasar_auth_error=oauth_failed"
                )

            async with session.get(
                DISCORD_USER_URL,
                headers={"Authorization": f"Bearer {access_token}"},
            ) as response:
                if response.status != 200:
                    return web.HTTPFound(
                        f"{frontend}/?quasar_auth_error=identity_failed"
                    )

                discord_user = await response.json()

    except asyncio.TimeoutError:
        logger.warning("Discord OAuth request timed out")
        return web.HTTPFound(
            f"{frontend}/?quasar_auth_error=oauth_unavailable"
        )
    except Exception:
        logger.exception("Discord OAuth callback failed")
        return web.HTTPFound(
            f"{frontend}/?quasar_auth_error=oauth_unavailable"
        )

    if discord_user.get("id") != request.app["owner_id"]:
        return web.HTTPFound(
            f"{frontend}/?quasar_auth_error=not_authorized"
        )

    ticket = secrets.token_urlsafe(32)

    request.app["oauth_tickets"][ticket] = {
        "user_id": discord_user["id"],
        "expires_at": time.time() + OAUTH_TICKET_TTL_SECONDS,
    }

    return web.HTTPFound(
        f"{frontend}/?{urlencode({'quasar_ticket': ticket})}"
    )


async def oauth_exchange_handler(request):
    if request.app["auth_mode"] != "oauth":
        return web.json_response(
            {"error": "Discord OAuth is not configured."},
            status=503,
        )

    try:
        body = await request.json()
    except Exception:
        return web.json_response(
            {"error": "Invalid request body."},
            status=400,
        )

    ticket = body.get("ticket", "")

    if not isinstance(ticket, str) or not ticket:
        return web.json_response(
            {"error": "Missing sign-in ticket."},
            status=400,
        )

    ticket_data = request.app["oauth_tickets"].pop(ticket, None)

    if (
        not ticket_data
        or ticket_data["expires_at"] <= time.time()
        or ticket_data["user_id"] != request.app["owner_id"]
    ):
        return web.json_response(
            {"error": "This sign-in link has expired. Please sign in again."},
            status=401,
        )

    session_token = secrets.token_urlsafe(32)

    request.app["sessions"][session_token] = {
        "user_id": ticket_data["user_id"],
        "expires_at": time.time() + SESSION_TTL_SECONDS,
    }

    return web.json_response(
        {
            "accessToken": session_token,
            "expiresIn": SESSION_TTL_SECONDS,
            "user": {
                "id": ticket_data["user_id"],
            },
        }
    )


async def logout_handler(request):
    session_token = request.get("quasar_session_token")

    if session_token:
        request.app["sessions"].pop(session_token, None)

    return web.json_response({"status": "ok"})


async def start_dashboard_api(bot):
    host = _env(
        "QUASAR_DASHBOARD_HOST",
        "0.0.0.0" if os.getenv("RENDER") else "127.0.0.1",
    )

    port = int(
        _env("PORT")
        or _env("QUASAR_DASHBOARD_PORT", "8765")
    )

    oauth_error = _oauth_configuration_error()
    oauth_enabled = _oauth_enabled()

    if os.getenv("RENDER") and (not oauth_enabled or oauth_error):
        raise RuntimeError(
            "Dashboard startup refused: secure Discord OAuth is not "
            f"configured correctly. {oauth_error or ''}"
        )

    if oauth_enabled and oauth_error:
        raise RuntimeError(oauth_error)

    if oauth_enabled:
        auth_mode = "oauth"
    elif _env("QUASAR_DASHBOARD_TOKEN"):
        if host not in {"127.0.0.1", "localhost", "::1"}:
            raise RuntimeError(
                "Shared-token authentication is only allowed on localhost. "
                "Configure Discord OAuth before exposing the API."
            )
        auth_mode = "local_token"
    else:
        print(
            "DASHBOARD API: Disabled. Configure local dashboard token "
            "or complete Discord OAuth setup."
        )
        return None

    frontend_origin = _env(
        "QUASAR_FRONTEND_ORIGIN",
        "http://127.0.0.1:5173",
    ).rstrip("/")

    public_api_url = _env(
        "QUASAR_PUBLIC_API_URL",
        f"http://127.0.0.1:{port}",
    ).rstrip("/")

    try:
        owner_id = str(int(_env("QUASAR_OWNER_DISCORD_ID")))
    except ValueError:
        owner_id = ""

    app = web.Application(
        middlewares=[
            cors_middleware,
            authentication_middleware,
        ]
    )

    app["bot"] = bot
    app["auth_mode"] = auth_mode
    app["frontend_origin"] = frontend_origin
    app["public_api_url"] = public_api_url
    app["owner_id"] = owner_id
    app["sessions"] = {}
    app["oauth_tickets"] = {}
    app["oauth_states"] = {}

    app.router.add_get("/api/health", health_handler)
    app.router.add_get("/api/dashboard", dashboard_handler)
    app.router.add_get("/api/auth/login", oauth_login_handler)
    app.router.add_get("/api/auth/callback", oauth_callback_handler)
    app.router.add_post("/api/auth/exchange", oauth_exchange_handler)
    app.router.add_post("/api/auth/logout", logout_handler)

    runner = web.AppRunner(app)
    await runner.setup()

    site = web.TCPSite(runner, host, port)

    try:
        await site.start()
    except Exception:
        await runner.cleanup()
        raise

    print(
        f"DASHBOARD API: Listening on http://{host}:{port} "
        f"(authentication mode: {auth_mode})"
    )

    return runner


async def stop_dashboard_api(runner):
    if runner is not None:
        await runner.cleanup()
        print("DASHBOARD API: Stopped.")
