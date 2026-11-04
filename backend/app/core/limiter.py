import os

from slowapi import Limiter
from slowapi.util import get_remote_address

# Configure Redis for shared limits when running multiple workers/instances.
limiter = Limiter(
    key_func=get_remote_address,
    storage_uri=os.getenv("RATE_LIMIT_STORAGE_URI", "memory://"),
)
