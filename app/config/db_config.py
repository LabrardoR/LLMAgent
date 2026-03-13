from tortoise import Tortoise
import os

DB_USER = os.getenv("DB_USER", "root")
DB_PASSWORD = os.getenv("DB_PASSWORD")
DB_NAME = os.getenv("DB_NAME")

DB_CONFIG = {
    "connections": {
        "default": f"mysql://{DB_USER}:{DB_PASSWORD}@127.0.0.1:3306/{DB_NAME}"
    },
    "apps": {
        "models": {
            "models": [
                "app.models.user",
                "app.models.conversation",
                "app.models.message",
                "app.models.long_memory",
                "app.models.knowledge_document",
                "aerich.models"
            ],
            "default_connection": "default",
        },
    },
}

async def init_db():
    await Tortoise.init(config=DB_CONFIG)
    await Tortoise.generate_schemas()