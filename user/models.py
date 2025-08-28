import pathlib
import uuid
from django.contrib.postgres.indexes import BTreeIndex

from django.conf import settings
from django.contrib.auth.models import (
    AbstractUser,
    BaseUserManager,
)
from django.db import models
from django.utils.translation import gettext as _


class UserManager(BaseUserManager):
    """Define a model manager for User model with no username field."""

    use_in_migrations = True

    def _create_user(self, email, password, **extra_fields):
        """Create and save a User with the given email and password."""
        if not email:
            raise ValueError("The email must be set")
        email = self.normalize_email(email)
        user = self.model(email=email, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_user(self, email, password=None, **extra_fields):
        """Create and save a User with the given email and password."""
        extra_fields.setdefault("is_staff", False)
        extra_fields.setdefault("is_superuser", False)
        return self._create_user(email, password, **extra_fields)

    def create_superuser(self, email, password, **extra_fields):
        """Create and save a SuperUser with the given email and password."""
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)

        if extra_fields.get("is_staff") is not True:
            raise ValueError("Superuser must have is_staff=True.")
        if extra_fields.get("is_superuser") is not True:
            raise ValueError("Superuser must have is_superuser=True.")

        return self._create_user(email, password, **extra_fields)


class User(AbstractUser):
    """
    Default user model for this project:
    - without username
    - with email
    - fields first_name and last_name transferred to Profile
    """

    username = None
    first_name = None
    last_name = None
    email = models.EmailField(_("email address"), unique=True)

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = []

    objects = UserManager()

    @property
    def full_name(self):
        if hasattr(self, "profile"):
            return self.profile.full_name
        return self.email.split("@")[0]


def profile_image_path(instance: "Profile", filename: str) -> str:
    """Generate unique path to profile image."""
    ext = pathlib.Path(filename).suffix
    filename = f"{instance.user.id}-{uuid.uuid4()}{ext}"
    return f"upload/profile/{filename}"


class Profile(models.Model):
    """Model representing a user's profile."""

    class GenderChoices(models.TextChoices):
        MALE = "Male"
        FEMALE = "Female"
        OTHER = "Other"

    first_name = models.CharField(max_length=255, blank=True)
    last_name = models.CharField(max_length=255, blank=True)
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="profile"
    )
    bio = models.TextField(max_length=500, blank=True)
    profile_picture = models.ImageField(
        blank=True, null=True, upload_to=profile_image_path
    )
    date_of_birth = models.DateField(
        blank=True,
        null=True,
    )
    location = models.CharField(max_length=100, blank=True)
    is_private = models.BooleanField(default=False)
    followers_count = models.PositiveIntegerField(default=0)
    following_count = models.PositiveIntegerField(default=0)
    gender = models.CharField(
        max_length=10, choices=GenderChoices.choices, default=GenderChoices.OTHER
    )
    posts_count = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    @property
    def full_name(self):
        if self.first_name and self.last_name:
            return f"{self.first_name} {self.last_name}"
        return self.first_name or self.last_name or self.user.email.split("@")[0]

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["location"]),
            models.Index(fields=["gender"]),
            models.Index(fields=["is_private"]),
            models.Index(fields=["first_name"]),
            models.Index(fields=["last_name"]),
            BTreeIndex(fields=["-created_at"]),
        ]

    def can_view_details(self, viewer_user) -> bool:
        """
        Privacy Rules :
        - if public profile — can see all
        - owner can see
        - else need have ACCEPTED-follow from viewer -> self
        """
        if not self.is_private:
            return True

        if not getattr(viewer_user, "is_authenticated", False):
            return False

        if viewer_user.id == self.user_id:
            return True

        viewer_profile = getattr(viewer_user, "profile", None)

        from networking.models import Follow

        return Follow.objects.filter(
            follower_id=viewer_profile.id,
            following_id=self.id,
            status=Follow.FollowStatus.ACCEPTED,
        ).exists()

    def __str__(self):
        return f"Profile of {self.full_name}"
