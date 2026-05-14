"""Public surface for the explore recommendation service.

Routes and tests should import from this module rather than reaching into
the internal submodules. Internal cross-module helpers (build_reason,
hydrate_components, etc.) are not re-exported on purpose.
"""

from app.services.recommendations.interactions import (
    INTERACTION_WEIGHTS,
    record_interaction,
)
from app.services.recommendations.pipeline import (
    ColdStartRequired,
    DEFAULT_PAGE_SIZE,
    FeedPage,
    get_feed_page,
)
from app.services.recommendations.popular import rank_popular
from app.services.recommendations.profile_builder import (
    invalidate,
    load_profile,
    set_seed_topics,
)

__all__ = [
    "ColdStartRequired",
    "DEFAULT_PAGE_SIZE",
    "FeedPage",
    "INTERACTION_WEIGHTS",
    "get_feed_page",
    "invalidate",
    "load_profile",
    "rank_popular",
    "record_interaction",
    "set_seed_topics",
]
