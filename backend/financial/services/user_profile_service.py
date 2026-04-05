import json
import asyncio
from typing import List, Optional
import asyncpg
from core.logger import get_logger
from financial.crud import get_user_profile, upsert_user_profile
from core.llm_client import ChatAgentClient

logger = get_logger(__name__)

class UserProfileService:
    """
    Manages user financial profiles, risk tolerance, and interests.
    Dynamically updates profiles based on user interactions.
    """

    @staticmethod
    async def get_profile(pool: asyncpg.Pool, user_id: str) -> dict:
        profile = await get_user_profile(pool, user_id)
        if not profile:
            # Return default profile for new users
            return {
                "user_id": user_id,
                "risk_tolerance": "medium",
                "preferred_style": "deep",
                "interests": [],
                "past_queries": [],
                "custom_persona": None
            }
        
        # Parse JSON fields if they are strings
        for field in ["interests", "past_queries"]:
            if isinstance(profile.get(field), str):
                try:
                    profile[field] = json.loads(profile[field])
                except Exception:
                    profile[field] = []
            elif profile.get(field) is None:
                profile[field] = []
            
        return profile

    @staticmethod
    async def update_profile_from_query(pool: asyncpg.Pool, user_id: str, question: str):
        """
        Analyze user query to infer interests, risk tolerance, and expertise level.
        """
        profile = await UserProfileService.get_profile(pool, user_id)
        
        # Optimization: Only update profile if the question is substantial
        if len(question) < 10:
            return

        prompt = f"""
Analyze the following user financial query and update their profile.

Query: "{question}"

Current Profile:
- Risk Tolerance: {profile['risk_tolerance']}
- Interests: {profile['interests']}

Identify:
1. New interests (e.g. "inflation", "tech stocks", "retirement").
2. Changes in risk tolerance (low/medium/high) if the query implies it (e.g. "I'm scared of market crash" -> low).
3. Experience level (beginner/intermediate/advanced).

Respond ONLY with a JSON object:
{{
    "new_interests": ["topic1", "topic2"],
    "inferred_risk_tolerance": "low/medium/high/null",
    "experience_level": "beginner/intermediate/advanced/null"
}}
"""
        try:
            response_str = await ChatAgentClient.generate(
                messages=[{"role": "system", "content": "You are a user profiling agent."},
                          {"role": "user", "content": prompt}],
                temperature=0.1
            )
            
            clean_response = response_str.strip()
            if "```json" in clean_response:
                clean_response = clean_response.split("```json")[1].split("```")[0].strip()
            elif "```" in clean_response:
                clean_response = clean_response.split("```")[1].split("```")[0].strip()
                
            data = json.loads(clean_response)
            
            # Update interests
            current_interests = set(profile.get("interests", []))
            for interest in data.get("new_interests", []):
                current_interests.add(interest.lower().strip())
            profile["interests"] = list(current_interests)
            
            # Update risk tolerance
            inferred_risk = data.get("inferred_risk_tolerance")
            if inferred_risk and inferred_risk in ["low", "medium", "high"]:
                profile["risk_tolerance"] = inferred_risk
            
            # Update experience level (store in a custom metadata or just use it in prompt)
            exp_level = data.get("experience_level")
            if exp_level and exp_level != "null":
                profile["experience_level"] = exp_level
            
            # Add to past queries
            past_queries = profile.get("past_queries", [])
            past_queries.append(question)
            profile["past_queries"] = past_queries[-5:]
            
            await upsert_user_profile(pool, user_id, profile)
            logger.info(f"Updated profile for user {user_id} based on query: {question[:30]}...")
            
        except Exception as e:
            logger.error(f"Failed to update profile for user {user_id}: {e}")

    @staticmethod
    def format_profile_for_prompt(profile: dict) -> str:
        """Format profile data as a natural language block for the LLM system prompt."""
        interests = profile.get("interests", [])
        interests_str = ", ".join(interests) if interests else "None identified yet"
        
        return f"""
[User Profile:
Risk: {profile.get('risk_tolerance', 'medium')}
Style: {profile.get('preferred_style', 'deep')}
Interests: {interests_str}
Experience: {profile.get('experience_level', 'beginner')}
]
"""
