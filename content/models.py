import pathlib
import uuid

from django.db import models
from django.utils.translation import gettext as _


class Tag(models.Model):
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
        return f"Post by {self.author.full_name} at {self.created_at}"
