from rest_framework import serializers
from rest_framework.reverse import reverse

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
        import re

        parts = [p.strip() for p in re.split(r"[,\s]+", value) if p.strip()]
        return list(dict.fromkeys(map(str.lower, parts)))


class PostSerializer(serializers.ModelSerializer):
    """Post serializer (Retrieve, Update, Delete, Create)"""

    author_full_name = serializers.CharField(source="author.full_name", read_only=True)
    tags_display = TagSerializer(source="tags", many=True, read_only=True)

    class Meta:
        model = Post
        fields = [
            "id",
            "title",
            "author_full_name",
            "content",
            "media",
            "tags_display",
            "created_at",
            "updated_at",
        ]

    def validate_content(self, value):
        """Extract hashtags from content and store in context."""
        if "#" in value:
            tags = re.findall(r"#(\w+)", value)
            self.context["extracted_tags"] = [tag.lower() for tag in tags]
        return value

    def create(self, validated_data):
        """Create post with tags from content."""
        tags_data = self.context.get("extracted_tags", [])
        existing_tags = Tag.objects.filter(name__in=[tag.lower() for tag in tags_data])
        existing_tag_names = set(existing_tags.values_list("name", flat=True))
        new_tags = [
            Tag(name=tag_name.lower())
            for tag_name in tags_data
            if tag_name.lower() not in existing_tag_names
        ]
        if new_tags:
            Tag.objects.bulk_create(new_tags)
        tags = list(existing_tags) + [
            Tag.objects.get(name=tag_name.lower())
            for tag_name in tags_data
            if tag_name.lower() not in existing_tag_names
        ]
        post = super().create(validated_data)
        post.tags.add(*tags)
        return post

    def update(self, instance, validated_data):
        """Update post and its tags from content."""
        tags_data = self.context.get("extracted_tags", [])
        post = super().update(self.instance, validated_data)
        if tags_data:
            post.tags.clear()
            existing_tags = Tag.objects.filter(
                name__in=[tag.lower() for tag in tags_data]
            )
            existing_tag_names = set(existing_tags.values_list("name", flat=True))
            new_tags = [
                Tag(name=tag_name.lower())
                for tag_name in tags_data
                if tag_name.lower() not in existing_tag_names
            ]
            if new_tags:
                Tag.objects.bulk_create(new_tags)
            tags = list(existing_tags) + [
                Tag.objects.get(name=tag_name.lower())
                for tag_name in tags_data
                if tag_name.lower() not in existing_tag_names
            ]
            post.tags.add(*tags)
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
        ]

    def get_detail(self, obj):
        request = self.context.get("request")
        return reverse("content:posts-detail", kwargs={"pk": obj.pk}, request=request)
