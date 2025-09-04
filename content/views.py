from django.db import transaction
from django.db.models import Q, F, Exists, OuterRef, Value, BooleanField, Count
from django.utils import timezone
from django_filters.rest_framework import DjangoFilterBackend
from drf_spectacular.utils import extend_schema, OpenApiParameter
from rest_framework import filters, viewsets, status
from rest_framework.exceptions import PermissionDenied
from rest_framework.decorators import action
from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from django.db.models import Prefetch

from content.models import Post, Tag, Like, Comment
from content.permissions import CanViewPostDetail, IsCommentAuthorOrReadOnly
from content.serializers import (
    PostListSerializer,
    PostSerializer,
    TagFilterSerializer,
    CommentListSerializer,
    CommentSerializer,
    CommentUpdateSerializer,
    LikeStatusSerializer,
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
    - GET/POST /posts/{id}/post_comments/ -> List or create comments for a specific post
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
        if self.action == "like":
            return LikeStatusSerializer

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
        me = getattr(self.request.user, "profile", None)

        if action in ["list", "by_tag", "like", "recommended"]:

            queryset = (
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
            return self._annotate_liked(queryset)

        if action == "my_posts":
            queryset = base.filter(author=me).prefetch_related(
                Prefetch("tags", queryset=Tag.objects.order_by("name"))
            )
            return self._annotate_liked(queryset)

        if action == "retrieve":
            queryset = base.prefetch_related(
                Prefetch("tags", queryset=Tag.objects.order_by("name"))
            )
            return queryset

        return base

    def update(self, request, *args, **kwargs):
        partial = kwargs.pop("partial", False)
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=partial)
        serializer.is_valid(raise_exception=True)
        post = serializer.save()

        return Response(
            PostSerializer(post, context=self.get_serializer_context()).data
        )

    def partial_update(self, request, *args, **kwargs):
        kwargs["partial"] = True
        return self.update(request, *args, **kwargs)

    def _annotate_liked(self, qs):
        """Add Bool field liked_by_me to all post"""
        user = self.request.user
        if user.is_authenticated:
            me = user.profile
            subquery = Like.objects.filter(post_id=OuterRef("pk"), user=me)
            return qs.annotate(liked_by_me=Exists(subquery))

        return qs.annotate(liked_by_me=Value(False, output_field=BooleanField()))

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
        """List all posts created by the current user."""
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
        """List post filter by tag names."""
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        tags = serializer.validated_data["tags"]
        mode = serializer.validated_data["mode"]

        queryset = self.get_queryset()

        if mode == "all":

            queryset = (
                queryset.filter(tags__name__in=tags)
                .annotate(tag_matches=Count("tags", filter=Q(tags__name__in=tags)))
                .filter(tag_matches=len(tags))
            )
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

    @action(detail=False, methods=["get"])
    def liked_by_me(self, request):
        """List Posts liked by the current user."""
        me = request.user.profile
        queryset = (
            self.get_queryset()
            .filter(likes__user=me, status=Post.PostStatus.PUBLISHED)
            .distinct()
        )
        page = self.paginate_queryset(queryset)
        ser = PostListSerializer(
            page or queryset, many=True, context=self.get_serializer_context()
        )
        return (
            self.get_paginated_response(ser.data)
            if page is not None
            else Response(ser.data)
        )

    @extend_schema(
        description="Manage post likes",
        methods=["GET"],
        responses={200: LikeStatusSerializer},
        summary="Check if post is liked",
    )
    @extend_schema(
        description="Like the post",
        methods=["PUT"],
        responses={200: LikeStatusSerializer},
        summary="Like post",
    )
    @extend_schema(
        description="Unlike the post",
        methods=["DELETE"],
        responses={200: LikeStatusSerializer},
        summary="Unlike post",
    )
    @action(detail=True, methods=["get", "put", "delete"])
    def like(self, request, pk=None):
        """
        GET - check if user liked the post
        PUT - like the post
        DELETE - unlike the post
        """
        me = request.user.profile
        post = self.get_object()

        if request.method == "GET":
            liked = Like.objects.filter(user=me, post=post).exists()
            return Response({"liked": liked, "likes_count": post.likes_count})

        with transaction.atomic():
            if request.method == "PUT":
                like, created = Like.objects.get_or_create(user=me, post=post)
                if created:
                    Post.objects.filter(pk=post.pk).update(
                        likes_count=F("likes_count") + 1
                    )
                    post.refresh_from_db()

                return Response({"liked": True, "likes_count": post.likes_count})

            else:  # DELETE
                deleted_count = Like.objects.filter(user=me, post=post).delete()[0]
                if deleted_count > 0:
                    Post.objects.filter(pk=post.pk).update(
                        likes_count=F("likes_count") - 1
                    )
                    post.refresh_from_db()

                return Response({"liked": False, "likes_count": post.likes_count})

    @extend_schema(
        description="List recommended posts based on user's liked/commented tags.",
        responses={200: PostListSerializer(many=True)},
    )
    @action(detail=False, methods=["get"])
    def recommended(self, request):
        """Recommend posts based on user's liked/commented."""
        me = request.user.profile
        liked_tags = Tag.objects.filter(
            posts__likes__user=me, posts__status=Post.PostStatus.PUBLISHED
        ).distinct()
        commented_tags = Tag.objects.filter(
            posts__comments__author=me, posts__status=Post.PostStatus.PUBLISHED
        ).distinct()
        tags = (liked_tags | commented_tags).distinct()

        queryset = (
            self.get_queryset()
            .filter(tags__in=tags)
            .order_by("-likes_count", "-created_at")
        ).distinct()
        page = self.paginate_queryset(queryset)
        serializer = PostListSerializer(
            page or queryset, many=True, context=self.get_serializer_context()
        )
        return (
            self.get_paginated_response(serializer.data)
            if page is not None
            else Response(serializer.data)
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


class CommentViewSet(viewsets.ModelViewSet):
    """
    API for managing comments.
    - GET    /comments/         -> List all comments (filtered by post_id if provided)
    - GET    /comments/{id}/    -> Retrieve comment details
    - POST   /comments/         -> Create a new comment (with post_id and optional parent_id)
    - PUT    /comments/{id}/    -> Update a comment (author only)
    - PATCH  /comments/{id}/    -> Partially update a comment (author only)
    - DELETE /comments/{id}/    -> Soft-delete a comment (author only)
    """

    queryset = Comment.objects.select_related("author__user", "author", "post")
    serializer_class = CommentSerializer
    permission_classes = [IsAuthenticated, IsCommentAuthorOrReadOnly]
    filter_backends = [DjangoFilterBackend, filters.OrderingFilter]
    filterset_fields = ["post", "parent"]
    ordering_fields = ["created_at", "updated_at"]
    ordering = ["-created_at"]

    def get_serializer_class(self):
        if self.action == "list":
            return CommentListSerializer
        elif self.action in ["update", "partial_update"]:
            return CommentUpdateSerializer
        return CommentSerializer

    def get_queryset(self):
        """Base queryset: exclude deleted, add annotations"""
        return (
            super()
            .get_queryset()
            .filter(is_deleted=False)
            .annotate(
                children_count=Count("children", filter=Q(children__is_deleted=False))
            )
        )

    def perform_create(self, serializer):
        """Create comment with permission check and counter update"""
        post = serializer.validated_data.get("post")
        if not CanViewPostDetail().has_object_permission(self.request, self, post):
            raise PermissionDenied("You do not have access to this post.")

        with transaction.atomic():
            serializer.save(author=self.request.user.profile)
            Post.objects.filter(pk=post.pk).update(
                comments_count=F("comments_count") + 1
            )

    def perform_update(self, serializer):
        """Update comment"""
        serializer.save()

    def perform_destroy(self, instance):
        """Soft delete comment"""
        with transaction.atomic():
            instance.is_deleted = True
            instance.save(update_fields=["is_deleted"])
            Post.objects.filter(pk=instance.post_id).update(
                comments_count=F("comments_count") - 1
            )

    @action(detail=True, methods=["get"], url_path="children")
    def children(self, request, pk=None):
        """
        Return all direct child comments of a given comment.
        GET /api/comments/{comment_id}/children/
        """
        parent_comment = self.get_object()
        children = parent_comment.children.filter(is_deleted=False).order_by(
            "created_at"
        )

        serializer = self.get_serializer(
            children, many=True, context=self.get_serializer_context()
        )
        return Response(serializer.data, status=status.HTTP_200_OK)

    @extend_schema(
        description=(
            "List all comments, optionally filtered by post_id. "
            "Supports pagination and ordering by created_at or updated_at."
        ),
        parameters=[
            OpenApiParameter(
                name="post",
                description="Filter comments by post ID",
                type=int,
                required=False,
            ),
            OpenApiParameter(
                name="parent",  # Виправив з "parent_id" на "parent"
                description="Filter comments by parent comment ID (null for top-level)",
                type=int,
                required=False,
            ),
            OpenApiParameter(
                name="ordering",
                description="Order by created_at or updated_at",
                type=str,
                enum=["created_at", "-created_at", "updated_at", "-updated_at"],
                required=False,
            ),
            OpenApiParameter(
                name="page",
                description="Page number for pagination",
                type=int,
                required=False,
            ),
            OpenApiParameter(
                name="page_size",
                description="Number of comments per page",
                type=int,
                required=False,
            ),
        ],
        responses={200: CommentListSerializer(many=True)},
    )
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)
