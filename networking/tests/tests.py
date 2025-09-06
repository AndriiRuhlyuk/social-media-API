from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework import status
from rest_framework.reverse import reverse
from rest_framework.test import APIClient

from networking.models import Follow
from networking.serializers import (
    ProfileListSerializer,
    ProfileDetailSerializer,
    PrivateProfileSerializer,
    FollowRequestSerializer,
)
from user.models import Profile


PROFILES_LIST_URL = reverse("networking:profiles-list")


def profile_detail_url(profile_id: int) -> str:
    return reverse("networking:profiles-detail", args=[profile_id])


def follow_url(profile_id: int) -> str:
    return reverse("networking:profiles-follow", args=[profile_id])


def unfollow_url(profile_id: int) -> str:
    return reverse("networking:profiles-unfollow", args=[profile_id])


def accept_request_url(follower_id: int) -> str:
    return reverse("networking:profiles-accept-request", args=[follower_id])


def reject_request_url(follower_id: int) -> str:
    return reverse("networking:profiles-reject-request", args=[follower_id])


def sample_user(**params):
    defaults = {"email": "test@example.com", "password": "testpassword123"}
    defaults.update(params)
    return get_user_model().objects.create_user(**defaults)


def sample_profile(user=None, **params):
    if user is None:
        user = sample_user()
    defaults = {
        "user": user,
        "first_name": "Test",
        "last_name": "User",
        "is_private": False,
        "followers_count": 0,
        "following_count": 0,
    }
    defaults.update(params)
    return Profile.objects.create(**defaults)


class UnauthenticatedNetworkingApiTests(TestCase):
    def setUp(self):
        self.client = APIClient()

    def test_profiles_list_unauthorized(self):
        res = self.client.get(PROFILES_LIST_URL)
        self.assertEqual(res.status_code, status.HTTP_401_UNAUTHORIZED)


class AuthenticatedNetworkingApiTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = sample_user(email="test@test.com")
        self.profile = sample_profile(user=self.user)
        self.client.force_authenticate(user=self.user)

    def test_list_profiles(self):
        """List returns other users (excludes me)."""
        other_profile = sample_profile(user=sample_user(email="other@test.com"))

        res = self.client.get(PROFILES_LIST_URL)
        self.assertEqual(res.status_code, status.HTTP_200_OK)

        serializer = ProfileListSerializer(
            [other_profile], many=True, context={"request": res.wsgi_request}
        )

        res_ids = sorted([p["id"] for p in res.data["results"]])
        ser_ids = sorted([p["id"] for p in serializer.data])
        self.assertEqual(res_ids, ser_ids)
        self.assertNotIn(self.profile.id, res_ids)

        self.assertEqual(res.data["results"][0], serializer.data[0])

    def test_filter_profiles_by_location(self):
        """Filter by location returns only matching others (excludes me)."""
        p1 = sample_profile(user=sample_user(email="u1@test.com"), location="Kyiv")
        p2 = sample_profile(user=sample_user(email="u2@test.com"), location="Kyiv")
        p3 = sample_profile(user=sample_user(email="u3@test.com"), location="Lviv")

        res = self.client.get(PROFILES_LIST_URL, {"location": "Kyiv"})
        self.assertEqual(res.status_code, status.HTTP_200_OK)

        serializer = ProfileListSerializer(
            [p1, p2], many=True, context={"request": res.wsgi_request}
        )

        res_sorted = sorted(res.data["results"], key=lambda x: x["id"])
        ser_sorted = sorted(serializer.data, key=lambda x: x["id"])
        self.assertEqual(res_sorted, ser_sorted)
        self.assertNotIn(p3.id, [p["id"] for p in res.data["results"]])

    def test_profile_detail_public(self):
        other_profile = sample_profile(
            user=sample_user(email="other@test.com"), is_private=False
        )
        url = profile_detail_url(other_profile.id)
        res = self.client.get(url)
        self.assertEqual(res.status_code, status.HTTP_200_OK)

        serializer = ProfileDetailSerializer(
            other_profile, context={"request": res.wsgi_request}
        )
        self.assertEqual(res.data, serializer.data)

    def test_profile_detail_private_not_followed(self):
        other_profile = sample_profile(
            user=sample_user(email="private@test.com"), is_private=True
        )
        url = profile_detail_url(other_profile.id)
        res = self.client.get(url)
        self.assertEqual(res.status_code, status.HTTP_200_OK)

        serializer = PrivateProfileSerializer(
            other_profile, context={"request": res.wsgi_request}
        )
        self.assertEqual(res.data, serializer.data)

    def test_follow_public_profile(self):
        other_profile = sample_profile(
            user=sample_user(email="pub@test.com"), is_private=False
        )
        url = follow_url(other_profile.id)
        res = self.client.post(url)
        self.assertIn(res.status_code, (status.HTTP_201_CREATED, status.HTTP_200_OK))
        self.assertEqual(res.data["status"], Follow.FollowStatus.ACCEPTED)

        follow = Follow.objects.get(follower=self.profile, following=other_profile)
        self.assertEqual(follow.status, Follow.FollowStatus.ACCEPTED)

        other_profile.refresh_from_db()
        self.profile.refresh_from_db()
        self.assertEqual(other_profile.followers_count, 1)
        self.assertEqual(self.profile.following_count, 1)

    def test_follow_private_profile(self):
        other_profile = sample_profile(
            user=sample_user(email="priv@test.com"), is_private=True
        )
        url = follow_url(other_profile.id)
        res = self.client.post(url)
        self.assertEqual(res.status_code, status.HTTP_202_ACCEPTED)
        self.assertEqual(res.data["status"], Follow.FollowStatus.PENDING)

        follow = Follow.objects.get(follower=self.profile, following=other_profile)
        self.assertEqual(follow.status, Follow.FollowStatus.PENDING)

    def test_unfollow_profile(self):
        other_profile = sample_profile(user=sample_user(email="x@test.com"))
        Follow.objects.create(
            follower=self.profile,
            following=other_profile,
            status=Follow.FollowStatus.ACCEPTED,
        )
        url = unfollow_url(other_profile.id)
        res = self.client.post(url)
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertFalse(
            Follow.objects.filter(
                follower=self.profile, following=other_profile
            ).exists()
        )

        other_profile.refresh_from_db()
        self.profile.refresh_from_db()
        self.assertEqual(other_profile.followers_count, 0)
        self.assertEqual(self.profile.following_count, 0)

    def test_follow_self_forbidden(self):
        """Current implementation returns 404 for self-detail follow route."""
        url = follow_url(self.profile.id)
        res = self.client.post(url)
        self.assertEqual(res.status_code, status.HTTP_404_NOT_FOUND)

    def test_list_followers(self):
        other_profile = sample_profile(user=sample_user(email="follower@test.com"))
        Follow.objects.create(
            follower=other_profile,
            following=self.profile,
            status=Follow.FollowStatus.ACCEPTED,
        )

        res = self.client.get(reverse("networking:profiles-my-followers"))
        self.assertEqual(res.status_code, status.HTTP_200_OK)

        other_profile.refresh_from_db()

        serializer = ProfileListSerializer(
            [other_profile], many=True, context={"request": res.wsgi_request}
        )
        self.assertEqual(res.data, serializer.data)

    def test_list_following(self):
        other_profile = sample_profile(user=sample_user(email="following@test.com"))
        Follow.objects.create(
            follower=self.profile,
            following=other_profile,
            status=Follow.FollowStatus.ACCEPTED,
        )

        res = self.client.get(reverse("networking:profiles-my-following"))
        self.assertEqual(res.status_code, status.HTTP_200_OK)

        other_profile.refresh_from_db()
        setattr(other_profile, "follow_status", Follow.FollowStatus.ACCEPTED)

        serializer = ProfileListSerializer(
            [other_profile], many=True, context={"request": res.wsgi_request}
        )
        self.assertEqual(res.data, serializer.data)

    def test_list_pending_requests(self):
        other_profile = sample_profile(user=sample_user(email="pending@test.com"))
        Follow.objects.create(
            follower=other_profile,
            following=self.profile,
            status=Follow.FollowStatus.PENDING,
        )

        res = self.client.get(reverse("networking:profiles-my-pending-requests"))
        self.assertEqual(res.status_code, status.HTTP_200_OK)

        serializer = FollowRequestSerializer(
            Follow.objects.filter(following=self.profile),
            many=True,
            context={"request": res.wsgi_request},
        )

        for res_item, serializer_item in zip(res.data, serializer.data):
            self.assertEqual(res_item["follower_id"], serializer_item["follower_id"])
            self.assertEqual(res_item["status"], serializer_item["status"])
