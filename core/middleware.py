class NoStoreSensitiveResponsesMiddleware:
    """Prevent browsers from retaining authenticated pages or form responses."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        user = getattr(request, "user", None)
        is_authenticated = bool(user and user.is_authenticated)
        is_post = request.method not in {"GET", "HEAD", "OPTIONS"}
        is_login = request.path in {"/accounts/login/", "/admin/login/"}
        is_service_worker = request.path == "/sw.js"
        if (is_authenticated or is_post or is_login) and not is_service_worker:
            response["Cache-Control"] = "private, no-store, no-cache, max-age=0, must-revalidate"
            response["Pragma"] = "no-cache"
            response["Expires"] = "0"
        return response
