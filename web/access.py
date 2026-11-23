"""Private access: with ACCESS_MODE=link, only these visitors get past the gate:
- someone signed in (Google),
- someone who opened a shared link (/s/<token>) that has not been revoked (checked on every request),
- the start, sign-in and static paths needed to get there.
Everyone else sees the "This site is private" page. Search engines are told not to index anything.
"""

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, PlainTextResponse, RedirectResponse

from tracker import config, services

OPEN_PATHS = ("/static/", "/login", "/auth/callback", "/dev-login", "/logout", "/robots.txt")  # sign-in checks may_sign_in


def has_access(request: Request) -> bool:
    if config.ACCESS_MODE != "link":
        return True
    s = request.session
    return bool(s.get("email")) or services.share_link_valid(s.get("access"))


def install(app: FastAPI, closed_page) -> None:
    """Add the gate. Call before SessionMiddleware is added so the session is available here."""

    @app.middleware("http")
    async def gate(request: Request, call_next):
        path = request.url.path
        if path.startswith("/s/") or path.startswith(OPEN_PATHS) or has_access(request):
            resp = await call_next(request)
        else:
            resp = closed_page(request)
        resp.headers["X-Robots-Tag"] = "noindex, nofollow"
        return resp

    @app.get("/s/{token}")
    def shared(request: Request, token: str):
        if not services.use_share_link(token):
            request.session.pop("access", None)
            return closed_page(request)
        request.session["access"] = token
        return RedirectResponse("/", status_code=303)

    @app.get("/robots.txt", response_class=PlainTextResponse)
    def robots():
        return "User-agent: *\nDisallow: /\n"


def may_sign_in(request: Request, email: str) -> bool:
    """In link mode, Google sign-in is for people who came through a link or have signed in before."""
    if config.ACCESS_MODE != "link":
        return True
    return services.share_link_valid(request.session.get("access")) or services.known_user(email) or email == config.OWNER_EMAIL


_ = HTMLResponse  # re-exported type for closed_page implementations
