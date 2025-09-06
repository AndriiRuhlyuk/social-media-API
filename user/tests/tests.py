import os
import tempfile
from PIL import Image
from django.test import TestCase
from django.contrib.auth import get_user_model
from rest_framework import status
from rest_framework.test import APIClient
from rest_framework.reverse import reverse
from rest_framework_simplejwt.tokens import RefreshToken
from user.models import Profile
from user.serializers import UserSerializer, ProfileSerializer
from django.utils import timezone
from datetime import date, timedelta
from user.tasks import create_user_profile_task

USER_URL = reverse("user:api_root")
REGISTER_URL = reverse("user:create")
MANAGE_URL = reverse("user:manage")
LOGOUT_URL = reverse("user:logout")
PROFILE_URL = reverse("user:profile-detail", kwargs={"pk": "me"})


def sample_user(**params):
    """Create and return a sample user."""
    defaults = {
        "email": "test@example.com",
        "password": "testpassword123",
    }
    defaults.update(params)
    return get_user_model().objects.create_user(**defaults)


def sample_profile(user=None, **params):
    """Create and return a sample profile."""
    if user is None:
        user = sample_user()
    defaults = {
        "user": user,
        "first_name": "Test",
        "last_name": "User",
        "is_private": False,
    }
    defaults.update(params)
    return Profile.objects.create(**defaults)


def image_upload_url():
    """Return URL for profile image upload."""
    return reverse("user:profile-upload-image")


class UnauthenticatedUserApiTests(TestCase):
    def setUp(self):
        self.client = APIClient()

    def test_register_access_allowed(self):
        """Test that unauthenticated users can access the register endpoint."""
        res = self.client.get(REGISTER_URL)
        self.assertEqual(res.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)

    def test_manage_user_unauthorized(self):
        """Test that manage user endpoint requires authentication."""
        res = self.client.get(MANAGE_URL)
        self.assertEqual(res.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_logout_unauthorized(self):
        """Test that logout endpoint requires authentication."""
        res = self.client.post(LOGOUT_URL)
        self.assertEqual(res.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_profile_unauthorized(self):
        """Test that profile endpoint requires authentication."""
        res = self.client.get(PROFILE_URL)
        self.assertEqual(res.status_code, status.HTTP_401_UNAUTHORIZED)


class AuthenticatedUserApiTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = sample_user(email="test@test.com", password="testpassword123")
        self.profile = sample_profile(user=self.user)
        self.client.force_authenticate(user=self.user)

    def test_create_user(self):
        """Test creating a new user."""
        payload = {
            "email": "newuser@test.com",
            "password": "newpassword123",
        }
        res = self.client.post(REGISTER_URL, payload)
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)
        user = get_user_model().objects.get(email=payload["email"])
        self.assertTrue(user.check_password(payload["password"]))
        self.assertIn("id", res.data)
        create_user_profile_task.apply(args=[user.id])
        profile = Profile.objects.get(user=user)
        self.assertFalse(profile.is_private)
        self.assertEqual(profile.posts_count, 0)

    def test_retrieve_user(self):
        """Test retrieving user data."""
        res = self.client.get(MANAGE_URL)
        serializer = UserSerializer(self.user)
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(res.data, serializer.data)

    def test_update_user(self):
        """Test updating user data."""
        payload = {
            "email": "updated@test.com",
            "password": "newpassword123",
        }
        res = self.client.put(MANAGE_URL, payload)
        self.user.refresh_from_db()
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(self.user.email, payload["email"])
        self.assertTrue(self.user.check_password(payload["password"]))

    def test_retrieve_profile(self):
        """Test retrieving profile data."""
        res = self.client.get(PROFILE_URL)
        serializer = ProfileSerializer(self.profile)
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(res.data, serializer.data)

    def test_update_profile(self):
        """Test updating profile data."""
        payload = {
            "first_name": "Updated",
            "last_name": "User",
            "bio": "Updated bio",
            "date_of_birth": date(1990, 1, 1),
            "location": "Kyiv",
            "gender": "Male",
            "is_private": True,
        }
        res = self.client.put(PROFILE_URL, payload)
        self.profile.refresh_from_db()
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        for key in payload:
            self.assertEqual(payload[key], getattr(self.profile, key))

    def test_profile_invalid_date_of_birth(self):
        """Test updating profile with invalid date of birth fails."""
        payload = {"date_of_birth": (timezone.now() + timedelta(days=1)).date()}
        res = self.client.patch(PROFILE_URL, payload)
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("date_of_birth", res.data)

    def test_upload_profile_image(self):
        """Test uploading a profile image."""
        url = image_upload_url()
        with tempfile.NamedTemporaryFile(suffix=".jpg") as ntf:
            img = Image.new("RGB", (10, 10))
            img.save(ntf, format="JPEG")
            ntf.seek(0)
            res = self.client.post(url, {"profile_picture": ntf}, format="multipart")
        self.profile.refresh_from_db()
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertIn("profile_picture", res.data)
        self.assertTrue(os.path.exists(self.profile.profile_picture.path))

    def test_upload_invalid_image(self):
        """Test uploading an invalid image fails."""
        url = image_upload_url()
        res = self.client.post(
            url, {"profile_picture": "not image"}, format="multipart"
        )
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)

    def test_logout(self):
        """Test logging out with a valid refresh token."""
        refresh = RefreshToken.for_user(self.user)
        payload = {"refresh": str(refresh)}
        res = self.client.post(LOGOUT_URL, payload)
        self.assertEqual(res.status_code, status.HTTP_204_NO_CONTENT)
        self.assertEqual(res.data["detail"], "Successfully logged out")

    def test_logout_invalid_token(self):
        """Test logging out with an invalid token fails."""
        payload = {"refresh": "invalid_token"}
        res = self.client.post(LOGOUT_URL, payload)
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("refresh", res.data)

    def test_logout_all_tokens(self):
        """Test logging out all tokens."""
        refresh1 = RefreshToken.for_user(self.user)
        refresh2 = RefreshToken.for_user(self.user)
        payload = {"refresh": str(refresh1), "all_tokens": True}
        res = self.client.post(LOGOUT_URL, payload)
        self.assertEqual(res.status_code, status.HTTP_204_NO_CONTENT)
        self.assertEqual(res.data["detail"], "Successfully logged out")
        from rest_framework_simplejwt.token_blacklist.models import BlacklistedToken

        self.assertTrue(
            BlacklistedToken.objects.filter(token__token=str(refresh1)).exists()
        )
        self.assertTrue(
            BlacklistedToken.objects.filter(token__token=str(refresh2)).exists()
        )
