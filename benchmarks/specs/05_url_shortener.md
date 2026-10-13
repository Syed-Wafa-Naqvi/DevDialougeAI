# Spec 05: URL Shortener Service

## Overview
Build a lightweight URL shortening service in Python/Django.

## Requirements
- Input form to submit a long URL and generate a unique 6-character short slug.
- Redirection logic: Accessing `http://host/<short_code>` redirects to original target URL.
- Analytics tracking: Log click count, timestamp, and referrer per short link.
- Dashboard displaying link metrics and total click counts.
