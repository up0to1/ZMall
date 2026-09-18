"""Compact, versioned task checkpoints for multi-turn outfit feedback.

The LangGraph state contains runtime-only values such as image bytes, user
profiles and tool results.  Persisting the whole state makes the Redis value
large and couples recovery to transient data.  This module defines the small
logical context that is required to resume a task or fall back to a precise
replacement flow.  The bounded query vector is retained because product-mode
feedback reuses it for deterministic retrieval; the profile is reloaded from
the profile service instead of being copied into the task snapshot.
"""
from copy import deepcopy
from typing import Any, Mapping


CHECKPOINT_SCHEMA_VERSION = 1

# Runtime/rebuildable fields deliberately excluded from Redis checkpoints.
_EXCLUDED_FIELDS = frozenset({
    "user_profile",       # reload from the profile cache/aggregator
    "recent_episodes",    # only needed when a new task starts
    "weather_info",       # refresh on the next workflow round
    "user_photo",         # bytes; reload from the photo session or model URL
    "generated_images",   # bytes; the durable result is stored in MySQL/OSS
    "_main_item_bytes",   # bytes; download the main item again
    "top_candidates_pool",  # reflection-only runtime candidates
})

# Logical fields required for task recovery and precise feedback.  Keeping an
# allow-list prevents newly added runtime fields from silently becoming Redis
# persistence requirements.
_CHECKPOINT_FIELDS = (
    "task_id",
    "user_id",
    "mode",
    "stage",
    "style_tags",
    "scene_desc",
    "photo_session_key",
    "shop_ids",
    "color",
    "color_is_explicit",
    "categories",
    "note",
    "budget_max",
    "season",
    "user_city",
    "user_country",
    "wardrobe_item_ids",
    "wardrobe_item_sources",
    "main_item_ids",
    "user_body_profile_id",
    "system_model_id",
    "system_model_image_url",
    "system_model_gender",
    "target_gender",
    "gender_source",
    "query_text",
    "query_vector",
    "category_constraints",
    "candidate_items_by_category",
    "outfit_candidates",
    "final_outfits",  # 结果 URL/元数据；图片本体仍在 OSS，不写入 Redis
    "history_outfits",
    "seen_item_ids",
    "round",
    "feedback",
    "feedback_parsed",
    "keep_categories",
    "finished",
    "user_dislike_colors",
    "dislike_item_ids",
    "retry_vton_item_ids",
    "want_style_tags",
    "_main_item_info",
    "accepted_outfit_index",
)


def _compact_checkpoint_value(field: str, value: Any) -> Any:
    """Remove oversized inline image payloads while keeping result metadata."""
    compacted = deepcopy(value)
    if field == "final_outfits" and isinstance(compacted, list):
        for outfit in compacted:
            if not isinstance(outfit, dict):
                continue
            result_url = outfit.get("resultUrl")
            if isinstance(result_url, str) and result_url.startswith("data:"):
                # Development fallback may inline the generated image as base64.
                # The durable record/OSS path remains the source of truth.
                outfit["resultUrl"] = None
    return compacted


def build_task_checkpoint(state: Mapping[str, Any], version: int = 0) -> dict[str, Any]:
    """Build a JSON-safe compact checkpoint from a LangGraph state."""
    checkpoint: dict[str, Any] = {
        "checkpoint_schema_version": CHECKPOINT_SCHEMA_VERSION,
        "checkpoint_version": int(version),
    }
    for field in _CHECKPOINT_FIELDS:
        if field in _EXCLUDED_FIELDS or field not in state:
            continue
        value = state[field]
        # JSON serialization below is the final guard, but deepcopy prevents
        # later LangGraph mutations from changing the object being persisted.
        checkpoint[field] = _compact_checkpoint_value(field, value)

    if isinstance(checkpoint.get("seen_item_ids"), set):
        checkpoint["seen_item_ids"] = sorted(checkpoint["seen_item_ids"])

    return checkpoint


def hydrate_task_checkpoint(checkpoint: Mapping[str, Any]) -> dict[str, Any]:
    """Restore in-memory types used by feedback nodes from a checkpoint."""
    state = deepcopy(dict(checkpoint))
    state.setdefault("checkpoint_version", 0)
    if isinstance(state.get("seen_item_ids"), list):
        state["seen_item_ids"] = set(state["seen_item_ids"])
    return state
