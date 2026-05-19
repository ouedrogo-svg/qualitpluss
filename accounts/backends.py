from django.contrib.auth.backends import ModelBackend
from django.contrib.auth.models import User


class NomBackend(ModelBackend):
    """Connexion avec le nom, le prénom et le mot de passe."""

    def authenticate(self, request, username=None, password=None, **kwargs):
        if not username or not password:
            return None
        nom = username.strip()
        prenom = (kwargs.get("first_name") or "").strip()
        if not nom or not prenom:
            return None
        users = User.objects.filter(
            last_name__iexact=nom,
            first_name__iexact=prenom,
        )
        if users.count() != 1:
            return None
        user = users.get()
        if user.check_password(password) and self.user_can_authenticate(user):
            return user
        return None

    def get_user(self, user_id):
        try:
            return User.objects.get(pk=user_id)
        except User.DoesNotExist:
            return None
