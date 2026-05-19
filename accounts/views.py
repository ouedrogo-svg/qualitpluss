from django.conf import settings
from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.views import LoginView, LogoutView, PasswordChangeView
from django.shortcuts import redirect, render
from django.urls import reverse_lazy

from .forms import CustomPasswordChangeForm, NameAuthenticationForm, SignUpForm

LOGIN_BACKEND = settings.AUTHENTICATION_BACKENDS[0]


class CustomLoginView(LoginView):
    template_name = "accounts/login.html"
    authentication_form = NameAuthenticationForm
    redirect_authenticated_user = True


class CustomLogoutView(LogoutView):
    next_page = reverse_lazy("courses:home")


class CustomPasswordChangeView(PasswordChangeView):
    template_name = "accounts/password_change.html"
    form_class = CustomPasswordChangeForm
    success_url = reverse_lazy("courses:home")

    def form_valid(self, form):
        messages.success(self.request, "Votre mot de passe a été modifié.")
        return super().form_valid(form)


def signup(request):
    if request.user.is_authenticated:
        return redirect("courses:home")
    if request.method == "POST":
        form = SignUpForm(request.POST)
        if form.is_valid():
            user = form.save()
            login(request, user, backend=LOGIN_BACKEND)
            return redirect("courses:home")
    else:
        form = SignUpForm()
    return render(request, "accounts/signup.html", {"form": form})
