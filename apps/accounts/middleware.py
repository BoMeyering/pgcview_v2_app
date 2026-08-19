from django.shortcuts import redirect

_ALLOWED_PREFIXES = (
    "/accounts/",
    "/admin/",
    "/static/",
    "/media/",
)


class ApprovalRequiredMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = request.user
        if (
            user.is_authenticated
            and not getattr(user, "is_approved", False)
            and not user.is_staff
            and not any(request.path.startswith(p) for p in _ALLOWED_PREFIXES)
        ):
            return redirect("accounts:pending_approval")
        return self.get_response(request)
