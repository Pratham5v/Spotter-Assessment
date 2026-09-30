from django.contrib import admin
from django.http import JsonResponse
from django.urls import path

urlpatterns = [
    path("health/", lambda request: JsonResponse({"status": "ok"})),
    path("admin/", admin.site.urls),
]
