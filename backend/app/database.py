"""Supabase client.

The backend always uses the service role key, which bypasses RLS. Never expose
this client's results directly without filtering — the RLS policies that protect
the anon key do not apply here.
"""

from functools import lru_cache

from supabase import Client, create_client

from app.config import settings


@lru_cache
def get_client() -> Client:
    if not settings.supabase_url or not settings.supabase_service_key:
        raise RuntimeError(
            "SUPABASE_URL and SUPABASE_SERVICE_KEY must be set. "
            "Copy backend/.env.example to backend/.env and fill them in."
        )
    return create_client(settings.supabase_url, settings.supabase_service_key)


def db() -> Client:
    """Shorthand used across routers and services."""
    return get_client()
