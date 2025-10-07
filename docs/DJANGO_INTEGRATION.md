# 🔧 Django Integration Guide

Simple guide for integrating RelayCache with Django projects

## 📦 Installation

```bash
pip install relaycache
pip install redis  # for Redis backend
```

## ⚙️ Quick Setup

### settings.py

```python
import redis
from custom_cache import RedisCache

# Create Redis client
REDIS_CLIENT = redis.Redis(host='localhost', port=6379, db=0)

# Cache backend configuration
CACHE_BACKEND = RedisCache(REDIS_CLIENT, default_ttl=3600)  # 1 hour default

# For development - use InMemory cache
# from custom_cache import InMemoryCache
# CACHE_BACKEND = InMemoryCache(default_ttl=3600)
```

## 🚀 Basic Usage Examples

### Cache Database Queries

```python
# models.py
from django.db import models

class Book(models.Model):
    title = models.CharField(max_length=255)
    author = models.CharField(max_length=255)
    genre = models.CharField(max_length=100)
    is_featured = models.BooleanField(default=False)

# services.py
from django.conf import settings
from custom_cache import cache

@cache(ttl=1800, backend=settings.CACHE_BACKEND, tags=["books"])
def get_featured_books():
    """Cache featured books for 30 minutes"""
    return list(Book.objects.filter(is_featured=True).values())

@cache(
    ttl=3600, 
    backend=settings.CACHE_BACKEND,
    tags=lambda genre: [f"books:{genre}", "books"],
    key=lambda genre: f"books_by_genre:{genre}"
)
def get_books_by_genre(genre):
    """Cache books by genre with dynamic tags"""
    return list(Book.objects.filter(genre=genre).values())

# views.py
def book_list_view(request):
    featured_books = get_featured_books()
    fiction_books = get_books_by_genre("fiction")
    
    return render(request, 'books.html', {
        'featured_books': featured_books,
        'fiction_books': fiction_books
    })
```

### Cache API Responses

```python
# api/views.py
from rest_framework.decorators import api_view
from rest_framework.response import Response
from django.conf import settings
from custom_cache import cache

@api_view(['GET'])
def book_stats_api(request):
    
    @cache(ttl=7200, backend=settings.CACHE_BACKEND, tags=["stats"])
    def get_book_stats():
        return {
            'total_books': Book.objects.count(),
            'featured_count': Book.objects.filter(is_featured=True).count(),
            'genres_count': Book.objects.values('genre').distinct().count(),
        }
    
    stats = get_book_stats()
    return Response(stats)
```

## 🗑️ Cache Invalidation

### Automatic Invalidation with Signals

```python
# signals.py
from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver
from django.conf import settings
from custom_cache import invalidate
from .models import Book

@receiver([post_save, post_delete], sender=Book)
def invalidate_book_cache(sender, instance, **kwargs):
    """Auto-invalidate cache when books change"""
    tags_to_clear = [
        "books",
        "stats",
        f"books:{instance.genre}"
    ]
    invalidate(tags=tags_to_clear, backend=settings.CACHE_BACKEND)

# Don't forget to register signals in apps.py:
# from django.apps import AppConfig
# 
# class BooksConfig(AppConfig):
#     default_auto_field = 'django.db.models.BigAutoField'
#     name = 'books'
#     
#     def ready(self):
#         import books.signals
```

### Manual Cache Clearing

```python
# utils/cache_utils.py
from django.conf import settings
from custom_cache import invalidate

def clear_book_cache():
    """Clear all book-related cache"""
    invalidate(tags=["books"], backend=settings.CACHE_BACKEND)

def clear_book_stats():
    """Clear book statistics cache"""
    invalidate(tags=["stats"], backend=settings.CACHE_BACKEND)

def clear_genre_cache(genre):
    """Clear cache for specific genre"""
    invalidate(tags=[f"books:{genre}"], backend=settings.CACHE_BACKEND)
```

### Management Command

```python
# management/commands/clear_cache.py
from django.core.management.base import BaseCommand
from django.conf import settings
from custom_cache import invalidate

class Command(BaseCommand):
    help = 'Clear cache by tags'

    def add_arguments(self, parser):
        parser.add_argument('--books', action='store_true', help='Clear book cache')
        parser.add_argument('--stats', action='store_true', help='Clear stats cache')
        parser.add_argument('--all', action='store_true', help='Clear all cache')

    def handle(self, *args, **options):
        backend = settings.CACHE_BACKEND
        
        if options['all']:
            backend.clear()
            self.stdout.write('✅ All cache cleared')
        elif options['books']:
            invalidate(tags=["books"], backend=backend)
            self.stdout.write('✅ Book cache cleared')
        elif options['stats']:
            invalidate(tags=["stats"], backend=backend)
            self.stdout.write('✅ Stats cache cleared')
        else:
            self.stdout.write('❌ Specify --books, --stats, or --all')

# Usage:
# python manage.py clear_cache --books
# python manage.py clear_cache --all
```

## 🎯 Common Patterns

### 1. Cache View Results

```python
from django.conf import settings
from custom_cache import cache

@cache(ttl=1800, backend=settings.CACHE_BACKEND, tags=["homepage"])
def get_homepage_data():
    """Cache expensive homepage data"""
    return {
        'featured_books': Book.objects.filter(is_featured=True)[:5],
        'recent_books': Book.objects.order_by('-id')[:10],
        'popular_genres': Book.objects.values('genre').annotate(
            count=Count('id')
        ).order_by('-count')[:5]
    }

def homepage_view(request):
    data = get_homepage_data()
    return render(request, 'homepage.html', data)
```

### 2. Cache User-Specific Data

```python
@cache(
    ttl=3600,
    backend=settings.CACHE_BACKEND,
    tags=lambda user_id: [f"user:{user_id}", "user_data"],
    key=lambda user_id: f"user_profile:{user_id}"
)
def get_user_profile(user_id):
    """Cache user profile data"""
    return User.objects.select_related('profile').get(id=user_id)

# Clear user cache when profile updates
@receiver(post_save, sender=UserProfile)
def invalidate_user_cache(sender, instance, **kwargs):
    invalidate(
        tags=[f"user:{instance.user_id}"],
        backend=settings.CACHE_BACKEND
    )
```

### 3. Cache Search Results

```python
@cache(
    ttl=900,  # 15 minutes
    backend=settings.CACHE_BACKEND,
    tags=["search"],
    key=lambda query: f"search:{hash(query)}"
)
def search_books(query):
    """Cache search results"""
    return Book.objects.filter(
        title__icontains=query
    ).values('id', 'title', 'author')[:20]

def search_view(request):
    query = request.GET.get('q', '')
    if query:
        results = search_books(query)
        return render(request, 'search.html', {'results': results})
    return render(request, 'search.html')
```

## ⚡ Performance Tips

1. **Use appropriate TTL**: Short for frequently changing data, long for static data
2. **Tag strategically**: Group related cache entries for easy invalidation
3. **Cache at service layer**: Not in views or models
4. **Monitor cache hit rates**: Add logging to track effectiveness

## 🔧 Production Settings

```python
# settings/production.py
import redis
from custom_cache import RedisCache

# Redis with connection pooling
REDIS_CLIENT = redis.Redis(
    host='your-redis-host',
    port=6379,
    db=0,
    max_connections=20,
    socket_timeout=5,
    socket_connect_timeout=5,
    decode_responses=True
)

CACHE_BACKEND = RedisCache(
    REDIS_CLIENT,
    default_ttl=3600,
    value_prefix="myapp:",
    meta_prefix="myapp:meta:"
)
```

---

That's it! RelayCache integrates seamlessly with Django. For more advanced features, check the main [README.md](../README.md).
