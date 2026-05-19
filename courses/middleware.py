"""Précharge les abonnements mensuels pour éviter une requête par vue / context processor."""


class PrefetchUserSubscriptionMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = getattr(request, "user", None)
        if user is not None and user.is_authenticated:
            from django.contrib.auth import get_user_model

            User = get_user_model()
            request.user = User.objects.prefetch_related(
                "month_subscriptions__category"
            ).get(pk=user.pk)
        return self.get_response(request)
