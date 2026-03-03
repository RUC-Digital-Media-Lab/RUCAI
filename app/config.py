import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


ROOT_DIR = Path(__file__).resolve().parents[1]
ENV_PATH = ROOT_DIR / ".env"


@dataclass(frozen=True)
class Settings:
    data_root: Path
    upload_root: Path
    db_host: str
    db_port: int
    db_name: str
    db_user: str
    db_password: str
    ollama_base_url: str
    embed_model: str
    chat_model: str
    auth_username: str
    auth_password: str
    auth_users_file: Path
    auth_ttl_seconds: int


def load_settings() -> Settings:
    load_dotenv(ENV_PATH, override=False)

    data_root = Path(os.getenv("DATA_ROOT", str(ROOT_DIR / "data")))
    upload_root = Path(os.getenv("UPLOAD_ROOT", str(data_root / "uploads")))

    return Settings(
        data_root=data_root,
        upload_root=upload_root,
        db_host=os.getenv("DB_HOST", "localhost"),
        db_port=int(os.getenv("DB_PORT", "5432")),
        db_name=os.getenv("DB_NAME", "ppl_rag"),
        db_user=os.getenv("DB_USER", "ppl"),
        db_password=os.getenv("DB_PASSWORD", ""),
        ollama_base_url=os.getenv("OLLAMA_BASE_URL", "http://localhost:11434"),
        embed_model=os.getenv("EMBED_MODEL", "bge-m3"),
        chat_model=os.getenv("CHAT_MODEL", "gemma3:12b"),
        auth_username=os.getenv("AUTH_USERNAME", "frede"),
        auth_password=os.getenv("AUTH_PASSWORD", "rucai-dev-password"),
        auth_users_file=Path(os.getenv("AUTH_USERS_FILE", str(data_root / "auth_users.json"))),
        auth_ttl_seconds=int(os.getenv("AUTH_TTL_SECONDS", "43200")),
    )


def ensure_data_dirs(settings: Settings) -> None:
    settings.data_root.mkdir(parents=True, exist_ok=True)
    settings.upload_root.mkdir(parents=True, exist_ok=True)
