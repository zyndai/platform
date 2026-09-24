"""
Every route must declare who may call it: either a guard dependency from
api/guards.py (or api/auth.get_current_user), or the @public marker.

Walks the mounted app so newly added routers are covered automatically.
Handles both FastAPI layouts: <0.140 copies included routes onto app.routes,
>=0.140 wraps each include in an _IncludedRouter with .original_router.
"""

from __future__ import annotations

from fastapi.routing import APIRoute

from api.auth import get_current_user

# Routes that authenticate inside the handler rather than via a dependency.
# Keep this list empty unless there is a strong reason — prefer @public + a
# comment on the handler.
ALLOWED_WITHOUT_MARKER: set[tuple[str, str]] = set()


def _walk(routes, prefix: str = ""):
    for route in routes:
        if isinstance(route, APIRoute):
            yield prefix + route.path, route
        original = getattr(route, "original_router", None)
        if original is not None:
            context = getattr(route, "include_context", None)
            yield from _walk(original.routes, prefix + (getattr(context, "prefix", "") or ""))


def _dependency_calls(dependant):
    for dep in dependant.dependencies:
        yield dep.call
        yield from _dependency_calls(dep)


def _is_guarded(route: APIRoute) -> bool:
    for call in _dependency_calls(route.dependant):
        if call is get_current_user or getattr(call, "__zynd_guard__", False):
            return True
    return False


def test_every_route_declares_auth():
    import main

    missing = []
    for path, route in _walk(main.app.routes):
        methods = ",".join(sorted(route.methods or []))
        if _is_guarded(route) or getattr(route.endpoint, "__zynd_public__", False):
            continue
        if (methods, path) in ALLOWED_WITHOUT_MARKER:
            continue
        missing.append(f"{methods} {path}")

    assert not missing, "Routes without a guard or @public marker:\n" + "\n".join(sorted(missing))


def test_walk_finds_the_app_routes():
    """Sanity check so the coverage test can't pass vacuously."""
    import main

    paths = {path for path, _ in _walk(main.app.routes)}
    assert "/api/persona/{user_id}/account" in paths
    assert "/api/meetings/pending/{user_id}" in paths
    assert len(paths) > 50
