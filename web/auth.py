"""Google sign-in (OpenID Connect via Authlib). Only the email and display name are kept, in the signed session cookie."""

from authlib.integrations.starlette_client import OAuth, OAuthError
from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse

from tracker import config, services

GOOGLE_METADATA = "https://accounts.google.com/.well-known/openid-configuration"
oauth = OAuth()


def configured() -> bool:
    return bool(config.GOOGLE_CLIENT_ID and config.GOOGLE_CLIENT_SECRET)


def dev_login_allowed() -> bool:
    """An email box instead of Google, only when running locally without Google keys. Never in prod."""
    return config.APP_ENV == "local" and not configured()


def _signed_in(request: Request, email: str, name: str | None):
    request.session.clear()
    request.session["email"] = email.strip().lower()
    request.session["name"] = name or email.split("@")[0]
    services.sign_in(request.session["email"])
    return RedirectResponse("/portfolio", status_code=303)


def register(app: FastAPI) -> None:
    if configured():
        oauth.register("google", client_id=config.GOOGLE_CLIENT_ID, client_secret=config.GOOGLE_CLIENT_SECRET,
                       server_metadata_url=GOOGLE_METADATA, client_kwargs={"scope": "openid email profile"})

    @app.get("/login")
    async def login(request: Request):
        if not configured():
            return RedirectResponse("/", status_code=303)
        return await oauth.google.authorize_redirect(request, f"{config.BASE_URL}/auth/callback")

    @app.get("/auth/callback")
    async def callback(request: Request):
        try:
            token = await oauth.google.authorize_access_token(request)
        except OAuthError:
            request.session["flash"] = "Google sign-in did not complete. Please try again."
            return RedirectResponse("/", status_code=303)
        info = token.get("userinfo") or {}
        if not info.get("email") or not info.get("email_verified"):
            request.session["flash"] = "Your Google account has no verified email."
            return RedirectResponse("/", status_code=303)
        return _signed_in(request, info["email"], info.get("given_name") or info.get("name"))

    @app.post("/dev-login")
    async def dev_login(request: Request):
        if not dev_login_allowed():
            return RedirectResponse("/", status_code=303)
        email = str((await request.form()).get("email", "")).strip()
        if "@" not in email:
            return RedirectResponse("/", status_code=303)
        return _signed_in(request, email, None)

    @app.get("/logout")
    def logout(request: Request):
        request.session.clear()
        return RedirectResponse("/", status_code=303)
