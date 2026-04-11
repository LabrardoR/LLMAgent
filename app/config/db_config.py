from tortoise import Tortoise
import os

DB_HOST = os.getenv("DB_HOST", "127.0.0.1")
DB_PORT = int(os.getenv("DB_PORT", 3306))
DB_USER = os.getenv("DB_USER", "root")
DB_PASSWORD = os.getenv("DB_PASSWORD", "")
DB_NAME = os.getenv("DB_NAME", "llm_agent")

DB_CONFIG = {
    "connections": {
        "default": f"mysql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"
    },
    "apps": {
        "models": {
            "models": [
                "app.models.user",
                "app.models.user_config",
                "app.models.revoked_token",
                "app.models.conversation",
                "app.models.message",
                "app.models.long_memory",
                "app.models.memory_meta",
                "app.models.memory_event",
                "app.models.knowledge_document",
                "app.models.knowledge_chunk",
                "app.models.knowledge_document_meta",
                "app.models.tool_call_log",
                "app.models.chat_run_log",
                "aerich.models"
            ],
            "default_connection": "default",
        },
    },
}


async def init_db():
    await Tortoise.init(config=DB_CONFIG)
    await Tortoise.generate_schemas()
