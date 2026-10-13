# Spec 03: Library REST API with Django REST Framework

## Overview
Build a RESTful web API for a library management system using Django REST Framework (DRF).

## Requirements
- Endpoint `/api/books/`: List books, search by title/author, and create new book records.
- Endpoint `/api/books/<id>/`: Retrieve details, update, or delete a book.
- Endpoint `/api/reservations/`: Allow registered members to reserve or checkout available books.
- Fine calculation endpoint for overdue returns.
- Standard JSON response format and pagination.
