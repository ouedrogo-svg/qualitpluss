from django.conf import settings
from django.conf.urls.static import static
from django.contrib.staticfiles.urls import staticfels_urlpatterns
from django.contrib import admin
from django.urls import include, path

admin.site.site_header = "SUJETLigne — administration"
admin.site.site_title = "SUJETLigne"
admin.site.index_title = "Tableau de bord"

urlpatterns = [
    path("admin/", admin.site.urls),
    path("comptes/", include("accounts.urls")),
    path("", include("courses.urls")),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
urlpatterns += staticfels_urlpatterns()