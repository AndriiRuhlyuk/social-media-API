import pathlib
import uuid

from django.db import models
from django.utils.translation import gettext as _


class Tag(models.Model):
    name = models.CharField(max_length=50, unique=True)

    class Meta:
        ordering = ["name"]
        indexes = [
            models.Index(fields=["name"]),
        ]

    def __str__(self):
        return self.name


def post_image_path(instance: "Post", filename: str) -> str:
    """Generate unique path to post image."""
    ext = pathlib.Path(filename).suffix
    filename = f"{instance.author.id}-{uuid.uuid4()}{ext}"
    return f"upload/post/{filename}"


class Post(models.Model):
    author = models.ForeignKey(
        "user.Profile",
        on_delete=models.CASCADE,
        related_name="posts",
        verbose_name=_("author"),
    )
    title = models.CharField(max_length=100, unique=True, verbose_name=_("title"))
    content = models.TextField(max_length=5000, verbose_name=_("content"))
    media = models.ImageField(
        upload_to=post_image_path, null=True, blank=True, verbose_name=_("media")
    )
    tags = models.ManyToManyField(
        Tag, related_name="posts", blank=True, verbose_name=_("tags")
    )
    created_at = models.DateTimeField(auto_now_add=True, verbose_name=_("created at"))
    updated_at = models.DateTimeField(auto_now=True, verbose_name=_("updated at"))

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["author"]),
            models.Index(fields=["-created_at"]),
        ]

    def __str__(self):
        return f"Post by {self.author.full_name} at {self.created_at}"
