"""Request correlation also propagated by the ASGI threadpool."""
from contextvars import ContextVar

REQUEST_ID: ContextVar[str] = ContextVar("geoqc_request_id", default="-")
