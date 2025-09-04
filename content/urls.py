from rest_framework import routers
from django.urls import path, include
from .views import PostViewSet, CommentViewSet

app_name = "content"
router = routers.DefaultRouter()

router.register("posts", PostViewSet, basename="posts")
router.register("comments", CommentViewSet, basename="comments")

urlpatterns = [path("", include(router.urls))]
