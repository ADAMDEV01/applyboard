from slowapi import Limiter
from slowapi.util import get_remote_address

from app.core.config import RATE_LIMIT_STORAGE_URI

# Configure Redis for shared limits when running multiple workers/instances.
limiter = Limiter(
    key_func=get_remote_address,
    storage_uri=RATE_LIMIT_STORAGE_URI,
)
