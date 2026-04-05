"""
intelligence/agents/user_profiler.py — UserProfilerAgent

Responsibility:
  Transform the raw DB user_profiles row into a structured UserInvestmentProfile
  that every downstream agent can consume without touching the DB.

Inputs:
  - raw profile dict from financial.services.user_profile_service.UserProfileService.get_profile()

Outputs:
  - UserInvestmentProfile (typed, with safe defaults)

Design:
  - Pure transform — no LLM, no DB queries.
  - Always succeeds: missing fields get safe defaults so the pipeline never stalls.
  - Infers time_horizon from experience_level when not explicitly stored.
"""

from __future__ import annotations

from core.logger import get_logger
from intelligence.schemas import UserInvestmentProfile

logger = get_logger(__name__)

# experience → implied time horizon heuristic
_TIME_HORIZON_MAP: dict[str, str] = {
    "beginner":     "medium",
    "intermediate": "medium",
    "expert":       "long",
}


class UserProfilerAgent:
    """
    Converts a raw profile dict → UserInvestmentProfile.
    Always returns a valid object, degrading gracefully on missing data.
    """

    @staticmethod
    def run(raw_profile: dict | None) -> UserInvestmentProfile:
        """
        Build a structured investment profile from the raw DB dict.
        Never raises — returns a safe-default profile on any error.
        """
        if not raw_profile:
            logger.info('{"event": "user_profiler_agent", "status": "no_profile_fallback"}')
            return UserInvestmentProfile(user_id="unknown")

        try:
            user_id = str(raw_profile.get("user_id", "unknown"))
            risk    = _validate_enum(raw_profile.get("risk_tolerance"), ["low", "medium", "high"], "medium")
            exp     = _validate_enum(raw_profile.get("experience_level"), ["beginner", "intermediate", "expert"], "intermediate")
            style   = _validate_enum(raw_profile.get("preferred_style"), ["simple", "deep"], "deep")

            interests = raw_profile.get("interests") or []
            if isinstance(interests, str):
                import json
                try:
                    interests = json.loads(interests)
                except Exception:
                    interests = []
            interests = [str(i).lower().strip() for i in interests if i]

            time_horizon = _TIME_HORIZON_MAP.get(exp, "medium")
            persona      = raw_profile.get("custom_persona") or None

            profile = UserInvestmentProfile(
                user_id=user_id,
                risk_tolerance=risk,
                experience_level=exp,
                preferred_style=style,
                interests=interests,
                time_horizon=time_horizon,
                custom_persona=persona,
            )

            logger.info(
                f'{{"event": "user_profiler_agent", "status": "ok", '
                f'"user_id": "{user_id}", "risk": "{risk}", "exp": "{exp}", '
                f'"interests_count": {len(interests)}}}'
            )
            return profile

        except Exception as exc:
            logger.warning(f'{{"event": "user_profiler_agent", "status": "error", "error": "{exc}"}}')
            uid = str(raw_profile.get("user_id", "unknown"))
            return UserInvestmentProfile(user_id=uid)


# ─────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────

def _validate_enum(value: str | None, allowed: list[str], default: str) -> str:
    if value and str(value).lower() in allowed:
        return str(value).lower()
    return default
