import json

import httpx

from src.config import settings
from src.models import GradeResult

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"


async def call_openrouter(
    messages: list[dict],
    model: str | None = None,
    json_mode: bool = False,
) -> str:
    headers = {
        "Authorization": f"Bearer {settings.openrouter_api_key}",
        "Content-Type": "application/json",
    }
    primary = model or settings.default_model
    body: dict = {
        "model": primary,
        "messages": messages,
    }
    if json_mode:
        body["response_format"] = {"type": "json_object"}

    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.post(OPENROUTER_URL, json=body, headers=headers)

        # Fallback to paid model on rate limit or server error
        if resp.status_code in (429, 502, 503) and settings.fallback_model and primary != settings.fallback_model:
            body["model"] = settings.fallback_model
            resp = await client.post(OPENROUTER_URL, json=body, headers=headers)

        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"]


async def grade_open_answer(
    question_text: str,
    model_answer: str,
    user_answer: str,
) -> GradeResult:
    prompt = f"""You are grading a satellite engineering quiz answer.

Question: {question_text}
Model answer: {model_answer}
Student answer: {user_answer}

Score the answer from 0.0 to 1.0 and provide brief feedback (1-2 sentences).
Respond in JSON: {{"score": 0.85, "feedback": "..."}}"""

    content = await call_openrouter(
        messages=[{"role": "user", "content": prompt}],
        json_mode=True,
    )
    data = json.loads(content)
    return GradeResult(score=float(data["score"]), feedback=data["feedback"])
