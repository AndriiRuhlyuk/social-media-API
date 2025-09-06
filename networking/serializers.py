from rest_framework import serializers
from rest_framework.reverse import reverse

from networking.models import Follow
from user.models import Profile
from datetime import date


class ProfileListSerializer(serializers.ModelSerializer):
    full_name = serializers.CharField(read_only=True)
    follow_status = serializers.SerializerMethodField()
    profile_detail = serializers.SerializerMethodField()

    class Meta:
        model = Profile
        fields = (
            "id",
            "full_name",
            "profile_picture",
            "is_private",
            "followers_count",
            "following_count",
            "follow_status",
            "profile_detail",
        )

    def get_follow_status(self, obj):
        return getattr(obj, "follow_status", None)

    def get_profile_detail(self, obj):
        request = self.context.get("request")
        return reverse(
            "networking:profiles-detail", kwargs={"pk": obj.pk}, request=request
        )


class PrivateProfileSerializer(serializers.ModelSerializer):
    full_name = serializers.CharField(read_only=True)

    class Meta:
        model = Profile
        fields = [
            "id",
            "full_name",
            "profile_picture",
            "is_private",
        ]


class ProfileDetailSerializer(serializers.ModelSerializer):

    full_name = serializers.CharField(read_only=True)
    follow_status = serializers.SerializerMethodField()
    age = serializers.SerializerMethodField()

    class Meta:
        model = Profile
        fields = (
            "id",
            "full_name",
            "bio",
            "date_of_birth",
            "age",
            "location",
            "gender",
            "profile_picture",
            "is_private",
            "followers_count",
            "following_count",
            "posts_count",
            "created_at",
            "follow_status",
        )

    def get_follow_status(self, obj):
        return getattr(obj, "follow_status", None)

    def get_age(self, obj):
        """Calculate user's age"""
        if obj.date_of_birth:
            today = date.today()
            return (
                today.year
                - obj.date_of_birth.year
                - (
                    (today.month, today.day)
                    < (obj.date_of_birth.month, obj.date_of_birth.day)
                )
            )
        return None


class FollowRequestSerializer(serializers.ModelSerializer):
    """Serializer for view all follow requests with accept/reject urls"""

    follower_id = serializers.IntegerField(source="follower.id", read_only=True)
    full_name = serializers.CharField(source="follower.full_name", read_only=True)
    profile_picture = serializers.ImageField(
        source="follower.profile_picture", read_only=True
    )
    requested_at = serializers.DateTimeField(source="created_at", read_only=True)
    accept_url = serializers.SerializerMethodField()
    reject_url = serializers.SerializerMethodField()

    class Meta:
        model = Follow
        fields = [
            "follower_id",
            "full_name",
            "profile_picture",
            "requested_at",
            "status",
            "accept_url",
            "reject_url",
        ]

    def get_accept_url(self, obj):
        req = self.context.get("request")
        return reverse(
            "networking:profiles-accept-request",
            kwargs={"follower_id": obj.follower_id},
            request=req,
        )

    def get_reject_url(self, obj):
        req = self.context.get("request")
        return reverse(
            "networking:profiles-reject-request",
            kwargs={"follower_id": obj.follower_id},
            request=req,
        )


class FollowStatusSerializer(serializers.Serializer):
    """Serializer for follow status response"""

    followed = serializers.BooleanField(read_only=True)
