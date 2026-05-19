from django.urls import path

from . import views

app_name = "accounts"

urlpatterns = [
    path("connexion/", views.CustomLoginView.as_view(), name="login"),
    path("deconnexion/", views.CustomLogoutView.as_view(), name="logout"),
    path("inscription/", views.signup, name="signup"),
    path(
        "mot-de-passe/modifier/",
        views.CustomPasswordChangeView.as_view(),
        name="password_change",
    ),
]
