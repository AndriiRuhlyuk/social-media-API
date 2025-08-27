from datetime import date

from django.contrib.auth import get_user_model
from rest_framework import serializers
from rest_framework.exceptions import ValidationError
from rest_framework_simplejwt.tokens import RefreshToken, TokenError

from user.models import Profile


class UserSerializer(serializers.ModelSerializer):
    """User serializer"""

    password = serializers.CharField(
        write_only=True,
        min_length=5,
        style={"input_type": "password"},
        trim_whitespace=False,
    )

    class Meta:
        model = get_user_model()
        fields = ("id", "email", "password", "is_staff")
        read_only_fields = ("is_staff",)
        extra_kwargs = {"password": {"write_only": True, "min_length": 5}}

    def create(self, validated_data):
        """Create a new user with encrypted password and return it"""

        return get_user_model().objects.create_user(**validated_data)

    def update(self, instance, validated_data):
        """Update a user, set the password correctly and return it"""

        password = validated_data.pop("password", None)
        user = super().update(instance, validated_data)

        if password:
            user.set_password(password)
            user.save()
        return user


class LogoutSerializer(serializers.Serializer):
    """Logout serializer"""

    refresh = serializers.CharField(
        write_only=True,
        required=True,
        help_text="Refresh token to be blacklisted",
    )
    all_tokens = serializers.BooleanField(
        required=False,
        default=False,
        help_text="Set to true to blacklist all refresh tokens for the user",
    )

    def validate_refresh(self, value):
        try:
            token = RefreshToken(value)

            token_user_id = token.payload.get("user_id")
            authenticated_user_id = self.context["request"].user.id

            if int(token_user_id) != int(authenticated_user_id):
                raise ValidationError(
                    "Refresh token does not belong to the authenticated user"
                )

            token.verify()

        except TokenError as e:
            raise ValidationError("Invalid or expired refresh token")
        except (ValueError, TypeError):

            raise ValidationError("Invalid token format")
        except Exception as e:
            raise ValidationError("Token validation failed")

        return value


class ProfileSerializer(serializers.ModelSerializer):
    """Profile serializer"""

    email = serializers.CharField(source="user.email", read_only=True)
    age = serializers.SerializerMethodField()

    class Meta:
        model = Profile
        fields = (
            "id",
            "email",
            "first_name",
            "last_name",
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
            "updated_at",
        )
        read_only_fields = ["followers_count", "following_count", "posts_count"]

    def validate_date_of_birth(self, value):
        """Validate birthdate"""
        if value:
            today = date.today()
            age = (
                today.year
                - value.year
                - ((today.month, today.day) < (value.month, value.day))
            )

            if age < 13:
                raise ValidationError("You must be at least 13 years old to register.")

            if age > 100:
                raise ValidationError("Please enter a valid birth date.")

            if value > today:
                raise ValidationError("Birth date cannot be in the future.")

        return value

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
