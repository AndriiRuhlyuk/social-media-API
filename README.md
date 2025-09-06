# social-media-API service

Project Overview

    Social Media API service is web-base for publication own posts and follow another
    users for reading their posts. The service provides full functionality from 
    basic activities social media (posts, comments, likes) to building a network of contacts 
    based on interests (follow / unfollow, accept / reject requests to follow)

# Key Features

    User Profiles: Create and manage user profiles with customizable settings (e.g., privacy, bio, profile picture).
    Content Management: Create, update, and delete posts and comments with tag-based filtering.
    Social Interactions: Follow/unfollow users, accept/reject follow requests, like posts, and comment on content.
    Personalized Recommendations: Recommend posts based on liked or commented tags.
    JWT Authentication: Secure authentication with access and refresh tokens.
    Optimized Queries: Avoid N+1 problems with efficient database queries.
    Advanced Filtering and Pagination: Support for filtering posts, comments, and profiles with pagination.

# Functionalities
User Management

    Users: Register, authenticate, and manage user accounts.
    Profiles: Update profile details, upload profile pictures, and manage privacy settings.
    Authentication: JWT-based authentication with access token (180 minutes) and refresh token (1 day).
    Auto Profile Creation: Profile is automatically created after user registration (via Celery task).
    Token Blacklist Cleanup: Expired refresh tokens are automatically cleaned by a scheduled Celery task.

Content Management

    Posts: Create, schedule, update, and delete posts with tag support and media uploads.
    Scheduled Posts: Posts with status SCHEDULED are automatically published at the scheduled time.
    Rescheduling: Editing a scheduled post cancels the old Celery task and creates a new one.
    Comments: Add, edit, and delete comments with nested replies and spam protection.
    Parent/Child Comments: Support for threaded comments and retrieving children by endpoint.
    Soft Delete: Comments are soft-deleted (hidden instead of being permanently removed).
    Likes: Like and unlike posts with real-time counter updates.
    Tags: Automatic tag extraction from post content for filtering and recommendations.

Social Interactions

    Follow System: Follow public or private profiles, send/accept/reject follow requests.
    Recommendations: Personalized post recommendations based on liked or commented tags.
    Profile Visibility: Restrict post and comment visibility based on follow status and privacy settings.

# Backend

    Django 5.2.4 
    Django REST Framework
    PostgreSQL 16.0 
    JWT - Authentication (180 minutes access, 1 day refresh token)
    Rate Limiting - 100 requests/day for anonymous users, 300/day for users
    Celery -  Asynchronous task processing for scheduled posts and profile creation.

# DevOps

    Docker: Containerization for consistent deployment.
    Docker Compose: Orchestration for local development and testing.
    Alpine Linux: Lightweight base image for Docker containers.

# Documentation
http://127.0.0.1:8000/api/doc/swagger/

    drf-spectacular - OpenAPI/Swagger documentation 
    Debug Toolbar - Development tools (only in DEBUG mode)


# API Endpoints

Basic resources

    GET/POST /api/content/posts/ - List or create posts.
    GET/PUT/DELETE /api/content/posts/{id}/ - Retrieve, update, or delete a post.
    PUT/DELETE /api/content/posts/{id}/like/ - Like or unlike a post.
    GET/POST /api/content/comments/ - List or create comments.
    GET/PUT/DELETE /api/content/comments/{id}/ - Retrieve, update, or delete a comment.
    GET /api/content/comments/{id}/children/ - List child comments.
    GET/POST /api/networking/profiles/ - List profiles or filter by location.
    GET /api/networking/profiles/{id}/ - Retrieve profile details.
    GET/POST /api/networking/profiles/{id}/follow/ - Follow a profile or check follow status.
    POST /api/networking/profiles/{id}/unfollow/ - Unfollow a profile.
    POST /api/networking/profiles/requests/{id}/accept/ - Accept a follow request.
    POST /api/networking/profiles/requests/{id}/reject/ - Reject a follow request.
    GET /api/networking/profiles/my-followers/ - List followers.
    GET /api/networking/profiles/my-following/ - List following.
    GET /api/networking/profiles/my-pending-requests/ - List pending follow requests.   

Special endpoints

    POST /api/user/profile/me/{id}/ - Upload profile picture.
    POST /api/content/posts/{id}/ - Upload post media.
    POST /api/content/posts/by_tag/ - Filter posts by tags.
    GET /api/content/posts/recommended/ - List recommended posts based on liked/commented tags.     

Authentication

    POST /api/user/register/ - Create a new user account.
    POST /api/user/token/ - Obtain JWT access and refresh tokens.
    POST /api/user/refresh/ - Refresh JWT access token.
    GET /api/user/me/ - Retrieve authenticated user details.        

# Installing using GitHub

Clone repository

    git clone https://github.com/your_username/social_media_api_service.git
    cd social_media_api_service

Create and activate virtual env.

    python -m venv venv
    source venv/bin/activate

Install dependencies

    pip install -r requirements.txt

Create .env file

    SECRET_KEY=your_secret_key_here
    DEBUG=True
    
    POSTGRES_DB=your_db_name
    POSTGRES_USER=your_db_user
    POSTGRES_PASSWORD=your_db_password
    POSTGRES_HOST=localhost
    POSTGRES_PORT=5432
    
    CELERY_BROKER_URL=redis://localhost:6379/0
    CELERY_RESULT_BACKEND=redis://localhost:6379/0
    
If DEBUG=False

    ALLOWED_HOSTS=localhost,127.0.0.1,0.0.0.0,social_media

Make migrations

    python manage.py migrate
    python manage.py runserver
    

# Run with docker

Docker should be installed

    docker-compose build
    docker-compose up

# Getting access

    create user via /api/user/register/
    get access token via /api/user/token/

# You can use following superuser (or create another one by yourself):
superuser cred.:

    Email - admin@admin.com
    Password - admin12345

user1 cred.:

    Email - user@user.com
    Password - user12345

user2 cred.:

    Email - user1@user.com
    Password - user112345

# Features

    JWT Authentication: Secure user authentication with access and refresh tokens.
    Admin Panel: Available at /admin/ for superusers.
    API Documentation: Swagger UI at /api/doc/swagger/.
    Profile Management: Update profiles, upload images, and manage privacy settings.
    Content Creation: Create and schedule posts, add comments, and like content.
    Social Interactions: Follow/unfollow users, manage follow requests, and view followers/following.
    Recommendations: Personalized post recommendations based on user interactions (likes/comments).
    Tag-Based Filtering: Filter posts by tags extracted from content.
    Media Uploads: Support for profile pictures and post media.
    Asynchronous Tasks: Use Celery for scheduling posts and creating user profiles.

# DB-structure:
[diagram](https://drive.google.com/file/d/15NTqkU648ATVCS5K7bgpWnTIxXVwezbx/view?usp=sharing):

