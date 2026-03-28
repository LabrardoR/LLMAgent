# LLMAgent 接口文档

> Base URL: `http://localhost:8000`
>
> 所有需要认证的接口须在请求头中携带：`Authorization: Bearer <access_token>`

---

## 认证说明

| 项目 | 说明 |
|------|------|
| 认证方式 | JWT Bearer Token |
| 算法 | HS256 |
| 有效期 | 默认 30 分钟 |
| Token 获取 | 调用登录或注册接口 |
| Token 失效 | 调用登出接口后 Token 立即失效（黑名单机制） |

---

## 一、用户模块 `/api/user`

### 1.1 注册

**`POST /api/user/register`**

**认证**：不需要

**请求体**（`application/json`）：

```json
{
  "account": "string",
  "password": "string"
}
```

> 密码强度要求：长度 ≥ 8，须包含大写字母、小写字母、数字、特殊字符

**响应** `200`：

```json
{
  "access_token": "string",
  "token_type": "bearer",
  "user": {
    "user_id": "uuid",
    "account": "string",
    "username": "string | null",
    "phone": "string | null",
    "email": "string | null",
    "gender": 0,
    "points": 0,
    "photo_url": "string | null"
  }
}
```

**错误**：

| HTTP | 说明 |
|------|------|
| 400 | 账号已存在 / 密码不符合强度要求 |

---

### 1.2 登录

**`POST /api/user/login`**

**认证**：不需要

**请求体**（`application/x-www-form-urlencoded`，OAuth2 标准格式）：

| 字段 | 类型 | 说明 |
|------|------|------|
| username | string | 账户名 |
| password | string | 密码 |

**响应** `200`：同注册响应结构

**错误**：

| HTTP | 说明 |
|------|------|
| 401 | 账号或密码错误 |

---

### 1.3 获取当前用户信息

**`GET /api/user/me`**

**认证**：需要

**响应** `200`：

```json
{
  "user_id": "uuid",
  "account": "string",
  "username": "string | null",
  "phone": "string | null",
  "email": "string | null",
  "gender": 0,
  "points": 0,
  "photo_url": "string | null"
}
```

---

### 1.4 修改当前用户信息

**`PUT /api/user/me`**

**认证**：需要

**请求体**（`application/json`，所有字段可选）：

```json
{
  "username": "string",
  "phone": "string",
  "email": "string",
  "gender": 0,
  "photo_url": "string"
}
```

> `gender`: `0` = 男，`1` = 女

**响应** `200`：同获取用户信息响应结构

---

### 1.5 修改密码

**`PUT /api/user/password`**

**认证**：需要

**请求体**（`application/json`）：

```json
{
  "old_password": "string",
  "new_password": "string"
}
```

> 新密码须满足强度要求，且不能与旧密码相同

**响应** `200`：

```json
{ "message": "密码已更新" }
```

**错误**：

| HTTP | 说明 |
|------|------|
| 400 | 原密码错误 / 新密码不合规 |

---

### 1.6 登出

**`POST /api/user/logout`**

**认证**：需要

**响应** `200`：

```json
{ "message": "已登出" }
```

---

### 1.7 上传头像

**`POST /api/user/avatar`**

**认证**：需要

**请求体**（`multipart/form-data`）：

| 字段 | 类型 | 说明 |
|------|------|------|
| file | File | 图片文件，仅支持 `image/jpeg` / `image/png` |

**响应** `200`：同获取用户信息响应结构（`photo_url` 更新为 `/static/avatars/<filename>`）

**错误**：

| HTTP | 说明 |
|------|------|
| 400 | 文件类型不支持 |

---

## 二、聊天模块 `/api/chat`

### 2.1 获取会话列表

**`GET /api/chat/conversations`**

**认证**：需要

**响应** `200`（按创建时间倒序）：

```json
[
  {
    "conversation_id": "uuid",
    "title": "string",
    "created_time": "2024-01-01T00:00:00"
  }
]
```

---

### 2.2 创建新会话

**`POST /api/chat/conversations`**

**认证**：需要

**请求体**（`application/json`）：

```json
{ "title": "新对话" }
```

**响应** `200`：

```json
{ "conversation_id": "uuid" }
```

---

### 2.3 获取会话消息列表

**`GET /api/chat/conversations/{conversation_id}`**

**认证**：需要

**路径参数**：

| 参数 | 类型 | 说明 |
|------|------|------|
| conversation_id | uuid | 会话 ID |

**响应** `200`（按时间正序）：

```json
[
  {
    "message_id": "uuid",
    "role": "user | assistant | system",
    "content": "string",
    "created_time": "2024-01-01T00:00:00"
  }
]
```

---

### 2.4 修改会话标题

**`PUT /api/chat/conversations/{conversation_id}`**

**认证**：需要

**路径参数**：`conversation_id`（uuid）

**请求体**（`application/json`）：

```json
{ "title": "string" }
```

**响应** `200`：

```json
{ "message": "会话标题已更新" }
```

---

### 2.5 删除会话

**`DELETE /api/chat/conversations/{conversation_id}`**

**认证**：需要

**路径参数**：`conversation_id`（uuid）

> 软删除，会话标记为不可见，历史消息保留

**响应** `200`：

```json
{ "message": "会话已删除" }
```

---

### 2.6 清空会话消息

**`DELETE /api/chat/conversations/{conversation_id}/messages`**

**认证**：需要

**路径参数**：`conversation_id`（uuid）

**响应** `200`：

```json
{ "message": "会话已清空" }
```

---

### 2.7 编辑消息

**`PUT /api/chat/messages/{message_id}`**

**认证**：需要

**路径参数**：`message_id`（uuid）

**请求体**（`application/json`）：

```json
{ "content": "string" }
```

> 更新消息内容后，该消息之后的所有消息将被自动删除

**响应** `200`：

```json
{ "message": "消息已更新" }
```

---

### 2.8 删除单条消息

**`DELETE /api/chat/messages/{message_id}`**

**认证**：需要

**路径参数**：`message_id`（uuid）

**响应** `200`：

```json
{ "message": "消息已删除" }
```

---

### 2.9 流式聊天（SSE）

**`POST /api/chat/`**

**认证**：需要

**请求体**（`application/json`）：

```json
{
  "conversation_id": "uuid（可选，不传则自动创建新会话）",
  "messages": [
    { "role": "user", "content": "string" }
  ]
}
```

> 取 `messages` 列表中最后一条消息作为本次用户输入

**响应**：`Content-Type: text/event-stream`（SSE 格式）

```
// 若为新会话，首条事件推送会话 ID
data: {"conversation_id": "uuid"}

// 逐 token 流式推送
data: {"content": "token片段"}

// 出错时推送
data: {"error": "错误信息"}
```

> 内部集成：短期记忆（最近10条）、长期记忆提取与召回、RAG 知识库检索

**前端接入示例（fetch SSE）**：

```javascript
const response = await fetch('/api/chat/', {
  method: 'POST',
  headers: {
    'Authorization': `Bearer ${token}`,
    'Content-Type': 'application/json'
  },
  body: JSON.stringify({ messages: [{ role: 'user', content: '你好' }] })
})

const reader = response.body.getReader()
const decoder = new TextDecoder()

while (true) {
  const { done, value } = await reader.read()
  if (done) break
  const lines = decoder.decode(value).split('\n')
  for (const line of lines) {
    if (line.startsWith('data: ')) {
      const data = JSON.parse(line.slice(6))
      // 处理 data.conversation_id 或 data.content
    }
  }
}
```

---

### 2.10 非流式聊天

**`POST /api/chat/sync`**

**认证**：需要

**请求体**：同流式聊天

**响应** `200`：

```json
{
  "conversation_id": "uuid",
  "content": "string（完整回答）"
}
```

---

### 2.11 重新生成回答

**`POST /api/chat/regenerate`**

**认证**：需要

**请求体**（`application/json`）：

```json
{
  "conversation_id": "uuid",
  "message_id": "uuid（基准消息 ID，传 user 消息或 assistant 消息均可）"
}
```

> 若传入的是 assistant 消息 ID，系统会自动向前查找最近的 user 消息作为输入

**响应** `200`：

```json
{
  "conversation_id": "uuid",
  "message_id": "uuid（新生成的 assistant 消息 ID）",
  "content": "string"
}
```

---

## 三、知识库模块 `/api/knowledge`

### 3.1 上传知识库文档

**`POST /api/knowledge/documents/upload`**

**认证**：需要

**请求体**（`multipart/form-data`）：

| 字段 | 类型 | 说明 |
|------|------|------|
| file | File | 文本文档（txt、md、pdf 等） |

**响应** `200`：

```json
{
  "document_id": "uuid",
  "title": "string",
  "file_name": "string",
  "chunk_count": 10,
  "status": "indexed",
  "created_time": "2024-01-01T00:00:00"
}
```

---

### 3.2 获取知识库文档列表

**`GET /api/knowledge/documents`**

**认证**：需要

**响应** `200`（按上传时间倒序）：

```json
[
  {
    "document_id": "uuid",
    "title": "string",
    "file_name": "string",
    "chunk_count": 10,
    "status": "indexed",
    "created_time": "2024-01-01T00:00:00"
  }
]
```

---

### 3.3 删除知识库文档

**`DELETE /api/knowledge/documents/{document_id}`**

**认证**：需要

**路径参数**：`document_id`（uuid）

> 同时删除该文档的所有分片数据

**响应** `200`：

```json
{ "message": "文档已删除" }
```

---

### 3.4 知识库检索

**`POST /api/knowledge/search`**

**认证**：需要

**请求体**（`application/json`）：

```json
{
  "query": "string（1~1000字符）",
  "top_k": 4
}
```

| 字段 | 类型 | 默认 | 范围 | 说明 |
|------|------|------|------|------|
| query | string | 必填 | 1~1000 字符 | 检索词 |
| top_k | int | 4 | 1~10 | 返回最相关的分片数量 |

**响应** `200`：

```json
{ "context": "string（检索结果拼接文本）" }
```

---

## 四、模型与工具模块

### 4.1 获取可用模型列表

**`GET /api/model/list`**

**认证**：不需要

**响应** `200`：可用模型名称列表

```json
["gpt-4o", "gpt-4o-mini", "..."]
```

---

### 4.2 切换模型

**`POST /api/model/select`**

**认证**：需要

**请求体**（`application/json`）：

```json
{ "model_name": "string" }
```

**响应** `200`：

```json
{ "model_name": "string（实际生效的模型名）" }
```

---

### 4.3 获取工具列表

**`GET /api/tools`**

**认证**：需要

**响应** `200`：可用工具列表（含扩展工具）

```json
[
  {
    "name": "string",
    "description": "string",
    "enabled": true
  }
]
```

---

### 4.4 启用 / 禁用工具

**`POST /api/tools/toggle`**

**认证**：需要

**请求体**（`application/json`）：

```json
{ "tool_name": "string", "enabled": true }
```

**响应** `200`：

```json
{ "tool_name": "string", "enabled": true }
```

---

### 4.5 重载扩展工具

**`POST /api/tools/reload`**

**认证**：需要

**响应** `200`：扩展工具扫描结果

---

## 附录：通用错误码

| HTTP 状态码 | 说明 |
|-------------|------|
| 400 | 请求参数错误 |
| 401 | 未认证或 Token 失效 |
| 403 | 无权限访问该资源 |
| 404 | 资源不存在 |
| 422 | 请求体格式错误（Pydantic 校验失败） |
| 500 | 服务器内部错误 |

---

## 附录：字段枚举值说明

| 字段 | 值 | 说明 |
|------|----|------|
| `gender` | `0` | 男 |
| `gender` | `1` | 女 |
| `role` | `user` | 用户消息 |
| `role` | `assistant` | AI 回复 |
| `role` | `system` | 系统消息 |
| `status`（文档） | `indexed` | 已完成向量化索引 |
