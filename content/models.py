import pathlib
import uuid

from django.db import models
from django.utils.translation import gettext as _


class Tag(models.Model):
    """Model for tags that associate with posts for categorize content"""

    name = models.CharField(max_length=50, unique=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


def post_image_path(instance: "Post", filename: str) -> str:
    """Generate unique path to post image."""
    ext = pathlib.Path(filename).suffix
    filename = f"{instance.author.id}-{uuid.uuid4()}{ext}"
    return f"upload/post/{filename}"


class Post(models.Model):
    """Post model."""

    class PostStatus(models.TextChoices):
        DRAFT = "draft", "Draft"
        SCHEDULED = "scheduled", "Scheduled"
        PUBLISHED = "published", "Published"
        CANCELED = "canceled", "Canceled"

    author = models.ForeignKey(
        "user.Profile",
        on_delete=models.CASCADE,
        related_name="posts",
        verbose_name=_("author"),
    )
    title = models.CharField(max_length=100, verbose_name=_("title"))
    content = models.TextField(max_length=5000, verbose_name=_("content"))
    media = models.ImageField(
        upload_to=post_image_path, null=True, blank=True, verbose_name=_("media")
    )
    tags = models.ManyToManyField(
        Tag, related_name="posts", blank=True, verbose_name=_("tags")
    )
    status = models.CharField(
        max_length=10, choices=PostStatus.choices, default=PostStatus.DRAFT
    )
    scheduled_task_id = models.CharField(
        max_length=255, null=True, blank=True, editable=False
    )
    scheduled_at = models.DateTimeField(null=True, blank=True)
    published_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    likes_count = models.PositiveIntegerField(default=0)
    comments_count = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["author", "title"],
                name="unique_post_author_title",
            ),
            models.CheckConstraint(
                name="scheduled_requires_time",
                check=(
                    models.Q(status="scheduled", scheduled_at__isnull=False)
                    | (
                        ~models.Q(status="scheduled")
                        & models.Q(scheduled_at__isnull=True)
                    )
                ),
            ),
            models.CheckConstraint(
                name="published_requires_time",
                check=(
                    models.Q(status="published", published_at__isnull=False)
                    | (
                        ~models.Q(status="published")
                        & models.Q(published_at__isnull=True)
                    )
                ),
            ),
        ]
        indexes = [
            models.Index(
                fields=["-created_at"],
                name="post_published_created_idx",
                condition=models.Q(status="published"),
            ),
            models.Index(
                fields=["author", "-created_at"],
                name="post_published_author_idx",
                condition=models.Q(status="published"),
            ),
            models.Index(
                fields=["author", "scheduled_at"],
                name="post_scheduled_idx",
                condition=models.Q(status="scheduled"),
            ),
        ]

    def __str__(self):
        return f"Post: {self.title}, (#{self.id})"


class Like(models.Model):
    """Model for like sign for user's posts."""

    post = models.ForeignKey(Post, on_delete=models.CASCADE, related_name="likes")
    user = models.ForeignKey(
        "user.Profile",
        on_delete=models.CASCADE,
        related_name="likes",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["post", "user"],
                name="unique_like_user",
            ),
        ]
        indexes = [
            models.Index(fields=["post", "-created_at"], name="like_post_created_idx"),
            models.Index(fields=["user", "-created_at"], name="like_user_created_idx"),
        ]


class Comment(models.Model):
    """Model for comment on post with support threads."""

    post = models.ForeignKey(Post, on_delete=models.CASCADE, related_name="comments")
    author = models.ForeignKey(
        "user.Profile", on_delete=models.CASCADE, related_name="comments"
    )
    content = models.TextField(max_length=2000)
    parent = models.ForeignKey(
        "self",
        blank=True,
        null=True,
        on_delete=models.SET_NULL,
        related_name="children",
    )
    is_deleted = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(
                fields=["post", "created_at"], name="comment_post_created_idx"
            ),
            models.Index(
                fields=["post", "parent", "created_at"], name="comment_thread_idx"
            ),
        ]

    def __str__(self):
        return f"Comment: {self.content}"
