import json
from pathlib import Path

from pydantic_settings import BaseSettings

ROLES_FILE = Path(__file__).resolve().parent.parent / "data" / "roles.json"


def _load_role_names() -> list[str]:
    if ROLES_FILE.exists():
        return [r["name"] for r in json.loads(ROLES_FILE.read_text())]
    return ["Systems Engineer", "AOCS Engineer", "Flight Software Engineer",
            "Ground Software Engineer", "QA Engineer", "Project Manager"]


class Settings(BaseSettings):
    database_path: str = "quiz.db"
    openrouter_api_key: str = ""
    default_model: str = "nvidia/nemotron-3-super-120b-a12b:free"
    fallback_model: str = "nvidia/nemotron-3-super-120b-a12b"
    quiz_size: int = 10
    roles: list[str] = _load_role_names()

    model_config = {"env_file": ".env", "env_prefix": "QUIZ_", "extra": "ignore"}


settings = Settings()
