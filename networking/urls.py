from rest_framework import routers
from django.urls import path, include
from .views import PublicProfileViewSet


app_name = "networking"
router = routers.DefaultRouter()

router.register("profiles", PublicProfileViewSet, basename="profiles")

urlpatterns = [path("", include(router.urls))]
