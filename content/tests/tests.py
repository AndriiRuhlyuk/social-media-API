import os
import tempfile
from PIL import Image
from django.test import TestCase
from django.contrib.auth import get_user_model
from rest_framework import status
from rest_framework.test import APIClient
from rest_framework.reverse import reverse

from django.utils import timezone
from datetime import timedelta

from content.models import Post, Tag, Comment, Like
from content.serializers import (
    PostListSerializer,
    PostSerializer,
    CommentListSerializer,
    CommentSerializer,
)
from user.models import Profile
from networking.models import Follow
from content.tasks import publish_post


POST_URL = reverse("content:posts-list")
COMMENT_URL = reverse("content:comments-list")
RECOMMENDED_URL = reverse("content:posts-recommended")


def sample_user(**params):
    """Create and return a sample user."""
    defaults = {
        "email": "test@example.com",
        "password": "testpassword123",
    }
    defaults.update(params)
    return get_user_model().objects.create_user(**defaults)


def sample_profile(user=None, **params):
    """Create and return a sample profile."""
    if user is None:
        user = sample_user()
    defaults = {
        "user": user,
        "first_name": "Test",
        "last_name": "User",
        "is_private": False,
    }
    defaults.update(params)
    return Profile.objects.create(**defaults)


def sample_tag(**params):
    """Create and return a sample tag."""
    defaults = {"name": "testtag"}
    defaults.update(params)
    return Tag.objects.create(**defaults)


def sample_post(author=None, **params):
    """Create and return a sample post."""
    if author is None:
        author = sample_profile()

    base_title = params.pop("title", "Test Post")
    unique_title = base_title
    i = 1
    while Post.objects.filter(author=author, title=unique_title).exists():
        i += 1
        unique_title = f"{base_title} ({i})"

    defaults = {
        "author": author,
        "title": unique_title,
        "content": "Test content #testtag",
        "status": Post.PostStatus.PUBLISHED,
        "published_at": timezone.now(),
    }
    defaults.update(params)

    status_value = defaults.get("status")
    if status_value == Post.PostStatus.PUBLISHED:
        defaults["scheduled_at"] = None
        defaults.setdefault("published_at", timezone.now())
    elif status_value == Post.PostStatus.SCHEDULED:
        defaults["published_at"] = None
        defaults.setdefault("scheduled_at", timezone.now() + timedelta(hours=1))
    else:
        defaults["published_at"] = None
        defaults["scheduled_at"] = None

    return Post.objects.create(**defaults)


def sample_comment(post=None, author=None, **params):
    """Create and return a sample comment."""
    if post is None:
        post = sample_post()
    if author is None:
        author = post.author
    defaults = {
        "post": post,
        "author": author,
        "content": "Test comment",
    }
    defaults.update(params)
    return Comment.objects.create(**defaults)


def post_detail_url(post_id):
    """Return URL for post detail and update."""
    return reverse("content:posts-detail", args=[post_id])


def comment_detail_url(comment_id):
    """Return URL for comment detail."""
    return reverse("content:comments-detail", args=[comment_id])


def post_like_url(post_id):
    """Return URL for post like."""
    return reverse("content:posts-like", args=[post_id])


def comment_children_url(comment_id):
    """Return URL for comment children."""
    return reverse("content:comments-children", args=[comment_id])


class UnauthenticatedContentApiTests(TestCase):
    def setUp(self):
        self.client = APIClient()

    def test_posts_list_unauthorized(self):
        """Test that posts list requires authentication."""
        res = self.client.get(POST_URL)
        self.assertEqual(res.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_comments_list_unauthorized(self):
        """Test that comments list requires authentication."""
        res = self.client.get(COMMENT_URL)
        self.assertEqual(res.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_recommended_unauthorized(self):
        """Test that recommended posts require authentication."""
        res = self.client.get(RECOMMENDED_URL)
        self.assertEqual(res.status_code, status.HTTP_401_UNAUTHORIZED)


class AuthenticatedContentApiTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = sample_user(email="test@test.com")
        self.profile = sample_profile(user=self.user)
        self.client.force_authenticate(user=self.user)

    def tearDown(self):
        """Clean up uploaded files."""
        for post in Post.objects.all():
            if post.media:
                post.media.delete()

    def test_create_post(self):
        """Test creating a post."""
        payload = {
            "title": "New Post",
            "content": "New content #newtag",
            "status": Post.PostStatus.PUBLISHED,
        }
        res = self.client.post(POST_URL, payload)
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)
        post = Post.objects.get(id=res.data["id"])
        self.assertEqual(post.title, payload["title"])
        self.assertEqual(post.author, self.profile)
        self.assertTrue(Tag.objects.filter(name="newtag").exists())
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.posts_count, 1)

    def test_create_scheduled_post(self):
        scheduled_at = timezone.now() + timedelta(hours=1)
        payload = {
            "title": "Scheduled Post",
            "content": "Scheduled content",
            "status": Post.PostStatus.SCHEDULED,
            "scheduled_at": scheduled_at,
        }

        with self.captureOnCommitCallbacks(execute=True):
            res = self.client.post(POST_URL, payload)

        self.assertEqual(res.status_code, status.HTTP_201_CREATED)
        post = Post.objects.get(id=res.data["id"])
        self.assertIsNotNone(post.scheduled_task_id)

    def test_publish_scheduled_post(self):
        """Test publishing a scheduled post via Celery."""
        post = sample_post(
            author=self.profile,
            status=Post.PostStatus.SCHEDULED,
            scheduled_at=timezone.now() - timedelta(hours=1),
        )
        publish_post.apply(args=[post.id])
        post.refresh_from_db()
        self.assertEqual(post.status, Post.PostStatus.PUBLISHED)
        self.assertIsNotNone(post.published_at)
        self.assertIsNone(post.scheduled_at)
        self.assertIsNone(post.scheduled_task_id)
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.posts_count, 1)

    def test_delete_scheduled_post(self):
        """Test deleting a scheduled post revokes Celery task."""
        post = sample_post(
            author=self.profile,
            status=Post.PostStatus.SCHEDULED,
            scheduled_at=timezone.now() + timedelta(hours=1),
            scheduled_task_id="test-task-id",
        )
        url = post_detail_url(post.id)
        res = self.client.delete(url)
        self.assertEqual(res.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(Post.objects.filter(id=post.id).exists())

    def test_create_post_invalid_scheduled_at(self):
        """Test creating a post with invalid scheduled_at fails."""
        payload = {
            "title": "Invalid Post",
            "content": "Invalid content",
            "status": Post.PostStatus.SCHEDULED,
            "scheduled_at": timezone.now() - timedelta(hours=1),
        }
        res = self.client.post(POST_URL, payload)
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("scheduled_at", res.data)

    def test_list_posts(self):
        """Test listing posts."""
        post = sample_post(author=self.profile)
        res = self.client.get(POST_URL)
        setattr(post, "liked_by_me", False)
        serializer = PostListSerializer(
            [post], many=True, context={"request": res.wsgi_request}
        )
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(res.data["results"], serializer.data)

    def test_filter_posts_by_tag(self):
        """Test filtering posts by tags."""
        tag = sample_tag(name="filtertag")
        post = sample_post(author=self.profile)
        post.tags.add(tag)
        payload = {"tags": "filtertag", "mode": "all"}
        setattr(post, "liked_by_me", False)
        res = self.client.post(reverse("content:posts-by-tag"), payload)
        serializer = PostListSerializer(
            [post], many=True, context={"request": res.wsgi_request}
        )
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(res.data["results"], serializer.data)

    def test_post_detail(self):
        """Test retrieving post details."""
        post = sample_post(author=self.profile)
        url = post_detail_url(post.id)
        res = self.client.get(url)
        serializer = PostSerializer(post)
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(res.data, serializer.data)

    def test_post_detail_not_followed(self):
        """Test retrieving post details when not following author."""
        other_user = sample_user(email="other@test.com")
        other_profile = sample_profile(user=other_user)
        post = sample_post(author=other_profile)
        url = post_detail_url(post.id)
        res = self.client.get(url)
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)

    def test_post_detail_followed(self):
        """Test retrieving post details when following author."""
        other_user = sample_user(email="other@test.com")
        other_profile = sample_profile(user=other_user)
        Follow.objects.create(
            follower=self.profile,
            following=other_profile,
            status=Follow.FollowStatus.ACCEPTED,
        )
        post = sample_post(author=other_profile)
        url = post_detail_url(post.id)
        res = self.client.get(url)
        serializer = PostSerializer(post)
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(res.data, serializer.data)

    def test_update_own_post(self):
        """Test updating own post."""
        post = sample_post(author=self.profile)
        payload = {"title": "Updated Post", "content": "Updated content"}
        url = post_detail_url(post.id)
        res = self.client.put(url, payload)
        post.refresh_from_db()
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(post.title, payload["title"])

    def test_delete_own_post(self):
        """Test deleting own post."""
        post = sample_post(author=self.profile)
        url = post_detail_url(post.id)
        res = self.client.delete(url)
        self.assertEqual(res.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(Post.objects.filter(id=post.id).exists())

    def test_upload_post_image(self):
        """Test uploading an image to a post via POST to post detail."""
        post = sample_post(author=self.profile)
        url = post_detail_url(post.id)
        with tempfile.NamedTemporaryFile(suffix=".jpg") as ntf:
            img = Image.new("RGB", (10, 10))
            img.save(ntf, format="JPEG")
            ntf.seek(0)
            res = self.client.patch(url, {"media": ntf}, format="multipart")
        post.refresh_from_db()
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertIn("media", res.data)
        self.assertTrue(os.path.exists(post.media.path))

    def test_upload_invalid_image(self):
        """Test uploading an invalid image via POST to post detail fails."""
        post = sample_post(author=self.profile)
        url = post_detail_url(post.id)
        res = self.client.patch(url, {"media": "not image"}, format="multipart")
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)

    def test_like_post(self):
        """Test liking a post."""
        post = sample_post(author=self.profile)
        url = post_like_url(post.id)
        res = self.client.put(url)
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertTrue(res.data["liked"])
        post.refresh_from_db()
        self.assertEqual(post.likes_count, 1)
        self.assertTrue(Like.objects.filter(user=self.profile, post=post).exists())

    def test_unlike_post(self):
        """Test unliking a post."""
        post = sample_post(author=self.profile)
        url = post_like_url(post.id)
        self.client.put(url)
        res = self.client.delete(url)
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertFalse(res.data["liked"])
        post.refresh_from_db()
        self.assertEqual(post.likes_count, 0)

    def test_create_comment(self):
        """Test creating a comment."""
        post = sample_post(author=self.profile)
        payload = {"post_id": post.id, "content": "New comment"}
        res = self.client.post(COMMENT_URL, payload)
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)
        comment = Comment.objects.get(id=res.data["id"])
        self.assertEqual(comment.content, payload["content"])
        post.refresh_from_db()
        self.assertEqual(post.comments_count, 1)

    def test_create_comment_spam_protection(self):
        """Test spam protection for comments."""
        post = sample_post(author=self.profile)
        sample_comment(post=post, author=self.profile)
        payload = {"post_id": post.id, "content": "Spammy comment"}
        res = self.client.post(COMMENT_URL, payload)
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("non_field_errors", res.data)

    def test_update_own_comment(self):
        """Test updating own comment."""
        post = sample_post(author=self.profile)
        comment = sample_comment(post=post, author=self.profile)
        url = comment_detail_url(comment.id)
        payload = {"content": "Updated comment"}
        res = self.client.put(url, payload)
        comment.refresh_from_db()
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(comment.content, payload["content"])

    def test_update_not_own_comment(self):
        """Test updating someone else's comment fails."""
        other_user = sample_user(email="other@test.com")
        other_profile = sample_profile(user=other_user)
        post = sample_post(author=self.profile)
        comment = sample_comment(post=post, author=other_profile)
        url = comment_detail_url(comment.id)
        payload = {"content": "Updated comment"}
        res = self.client.put(url, payload)
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)

    def test_delete_own_comment(self):
        """Test deleting own comment."""
        post = sample_post(author=self.profile)

        create_payload = {"post_id": post.id, "content": "Test comment"}
        create_res = self.client.post(COMMENT_URL, create_payload)
        self.assertEqual(create_res.status_code, status.HTTP_201_CREATED)
        comment_id = create_res.data["id"]
        url = comment_detail_url(comment_id)
        res = self.client.delete(url)
        self.assertEqual(res.status_code, status.HTTP_204_NO_CONTENT)
        comment = Comment.objects.get(id=comment_id)
        self.assertTrue(comment.is_deleted)

        post.refresh_from_db()
        self.assertEqual(post.comments_count, 0)

    def test_delete_not_own_comment(self):
        """Test deleting someone else's comment fails."""
        other_user = sample_user(email="other@test.com")
        other_profile = sample_profile(user=other_user)
        post = sample_post(author=self.profile)
        comment = sample_comment(post=post, author=other_profile)
        url = comment_detail_url(comment.id)
        res = self.client.delete(url)
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)

    def test_list_comments_no_followers(self):
        """Test listing comments when user has no followers or followings."""
        other_user = sample_user(email="other@test.com")
        other_profile = sample_profile(user=other_user)
        post = sample_post(author=self.profile)
        other_post = sample_post(author=other_profile)

        comment_own = sample_comment(post=post, author=self.profile)
        sample_comment(post=other_post, author=other_profile)
        res = self.client.get(COMMENT_URL)
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        setattr(comment_own, "children_count", 0)
        serializer = CommentListSerializer(
            [comment_own], many=True, context={"request": res.wsgi_request}
        )
        self.assertEqual(res.data["results"], serializer.data)

    def test_list_comments_followed(self):
        """Test listing comments when following post author."""
        other_user = sample_user(email="other@test.com")
        other_profile = sample_profile(user=other_user)
        Follow.objects.create(
            follower=self.profile,
            following=other_profile,
            status=Follow.FollowStatus.ACCEPTED,
        )
        post = sample_post(author=self.profile)
        other_post = sample_post(author=other_profile)
        comment_own = sample_comment(post=post, author=self.profile)
        comment_followed = sample_comment(post=other_post, author=other_profile)
        res = self.client.get(COMMENT_URL)
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        setattr(comment_own, "children_count", 0)
        setattr(comment_followed, "children_count", 0)
        expected = CommentListSerializer(
            [comment_followed, comment_own],
            many=True,
            context={"request": res.wsgi_request},
        ).data

        self.assertEqual(res.data["results"], expected)

    def test_comment_children(self):
        """Test retrieving child comments for own comment."""
        post = sample_post(author=self.profile)
        parent_comment = sample_comment(post=post, author=self.profile)
        child_comment = sample_comment(
            post=post, author=self.profile, parent=parent_comment
        )
        url = comment_children_url(parent_comment.id)
        res = self.client.get(url)
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        serializer = CommentSerializer(
            [child_comment], many=True, context={"request": res.wsgi_request}
        )

        self.assertEqual(res.data, serializer.data)

    def test_recommended_posts_liked(self):
        """Test recommended posts based on liked tags."""
        tag = sample_tag(name="likedtag")
        post = sample_post(author=self.profile)
        post.tags.add(tag)
        Like.objects.create(user=self.profile, post=post)
        other_post = sample_post(author=self.profile, content="Another post #likedtag")
        other_post.tags.add(tag)

        res = self.client.get(RECOMMENDED_URL)

        setattr(post, "liked_by_me", True)
        setattr(other_post, "liked_by_me", False)

        serializer = PostListSerializer(
            [post, other_post], many=True, context={"request": res.wsgi_request}
        )
        res_data_sorted = sorted(res.data["results"], key=lambda x: x["id"])
        serializer_data_sorted = sorted(serializer.data, key=lambda x: x["id"])
        self.assertEqual(res_data_sorted, serializer_data_sorted)

    def test_recommended_posts_commented(self):
        """Test recommended posts based on commented tags."""
        tag = sample_tag(name="commentedtag")
        post = sample_post(author=self.profile)
        post.tags.add(tag)
        sample_comment(post=post, author=self.profile)
        other_post = sample_post(
            author=self.profile, content="Another post #commentedtag"
        )
        other_post.tags.add(tag)
        res = self.client.get(RECOMMENDED_URL)
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        setattr(post, "liked_by_me", False)
        setattr(other_post, "liked_by_me", False)

        serializer = PostListSerializer(
            [post, other_post], many=True, context={"request": res.wsgi_request}
        )
        res_data_sorted = sorted(res.data["results"], key=lambda x: x["id"])
        serializer_data_sorted = sorted(serializer.data, key=lambda x: x["id"])
        self.assertEqual(res_data_sorted, serializer_data_sorted)

    def test_recommended_posts_no_tags(self):
        """Test recommended posts when no liked or commented tags."""
        post = sample_post(author=self.profile)
        Like.objects.create(user=self.profile, post=post)
        res = self.client.get(RECOMMENDED_URL)
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertTrue(len(res.data["results"]) <= 10)
