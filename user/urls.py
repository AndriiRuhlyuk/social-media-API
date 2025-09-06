from django.urls import path, include
from rest_framework.routers import DefaultRouter
from rest_framework_simplejwt.views import (
    TokenObtainPairView,
    TokenRefreshView,
    TokenVerifyView,
)
from user import views as user_views

app_name = "user"

router = DefaultRouter()

router.register("profile", user_views.ManageProfileView, basename="profile")

urlpatterns = [
    path("", user_views.user_api_root, name="api_root"),
    path("register/", user_views.CreateUserView.as_view(), name="create"),
    path("token/", TokenObtainPairView.as_view(), name="token_obtain_pair"),
    path("token/refresh/", TokenRefreshView.as_view(), name="token_refresh"),
    path("token/verify/", TokenVerifyView.as_view(), name="token_verify"),
    path("me/", user_views.ManageUserView.as_view(), name="manage"),
    path("logout/", user_views.LogoutUserView.as_view(), name="logout"),
    path("", include(router.urls)),
    # path("profile/me/", user_views.ManageProfileView.as_view(), name="manage_profile"),
]
