# 🔧 Django Integration Guide

Complete guide for integrating RelayCache with Django projects

## 📦 Installation

```bash
pip install relaycache
pip install redis  # for Redis backend
```

## ⚙️ Django Configuration

### settings.py

```python
import redis
from custom_cache import RedisCache, InMemoryCache

# Redis settings
REDIS_HOST = 'localhost'
REDIS_PORT = 6379
REDIS_DB = 0

# Create Redis client
REDIS_CLIENT = redis.Redis(
    host=REDIS_HOST, 
    port=REDIS_PORT, 
    db=REDIS_DB,
    decode_responses=True
)

# Cache backend configuration
CACHE_BACKEND = RedisCache(
    REDIS_CLIENT, 
    default_ttl=3600,  # 1 hour by default
    value_prefix="myapp:",
    meta_prefix="myapp:meta:"
)

# Alternative for development - InMemory cache
# CACHE_BACKEND = InMemoryCache(default_ttl=3600)
```

## 🏗️ Caching Django ORM Queries

### Basic Example with Book Queries

```python
# models.py
from django.db import models

class Book(models.Model):
    title = models.CharField(max_length=255)
    author = models.CharField(max_length=255)
    isbn = models.CharField(max_length=13, unique=True)
    publication_date = models.DateField()
    is_featured = models.BooleanField(default=False)
    
class Genre(models.Model):
    name = models.CharField(max_length=100)
    slug = models.SlugField(unique=True)

class BookGenre(models.Model):
    book = models.ForeignKey(Book, on_delete=models.CASCADE, related_name='genres')
    genre = models.ForeignKey(Genre, on_delete=models.CASCADE)

class Publisher(models.Model):
    name = models.CharField(max_length=255)
    country = models.CharField(max_length=100)

class BookPublisher(models.Model):
    book = models.ForeignKey(Book, on_delete=models.CASCADE, related_name='publishers')
    publisher = models.ForeignKey(Publisher, on_delete=models.CASCADE, related_name='books')
    position = models.IntegerField(default=0)

# views.py or services.py
from django.conf import settings
from django.db.models import Prefetch
from custom_cache import cache
from .models import Book, BookGenre, BookPublisher, Publisher

@cache(
    ttl=1800,  # 30 minutes
    backend=settings.CACHE_BACKEND,
    tags=lambda slug: [f"books_top:{slug}", "books", "book_listings"],
    key=lambda slug: f"books_top:{slug}"
)
def get_books_top(slug):
    """Cache top books by genre slug"""
    return list(
        Book.objects.filter(genres__genre__slug=slug, is_featured=True)
        .prefetch_related(
            Prefetch(
                "publishers", 
                queryset=BookPublisher.objects.select_related("publisher")
            )
        )
        .order_by("publishers__position")
        .values()  # Serialization for cache
    )

@cache(
    ttl=1800,  # 30 minutes
    backend=settings.CACHE_BACKEND,
    tags=lambda slug: [f"books_all:{slug}", "books", "book_listings"],
    key=lambda slug: f"books_all_except:{slug}"
)
def get_books_all_except(slug):
    """Cache all books except specific genre slug"""
    return list(
        Book.objects.exclude(genres__genre__slug=slug)
        .prefetch_related(
            Prefetch(
                "publishers", 
                queryset=BookPublisher.objects.select_related("publisher")
            )
        )
        .order_by("title")
        .values()  # Serialization for cache
    )

# Usage in view
def book_list_view(request, slug):
    books_top = get_books_top(slug)
    books_all = get_books_all_except(slug)
    
    return render(request, 'book_list.html', {
        'books_top': books_top,
        'books_all': books_all
    })
```

### Advanced Caching with Tags

```python
# services/book_service.py
from django.conf import settings
from custom_cache import cache
from typing import List, Dict, Any

class BookService:
    
    @staticmethod
    @cache(
        ttl=3600,
        backend=settings.CACHE_BACKEND,
        tags=lambda book_id: [f"book:{book_id}", "books"],
        distributed_singleflight=True  # Prevents multiple simultaneous requests
    )
    def get_book_details(book_id: int) -> Dict[str, Any]:
        """Detailed book information"""
        try:
            book = Book.objects.select_related(
                'author'
            ).prefetch_related(
                'genres__genre', 'publishers__publisher'
            ).get(id=book_id)
            
            return {
                'id': book.id,
                'title': book.title,
                'author': book.author,
                'isbn': book.isbn,
                'genres': [bg.genre.name for bg in book.genres.all()],
                'publishers': [bp.publisher.name for bp in book.publishers.all()],
                'publication_date': book.publication_date.isoformat() if book.publication_date else None,
            }
        except Book.DoesNotExist:
            return None
    
    @staticmethod
    @cache(
        ttl=7200,  # 2 hours
        backend=settings.CACHE_BACKEND,
        tags=lambda: ["book_stats", "analytics"],
        key=lambda: "book_global_stats"
    )
    def get_book_statistics() -> Dict[str, int]:
        """Global book statistics"""
        return {
            'total_books': Book.objects.count(),
            'featured_books': Book.objects.filter(is_featured=True).count(),
            'recent_books': Book.objects.filter(
                publication_date__year=2024
            ).count(),
        }
```

## 🗑️ Cache Invalidation

### Automatic Invalidation via Django Signals

```python
# signals.py
from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver
from django.conf import settings
from custom_cache import invalidate
from .models import Book, BookGenre, BookPublisher

@receiver(post_save, sender=Book)
def invalidate_book_cache(sender, instance, created, **kwargs):
    """Invalidate cache when book changes"""
    tags_to_invalidate = [
        f"book:{instance.id}",
        "books",
        "book_listings",
        "book_stats"
    ]
    
    # If book has genres, invalidate those caches too
    for book_genre in instance.genres.all():
        slug = book_genre.genre.slug
        tags_to_invalidate.extend([
            f"books_top:{slug}",
            f"books_all:{slug}"
        ])
    
    invalidate(tags=tags_to_invalidate, backend=settings.CACHE_BACKEND)

@receiver(post_delete, sender=Book)
def invalidate_book_cache_on_delete(sender, instance, **kwargs):
    """Invalidate cache when book is deleted"""
    invalidate(
        tags=["books", "book_listings", "book_stats"],
        backend=settings.CACHE_BACKEND
    )

@receiver(post_save, sender=BookGenre)
def invalidate_book_genre_cache(sender, instance, **kwargs):
    """Invalidate when book-genre relationship changes"""
    tags_to_invalidate = [
        f"book:{instance.book.id}",
        f"books_top:{instance.genre.slug}",
        f"books_all:{instance.genre.slug}",
        "books", "book_listings"
    ]
    invalidate(tags=tags_to_invalidate, backend=settings.CACHE_BACKEND)

@receiver(post_save, sender=BookPublisher)
def invalidate_book_publisher_cache(sender, instance, **kwargs):
    """Invalidate when book-publisher relationship changes"""
    invalidate(
        tags=[f"book:{instance.book.id}", "books", "book_listings"],
        backend=settings.CACHE_BACKEND
    )
```

### Manual Tag-based Invalidation

```python
# management/commands/clear_book_cache.py
from django.core.management.base import BaseCommand
from django.conf import settings
from custom_cache import invalidate

class Command(BaseCommand):
    help = 'Clear book cache'

    def add_arguments(self, parser):
        parser.add_argument(
            '--tag',
            type=str,
            help='Clear cache by specific tag'
        )
        parser.add_argument(
            '--all-books',
            action='store_true',
            help='Clear all book cache'
        )

    def handle(self, *args, **options):
        backend = settings.CACHE_BACKEND
        
        if options['all_books']:
            invalidate(tags=["books"], backend=backend)
            self.stdout.write(
                self.style.SUCCESS('All book cache cleared')
            )
        elif options['tag']:
            invalidate(tags=[options['tag']], backend=backend)
            self.stdout.write(
                self.style.SUCCESS(f'Cache with tag "{options["tag"]}" cleared')
            )
        else:
            self.stdout.write(
                self.style.ERROR('Specify --tag or --all-books')
            )

# Usage:
# python manage.py clear_book_cache --tag "books"
# python manage.py clear_book_cache --all-books
```

## 🎯 Cache Clearing by Tags

### Programmatic Clearing

```python
from django.conf import settings
from custom_cache import invalidate

# Clear specific book
def clear_book_cache(book_id):
    invalidate(
        tags=[f"book:{book_id}"],
        backend=settings.CACHE_BACKEND
    )

# Clear all books
def clear_all_book_cache():
    invalidate(
        tags=["books"],
        backend=settings.CACHE_BACKEND
    )

# Clear by genre slug
def clear_books_by_genre(slug):
    invalidate(
        tags=[f"books_top:{slug}", f"books_all:{slug}"],
        backend=settings.CACHE_BACKEND
    )

# Clear statistics
def clear_book_stats():
    invalidate(
        tags=["book_stats", "analytics"],
        backend=settings.CACHE_BACKEND
    )
```

### API Endpoint for Cache Clearing

```python
# views.py
from django.http import JsonResponse
from django.views.decorators.http import require_POST
from django.contrib.admin.views.decorators import staff_member_required
from django.conf import settings
from custom_cache import invalidate

@require_POST
@staff_member_required
def clear_cache_api(request):
    """API for cache clearing (admin only)"""
    cache_type = request.POST.get('cache_type')
    
    if cache_type == 'books':
        invalidate(tags=["books"], backend=settings.CACHE_BACKEND)
        return JsonResponse({'status': 'success', 'message': 'Book cache cleared'})
    
    elif cache_type == 'stats':
        invalidate(tags=["book_stats"], backend=settings.CACHE_BACKEND)
        return JsonResponse({'status': 'success', 'message': 'Stats cache cleared'})
    
    elif cache_type == 'all':
        # Clear all cache
        settings.CACHE_BACKEND.clear()
        return JsonResponse({'status': 'success', 'message': 'All cache cleared'})
    
    else:
        return JsonResponse({'status': 'error', 'message': 'Invalid cache_type'})

# urls.py
urlpatterns = [
    path('admin/clear-cache/', clear_cache_api, name='clear_cache_api'),
]
```

## 🔧 Useful Utilities

### View Caching Decorator

```python
# utils/cache_utils.py
from functools import wraps
from django.conf import settings
from custom_cache import cache

def cache_view(ttl=3600, tags=None, key_func=None):
    """Decorator for caching Django views"""
    def decorator(view_func):
        @wraps(view_func)
        def wrapper(request, *args, **kwargs):
            # Generate key based on URL and parameters
            if key_func:
                cache_key = key_func(request, *args, **kwargs)
            else:
                cache_key = f"view:{request.path}:{hash(str(sorted(request.GET.items())))}"
            
            # Generate tags
            if callable(tags):
                cache_tags = tags(request, *args, **kwargs)
            else:
                cache_tags = tags or []
            
            @cache(
                ttl=ttl,
                backend=settings.CACHE_BACKEND,
                tags=cache_tags,
                key=lambda: cache_key
            )
            def cached_view():
                return view_func(request, *args, **kwargs)
            
            return cached_view()
        return wrapper
    return decorator

# Usage:
@cache_view(
    ttl=1800,
    tags=lambda request, slug: [f"book_page:{slug}", "book_pages"],
    key_func=lambda request, slug: f"book_list:{slug}"
)
def book_list_view(request, slug):
    # your view logic
    pass
```

## 📊 Cache Monitoring

```python
# management/commands/cache_stats.py
from django.conf import settings
from django.core.management.base import BaseCommand

class Command(BaseCommand):
    help = 'Cache usage statistics'

    def handle(self, *args, **options):
        backend = settings.CACHE_BACKEND
        
        if hasattr(backend, 'redis_client'):
            # Redis statistics
            info = backend.redis_client.info()
            self.stdout.write(f"Redis memory used: {info.get('used_memory_human')}")
            self.stdout.write(f"Total keys: {backend.redis_client.dbsize()}")
            
            # Search keys by pattern
            book_keys = backend.redis_client.keys("*book*")
            self.stdout.write(f"Book-related keys: {len(book_keys)}")
```

## 🚀 Real-world Usage Examples

### Book Search with Caching

```python
# services/search_service.py
from django.conf import settings
from custom_cache import cache
from django.db.models import Q

class BookSearchService:
    
    @staticmethod
    @cache(
        ttl=900,  # 15 minutes
        backend=settings.CACHE_BACKEND,
        tags=lambda query, genre=None: [
            f"search:{hash(query)}", 
            "book_search",
            f"genre:{genre}" if genre else "all_genres"
        ],
        key=lambda query, genre=None: f"search:{hash(query)}:genre:{genre or 'all'}"
    )
    def search_books(query: str, genre: str = None) -> List[Dict]:
        """Search books with caching"""
        qs = Book.objects.select_related('author').prefetch_related('genres__genre')
        
        # Text search
        qs = qs.filter(
            Q(title__icontains=query) | 
            Q(author__icontains=query) |
            Q(isbn__icontains=query)
        )
        
        # Genre filter
        if genre:
            qs = qs.filter(genres__genre__slug=genre)
        
        return list(qs.values(
            'id', 'title', 'author', 'isbn', 'publication_date'
        )[:50])  # Limit results

# Usage in API view
from rest_framework.decorators import api_view
from rest_framework.response import Response

@api_view(['GET'])
def book_search_api(request):
    query = request.GET.get('q', '')
    genre = request.GET.get('genre')
    
    if not query:
        return Response({'error': 'Query parameter required'}, status=400)
    
    results = BookSearchService.search_books(query, genre)
    return Response({'books': results})
```

### Paginated Book List with Caching

```python
# views.py
from django.core.paginator import Paginator
from django.conf import settings
from custom_cache import cache

@cache(
    ttl=1800,
    backend=settings.CACHE_BACKEND,
    tags=lambda page=1, genre=None: [
        f"books_page:{page}",
        f"genre:{genre}" if genre else "all_genres",
        "book_listings"
    ],
    key=lambda page=1, genre=None: f"books:page:{page}:genre:{genre or 'all'}"
)
def get_paginated_books(page=1, genre=None):
    """Get paginated book list with caching"""
    qs = Book.objects.select_related('author').prefetch_related('genres__genre')
    
    if genre:
        qs = qs.filter(genres__genre__slug=genre)
    
    qs = qs.order_by('-publication_date', 'title')
    
    paginator = Paginator(qs, 20)  # 20 books per page
    page_obj = paginator.get_page(page)
    
    return {
        'books': list(page_obj.object_list.values()),
        'has_next': page_obj.has_next(),
        'has_previous': page_obj.has_previous(),
        'num_pages': paginator.num_pages,
        'current_page': page
    }

def book_list_view(request):
    page = request.GET.get('page', 1)
    genre = request.GET.get('genre')
    
    data = get_paginated_books(page, genre)
    
    return render(request, 'books/list.html', data)
```

This guide demonstrates how to effectively use RelayCache in Django projects for caching ORM queries and managing cache through tags with book-related examples.
