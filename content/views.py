from django.db.models import Q
from django_filters.rest_framework import DjangoFilterBackend
from drf_spectacular.utils import extend_schema, OpenApiParameter
from rest_framework import filters, viewsets
from rest_framework.decorators import action
from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from django.db.models import Prefetch

from content.models import Post, Tag
from content.permissions import CanViewPostDetail
from content.serializers import (
    PostListSerializer,
    PostSerializer,
    TagFilterSerializer,
)
from networking.models import Follow
from user.models import Profile


class PostPagination(PageNumberPagination):
    page_size = 10
    max_page_size = 100


class PostViewSet(viewsets.ModelViewSet):
    """
    API for managing posts.
    - GET    /posts/            -> List accessible posts (others: published only; own: all)
    - GET    /posts/{id}/       -> Retrieve post details
    - POST   /posts/            -> Create a post (draft/scheduled/published)
    - PUT    /posts/{id}/       -> Update own post
    - PATCH  /posts/{id}/       -> Partially update own post
    - DELETE /posts/{id}/       -> Delete own post
    - GET    /posts/my_posts/   -> List current user's posts (all statuses; filterable)
    - POST   /posts/by_tag/     -> List posts by tags (AND/OR) within accessible scope
    """

    queryset = Post.objects.select_related("author__user")
    serializer_class = PostSerializer
    pagination_class = PostPagination
    permission_classes = [IsAuthenticated]
    filter_backends = [
        DjangoFilterBackend,
        filters.SearchFilter,
        filters.OrderingFilter,
    ]
    filterset_fields = ["author", "created_at", "status"]
    search_fields = ["title", "content", "tags__name"]
    ordering_fields = ["created_at", "published_at", "author__full_name"]
    ordering = ["-published_at", "-created_at"]

    def get_permissions(self):
        if self.action in ["update", "partial_update", "destroy", "retrieve"]:
            return [CanViewPostDetail()]
        return [IsAuthenticated()]

    def get_serializer_class(self):
        if self.action == "by_tag":
            return TagFilterSerializer
        if self.action in ["list", "my_posts"]:
            return PostListSerializer

        return PostSerializer

    def perform_create(self, serializer):
        """Automatically identifies the author of the post as the current profile user"""
        profile = getattr(self.request.user, "profile", None)
        if not profile:
            profile = Profile.objects.get(user=self.request.user)
        serializer.save(author=profile)

    def get_queryset(self):
        """
        Access:
        - own posts: any satus
        - oter users posts: only published
        * public profiles
        * privates profiles followers if status == ACCEPTED
        """
        base = Post.objects.select_related("author__user")
        action = getattr(self, "action", None)

        if action in ["list", "by_tag"]:
            me = self.request.user.profile
            return (
                base.filter(status=Post.PostStatus.PUBLISHED)
                .filter(
                    Q(author=me)
                    | Q(
                        author__follower_links__follower=me,
                        author__follower_links__status=Follow.FollowStatus.ACCEPTED,
                    )
                )
                .distinct()
            )

        if action == "my_posts":
            return base.filter(author=self.request.user.profile).prefetch_related(
                Prefetch("tags", queryset=Tag.objects.order_by("name"))
            )

        if action == "retrieve":
            return base.prefetch_related(
                Prefetch("tags", queryset=Tag.objects.order_by("name"))
            )

        return base

    def update(self, request, *args, **kwargs):
        partial = kwargs.pop("partial", False)
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=partial)
        serializer.is_valid(raise_exception=True)
        post = serializer.save()

        post = (
            Post.objects.select_related("author__user")
            .prefetch_related(Prefetch("tags", queryset=Tag.objects.order_by("name")))
            .get(pk=post.pk)
        )

        out = PostSerializer(post, context=self.get_serializer_context())
        return Response(out.data)

    def partial_update(self, request, *args, **kwargs):
        kwargs["partial"] = True
        return self.update(request, *args, **kwargs)

    @extend_schema(
        description="List all posts by the current user. Optional ?status=...",
        parameters=[
            OpenApiParameter(
                name="status",
                description="Filter by status",
                type=str,
                enum=[c for c, _ in Post.PostStatus.choices],
            ),
        ],
        responses={200: PostListSerializer(many=True)},
    )
    @action(detail=False, methods=["get"])
    def my_posts(self, request):
        """List all posts by the current user."""
        queryset = self.get_queryset()
        status_params = request.query_params.get("status")
        if status_params:
            queryset = queryset.filter(status=status_params)
        page = self.paginate_queryset(queryset.order_by("-created_at"))
        serializer = self.get_serializer(page or queryset, many=True)
        return (
            self.get_paginated_response(serializer.data)
            if page is not None
            else Response(serializer.data)
        )

    @extend_schema(
        description="List posts that contain ALL provided tag names (AND).",
        request=TagFilterSerializer,
        responses={200: PostListSerializer(many=True)},
    )
    @action(detail=False, methods=["post"])
    def by_tag(self, request):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        tags = serializer.validated_data["tags"]
        mode = serializer.validated_data["mode"]

        queryset = self.get_queryset()
        if mode == "all":
            for tag in tags:
                queryset = queryset.filter(tags__name__iexact=tag)
        else:
            queryset = queryset.filter(tags__name__in=tags)

        queryset = queryset.distinct()
        page = self.paginate_queryset(queryset)
        output = PostListSerializer(
            page or queryset, many=True, context=self.get_serializer_context()
        )
        return (
            self.get_paginated_response(output.data)
            if page is not None
            else Response(output.data)
        )

    @extend_schema(
        description=(
            "List all accessible posts (others: published only; own: all). "
            "Supports filtering by author, created_at, status; search by title/content/tags; and ordering."
        ),
        parameters=[
            OpenApiParameter(
                name="author", description="Filter by author ID", type=int
            ),
            OpenApiParameter(
                name="created_at",
                description="Filter by creation date (YYYY-MM-DD)",
                type=str,
            ),
            OpenApiParameter(
                name="status",
                description="Filter by post status",
                type=str,
                enum=[c for c, _ in Post.PostStatus.choices],
            ),
            OpenApiParameter(
                name="search",
                description="Search in title, content or tag name",
                type=str,
            ),
            OpenApiParameter(
                name="ordering",
                description="Order by created_at, published_at or author__full_name",
                type=str,
                enum=[
                    "created_at",
                    "-created_at",
                    "published_at",
                    "-published_at",
                    "author__full_name",
                    "-author__full_name",
                ],
            ),
            OpenApiParameter(
                name="page", description="Page number for pagination", type=int
            ),
            OpenApiParameter(
                name="page_size", description="Number of results per page", type=int
            ),
        ],
        responses={200: PostListSerializer(many=True)},
    )
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)
