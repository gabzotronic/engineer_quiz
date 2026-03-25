from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_path: str = "quiz.db"
    openrouter_api_key: str = ""
    default_model: str = "nvidia/nemotron-3-super-120b-a12b:free"
    fallback_model: str = "nvidia/nemotron-3-super-120b-a12b"
    quiz_size: int = 10
    roles: list[str] = [
        "Software Engineer",
        "QA Engineer",
        "AOCS Engineer",
        "Project Manager",
        "Systems Engineer",
    ]

    model_config = {"env_file": ".env", "env_prefix": "QUIZ_", "extra": "ignore"}


settings = Settings()
