from django.db import transaction
from rest_framework import serializers
from rest_framework.reverse import reverse
from content.scheduling import reschedule_publish, revoke_task
from django.utils import timezone

from content.models import Post, Tag
import re


class TagSerializer(serializers.ModelSerializer):
    """Tag serializer"""

    class Meta:
        model = Tag
        fields = ("name",)


class TagFilterSerializer(serializers.Serializer):
    tags = serializers.CharField(help_text="Comma/space separated tags")
    mode = serializers.ChoiceField(choices=["all", "any"], default="all")

    def validate_tags(self, value):
        parts = [p.strip() for p in re.split(r"[,\s]+", value) if p.strip()]

        return list(dict.fromkeys(map(str.lower, parts)))


HASHTAG_RE = re.compile(r"(?<!\w)#([\w-]{1,50})", flags=re.UNICODE)


class PostSerializer(serializers.ModelSerializer):
    """Post serializer (Retrieve, Update, Delete, Create)"""

    author_full_name = serializers.CharField(source="author.full_name", read_only=True)
    tags_display = TagSerializer(source="tags", many=True, read_only=True)
    status = serializers.ChoiceField(choices=Post.PostStatus.choices, required=False)
    scheduled_at = serializers.DateTimeField(required=False, allow_null=True)
    published_at = serializers.DateTimeField(read_only=True)

    class Meta:
        model = Post
        fields = [
            "id",
            "title",
            "author_full_name",
            "content",
            "media",
            "tags_display",
            "status",
            "scheduled_at",
            "published_at",
            "created_at",
            "updated_at",
        ]

    def _extract_tags_from_content(self, content: str) -> list[str]:
        """Extract tags from content"""
        return [m.lower() for m in HASHTAG_RE.findall(content or "")]

    def _upsert_and_fetch_tags(self, names: list[str]) -> list[Tag]:
        """Normalization tags & return list from DB"""
        norm = {t.lower() for t in names if t and t.strip()}
        if not norm:
            return []
        Tag.objects.bulk_create([Tag(name=n) for n in norm], ignore_conflicts=True)

        return list(Tag.objects.filter(name__in=norm))

    def validate(self, data):
        """Validate post status"""
        instance = getattr(self, "instance", None)

        if instance and instance.status == Post.PostStatus.PUBLISHED:
            if "status" in data and data["status"] != Post.PostStatus.PUBLISHED:
                raise serializers.ValidationError(
                    {"status": "Published post can't change status."}
                )
            if "scheduled_at" in data and data["scheduled_at"] is not None:
                raise serializers.ValidationError(
                    {"scheduled_at": "Published post can't be scheduled."}
                )
            data["status"] = Post.PostStatus.PUBLISHED
            data["scheduled_at"] = None
            return data

        target_status = data.get(
            "status", getattr(self.instance, "status", Post.PostStatus.DRAFT)
        )
        scheduled_at = data.get(
            "scheduled_at", getattr(self.instance, "scheduled_at", None)
        )
        if target_status == Post.PostStatus.SCHEDULED:
            if not scheduled_at:
                raise serializers.ValidationError(
                    {"scheduled_at": "This field is required for scheduled posts."}
                )
            if scheduled_at <= timezone.now():
                raise serializers.ValidationError(
                    {"scheduled_at": "Must be in the future."}
                )
        else:
            data["scheduled_at"] = None

        return data

    def validate_content(self, value):
        """Put in context extracted tags."""
        extracted = self._extract_tags_from_content(value)
        if extracted:
            self.context["extracted_tags"] = extracted
        else:
            self.context["extracted_tags"] = []
        return value

    def create(self, validated_data):
        """Create post with tags from content and status."""
        with transaction.atomic():
            if validated_data.get(
                "status"
            ) == Post.PostStatus.PUBLISHED and not validated_data.get("published_at"):
                validated_data["published_at"] = timezone.now()

            post = super().create(validated_data)

            if post.status == Post.PostStatus.SCHEDULED and post.scheduled_at:
                transaction.on_commit(lambda: reschedule_publish(post))

            tags = self._upsert_and_fetch_tags(self.context.get("extracted_tags", []))
            if tags:
                post.tags.set(tags)
            return post

    def update(self, instance, validated_data):
        """Update post and its tags from content and status."""
        with transaction.atomic():
            old_status = instance.status
            new_status = validated_data.get("status", old_status)

            if (
                old_status != Post.PostStatus.PUBLISHED
                and new_status == Post.PostStatus.PUBLISHED
            ):
                validated_data.setdefault("published_at", timezone.now())
                validated_data["scheduled_at"] = None
                validated_data["scheduled_task_id"] = None

            leaving_scheduled = (
                old_status == Post.PostStatus.SCHEDULED
                and new_status != Post.PostStatus.SCHEDULED
            )
            task_id_to_revoke = (
                instance.scheduled_task_id if leaving_scheduled else None
            )

            post = super().update(instance, validated_data)

            if post.status == Post.PostStatus.SCHEDULED and post.scheduled_at:
                transaction.on_commit(lambda: reschedule_publish(post))

            elif task_id_to_revoke:
                transaction.on_commit(lambda: revoke_task(task_id_to_revoke))

            if "extracted_tags" in self.context:
                tags = self._upsert_and_fetch_tags(
                    self.context.get("extracted_tags", [])
                )
                post.tags.set(tags)
                post._prefetched_objects_cache = {"tags": list(tags)}

            return post


class PostListSerializer(serializers.ModelSerializer):
    """PostListSerializer (List)"""

    author_full_name = serializers.CharField(source="author.full_name", read_only=True)
    detail = serializers.SerializerMethodField()

    class Meta:
        model = Post
        fields = [
            "id",
            "title",
            "author_full_name",
            "created_at",
            "media",
            "detail",
            "status",
        ]

    def get_detail(self, obj):
        request = self.context.get("request")
        return reverse("content:posts-detail", kwargs={"pk": obj.pk}, request=request)
