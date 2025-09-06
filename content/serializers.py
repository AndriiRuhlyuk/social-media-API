from datetime import timedelta

from django.db import transaction
from rest_framework import serializers
from rest_framework.reverse import reverse
from content.scheduling import reschedule_publish, revoke_task
from django.utils import timezone

from content.models import Post, Tag, Comment
import re

from networking.models import Follow


class TagSerializer(serializers.ModelSerializer):
    """Tag serializer"""

    class Meta:
        model = Tag
        fields = ("name",)


class TagFilterSerializer(serializers.Serializer):
    """Tag filter serializer"""

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
            "likes_count",
            "comments_count",
        ]
        read_only_fields = [
            "likes_count",
            "comments_count",
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
    liked_by_me = serializers.BooleanField(read_only=True)

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
            "liked_by_me",
        ]

    def get_detail(self, obj):
        request = self.context.get("request")
        return reverse(
            "content:posts-detail",
            kwargs={"pk": obj.pk},
            request=request,
        )


class LikeStatusSerializer(serializers.Serializer):
    """Serializer for like status response"""

    liked = serializers.BooleanField(read_only=True)
    likes_count = serializers.IntegerField(read_only=True)


class CommentSerializer(serializers.ModelSerializer):
    """Serializer for Comment model"""

    author_full_name = serializers.CharField(source="author.full_name", read_only=True)
    post_id = serializers.PrimaryKeyRelatedField(
        source="post", queryset=Post.objects.none()
    )
    parent_id = serializers.PrimaryKeyRelatedField(
        source="parent",
        queryset=Comment.objects.filter(parent__isnull=True, is_deleted=False),
        allow_null=True,
        required=False,
    )

    children_count = serializers.IntegerField(read_only=True)

    class Meta:
        model = Comment
        fields = [
            "id",
            "post_id",
            "author_full_name",
            "content",
            "parent_id",
            "is_deleted",
            "created_at",
            "updated_at",
            "children_count",
        ]
        read_only_fields = [
            "author_full_name",
            "created_at",
            "updated_at",
        ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        request = self.context.get("request")

        if request and request.user.is_authenticated:
            visible_posts = self._get_or_cache_visible_posts(request)
            self.fields["post_id"].queryset = visible_posts

    def _get_or_cache_visible_posts(self, request):
        """Get visible posts with request-level caching to avoid duplicate queries."""

        cache_key = f"_visible_posts_user_{request.user.id}"

        if hasattr(request, cache_key):
            return getattr(request, cache_key)

        profile = request.user.profile

        following_ids = Follow.objects.filter(
            follower=profile,
            status=Follow.FollowStatus.ACCEPTED,
        ).values_list("following_id", flat=True)

        visible_posts = Post.objects.filter(
            status=Post.PostStatus.PUBLISHED,
            author_id__in=list(following_ids)
            + [profile.id],  # list() тільки тут де потрібно
        )

        setattr(request, cache_key, visible_posts)
        return visible_posts

    def validate_content(self, value):
        """Validate empty comment content"""
        if not value.strip():
            raise serializers.ValidationError("Comment content cannot be empty.")
        return value

    def validate(self, data):
        """Validate spam protection with optimized query"""
        author = self.context["request"].user.profile

        cutoff_time = timezone.now() - timedelta(seconds=30)
        recent_comment_exists = Comment.objects.filter(
            author=author, created_at__gte=cutoff_time
        ).exists()

        if recent_comment_exists:
            raise serializers.ValidationError("You are commenting too quickly.")
        return data

    def validate_parent(self, value):
        """Validate that parent belongs to the same post"""
        if not value:
            return value

        post_data = self.initial_data.get("post_id")
        if not post_data:
            return value

        try:
            post_id = post_data if isinstance(post_data, int) else int(post_data)
        except (ValueError, TypeError):
            raise serializers.ValidationError("Invalid post ID.")

        if value.post_id != post_id:
            raise serializers.ValidationError(
                "Parent comment must belong to the same post."
            )
        return value


class CommentListSerializer(serializers.ModelSerializer):
    """Serializer for Comment list"""

    author_full_name = serializers.CharField(source="author.full_name", read_only=True)
    post_title = serializers.CharField(source="post.title", read_only=True)
    detail = serializers.SerializerMethodField()
    children_count = serializers.IntegerField(read_only=True)

    class Meta:
        model = Comment
        fields = [
            "id",
            "post_title",
            "author_full_name",
            "parent",
            "is_deleted",
            "created_at",
            "children_count",
            "detail",
        ]

    def get_detail(self, obj):
        request = self.context.get("request")
        return reverse(
            "content:comments-detail",
            kwargs={"pk": obj.pk},
            request=request,
        )


class CommentUpdateSerializer(serializers.ModelSerializer):
    """Serializer for Comment update"""

    class Meta:
        model = Comment
        fields = [
            "id",
            "content",
            "updated_at",
        ]
        read_only_fields = ["id", "updated_at"]

    def validate_content(self, value):
        """Validate comment content"""
        if not value.strip():
            raise serializers.ValidationError("Comment content cannot be empty.")
        return value
