from django.db.models import Q
from django_filters.rest_framework import DjangoFilterBackend
from drf_spectacular.utils import extend_schema, OpenApiParameter
from rest_framework import filters, viewsets
from rest_framework.decorators import action
from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated

from content.models import Post
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
    - GET /posts/ -> List all accessible posts (public or followed private profiles)
    - GET /posts/{id}/ -> Retrieve post details
    - POST /posts/ -> Create a new post
    - PUT /posts/{id}/ -> Update own post
    - PATCH /posts/{id}/ -> Partially update own post
    - DELETE /posts/{id}/ -> Delete own post
    - GET /posts/my_posts/ -> List current user's posts
    - GET /posts/by_tag/ -> List posts by tag
    """

    queryset = Post.objects.select_related("author__user").prefetch_related("tags")
    serializer_class = PostSerializer
    pagination_class = PostPagination
    permission_classes = [IsAuthenticated]
    filter_backends = [
        DjangoFilterBackend,
        filters.SearchFilter,
        filters.OrderingFilter,
    ]
    filterset_fields = ["author", "created_at"]
    search_fields = ["title", "content", "tags__name"]
    ordering_fields = ["created_at", "author__full_name"]

    def get_permissions(self):
        if self.action in ["create", "update", "partial_update", "destroy", "retrieve"]:
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
        """Return posts followers and following users"""
        queryset = super().get_queryset()
        user = self.request.user
        if user.is_authenticated:
            my_profile = user.profile
            queryset = queryset.filter(
                Q(author__is_private=False)
                | Q(author=my_profile)
                | Q(
                    author__follower_links__follower=my_profile,
                    author__follower_links__status=Follow.FollowStatus.ACCEPTED,
                )
            ).distinct()
        else:
            queryset = queryset.filter(author__is_private=False)
        return queryset

    @extend_schema(
        description="List all posts by the current user.",
        responses={200: PostListSerializer(many=True)},
    )
    @action(detail=False, methods=["get"])
    def my_posts(self, request):
        """List all posts by the current user."""
        queryset = self.get_queryset().filter(author=self.request.user.profile)
        serializer = self.get_serializer(queryset, many=True)
        return Response(serializer.data)

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
            for t in tags:
                queryset = queryset.filter(tags__name__iexact=t)
        else:
            queryset = queryset.filter(tags__name__in=tags)

        queryset = queryset.distinct()
        output = PostListSerializer(
            queryset, many=True, context=self.get_serializer_context()
        )
        return Response(output.data)

    @extend_schema(
        description="List all accessible posts (public or followed private profiles). "
        "Supports filtering by author, created_at, search by title content or tags and ordering.",
        parameters=[
            OpenApiParameter(
                name="author", description="Filter by author ID", type=int
            ),
            OpenApiParameter(
                name="created_at",
                description="Filter by creation date (e.g., 2025-08-28)",
                type=str,
            ),
            OpenApiParameter(
                name="search",
                description="Search by title, content or tag name",
                type=str,
            ),
            OpenApiParameter(
                name="ordering",
                description="Order by created_at or author__full_name",
                type=str,
                enum=[
                    "created_at",
                    "-created_at",
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
