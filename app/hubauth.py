"""Login through JupyterHub when the service runs inside JupyDo (APP_ROLE=hub).

JupyterHub runs this app as a managed service under /services/<name>/ and
provides the OAuth client credentials in the environment. Every request needs a
logged-in hub user; the hub's admin flag decides admin or user rights (see
main._is_admin). Static files stay public.
"""

import os

from flask import abort, g, make_response, redirect, request, session
from jupyterhub.services.auth import HubOAuth


def init_app(app):
    auth = HubOAuth(cache_max_age=60)
    app.secret_key = os.urandom(32)  # sessions reset on restart: users log in again
    app.config["SESSION_COOKIE_NAME"] = "genome-index-session"
    app.config["SESSION_COOKIE_HTTPONLY"] = True

    @app.before_request
    def _require_hub_login():
        if request.endpoint in ("hub_oauth_callback", "static"):
            return None
        token = session.get("hub_token")
        user = None
        if token:
            try:
                user = auth.user_for_token(token)
            except Exception:
                user = None
        if user:
            g.hub_user = user
            return None
        if request.path.startswith("/api/"):
            return {"error": "Not logged in: reload the page."}, 401
        state = auth.generate_state(next_url=request.script_root + request.path)
        response = make_response(redirect(auth.login_url + "&state=" + state))
        response.set_cookie(auth.state_cookie_name, state, httponly=True)
        return response

    @app.route("/oauth_callback", endpoint="hub_oauth_callback")
    def _oauth_callback():
        code = request.args.get("code")
        arg_state = request.args.get("state")
        cookie_state = request.cookies.get(auth.state_cookie_name)
        if not code or not arg_state or arg_state != cookie_state:
            abort(403)
        session["hub_token"] = auth.token_for_code(code)
        next_url = auth.get_next_url(cookie_state) or (request.script_root + "/")
        response = make_response(redirect(next_url))
        response.delete_cookie(auth.state_cookie_name)
        return response
