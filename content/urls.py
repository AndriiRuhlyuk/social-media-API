from rest_framework import routers
from django.urls import path, include
from .views import PostViewSet

app_name = "content"
router = routers.DefaultRouter()

router.register("posts", PostViewSet, basename="posts")

urlpatterns = [path("", include(router.urls))]
