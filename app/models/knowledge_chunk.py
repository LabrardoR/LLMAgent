import uuid
from tortoise import fields
from tortoise.models import Model


class KnowledgeChunk(Model):
    chunk_id = fields.UUIDField(pk=True, default=uuid.uuid4)
    document = fields.ForeignKeyField("models.KnowledgeDocument", related_name="chunks", description="所属文档")
    chunk_index = fields.IntField(description="文档内分片序号")
    content = fields.TextField(description="分片文本")
    vector_id = fields.CharField(max_length=120, null=True, description="向量索引ID")
    created_time = fields.DatetimeField(auto_now_add=True)
