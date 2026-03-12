from tortoise import Tortoise

DB_CONFIG = {
    "connections": {
        "default": "mysql://root:932384@127.0.0.1:3306/llm_agent"
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