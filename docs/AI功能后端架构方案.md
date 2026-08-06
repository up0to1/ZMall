# ZMall 后端架构方案（AI 扩展）

本方案在现有 Java 微服务基础上新增 Python AI 服务层，实现两大 AI 功能：AI 随心搭（商品驱动 + 风格驱动）与 AI 模特图生成。设计以 `docs/AI功能需求分析.md` 为依据，核心思路是 Java 负责交易与业务数据，Python 负责 AI 推理与向量检索，两者通过 RabbitMQ 和 HTTP 协作。

---

## 一、架构总览

### 1.1 分层架构

```
客户端（zmall-portal / zmall-admin / zm-refresh-admin）
        ↓ HTTPS / WSS
网关层（hm-gateway · Spring Cloud Gateway · 8080）
        ↓ REST（lb:// Nacos 服务发现）
┌─────────────────────────┬───────────────────────────┐
│  Java 微服务层（现有）    │  Python AI 服务层（新增）   │
│  item / cart / trade     │  ai-models（FastAPI）    │
│  user / pay / social     │  ai-outfit（LangGraph）    │
│  dashboard               │  shared（共享客户端）      │
└────────────┬────────────┴─────────────┬─────────────┘
             ↓                          ↓
基础设施层：MySQL / Redis / Qdrant / RabbitMQ / Nacos / OSS
```

### 1.2 核心设计原则

| 原则 | 落地方式 |
|------|----------|
| 不重写底层 | Java 微服务零改造，仅增量新增 Python 服务与少量接口 |
| 语言职责分离 | Java 管交易、业务数据、配额；Python 管 AI、模型、向量检索 |
| 统一网关入口 | Python 服务注册到 Nacos，Gateway 统一路由与鉴权 |
| 同步 + 异步混合 | 短任务 HTTP 同步；长任务（换装、模特图）RabbitMQ 异步 + WebSocket 推进度 |
| 照片零持久化 | 用户照片仅存 Redis 会话级缓存，TTL 自动过期，不落 MySQL/OSS |
| 功能内聚 | AI 随心搭整合商品驱动与风格驱动两种入口，统一配额池 |

---

## 二、服务拆分设计

### 2.1 Python 服务拆分（3 个模块）

| 模块 | 职责 | 端口 | 技术栈 |
|------|------|------|--------|
| **ai-models** | AI 模特图生成（MQ 消费 + 链式 VTON + 多 Agent 决策）、结果查询、向量检索 | 9000 | FastAPI + uvicorn |
| **ai-outfit** | AI 随心搭（商品驱动 + 风格驱动双模式）：意图理解、商品检索编排、组合决策、照片会话、换装 WS | 9001 | FastAPI + LangGraph |
| **shared** | 共享客户端库：Qdrant、OSS、模型、MQ、Nacos、DB 封装 | - | Python package |

拆分原因：AI 模特是 I/O 密集型（MQ 消费 + 链式 VTON + 多 Agent 决策），AI 随心搭是 LangGraph 多步推理编排，两者资源画像不同，拆分后可独立扩缩容。

### 2.2 ai-models 详细职责

| 接口分组 | 端点 | 方法 | 说明 |
|---------|------|------|------|
| AI 模特·结果查询 | `/api/v1/model/result/{task_id}` | GET | 商家查询生成任务状态（兜底轮询） |
| AI 模特·相似检索 | `/api/v1/search/similar` | GET | 向量检索相似商品 |
| WebSocket | `/ws/model/{user_id}` | WS | AI 模特图生成进度推送 |
| 健康检查 | `/health` | GET | Nacos 心跳 + 探针 |

AI 模特图的生成、发布与模特图池管理接口在 Java item-service（`/items/admin/ai-model/*`），Python ai-models 只负责 MQ 消费、链式 VTON 生成、结果 MQ 回流，不暴露 HTTP 生成接口。

### 2.3 ai-outfit 详细职责

| 接口分组 | 端点 | 方法 | 说明 |
|---------|------|------|------|
| AI 随心搭·风格驱动 | `/api/v1/outfit/agent/recommend` | POST | 结构化表单（风格/颜色/品类/店铺可选框 + 选填备注）+ 照片 → LangGraph 编排 → 3 套搭配 + 换装图 |
| AI 随心搭·风格驱动 | `/api/v1/outfit/agent/feedback` | POST | 多轮反馈：表单字段（dislikeColors/dislikeItemIds/wantStyleTags）+ 备注 → LLM 解析 → 局部调整推荐 |
| AI 随心搭·结果查询 | `/api/v1/outfit/agent/result/{task_id}` | GET | 兜底轮询：查 Redis 任务状态 |
| AI 随心搭·商品驱动 | `/api/v1/outfit/generate` | POST | 用户从商品详情页发起，指定主商品 + 照片会话 → 生成 1 套搭配 |
| 照片会话 | `/api/v1/outfit/photo` | POST | 上传自拍照，写入 Redis 会话级缓存 |
| 健康检查 | `/health` | GET | Nacos 心跳 |

风格驱动接口统一在 `/api/v1/outfit/agent/` 下，与商品驱动 `/api/v1/outfit/generate` 同属 `outfit` 命名空间，体现同一功能两种入口的产品定位。

#### 2.3.1 场景 A/B 双模型路由

根据用户是否上传自拍照，自动路由到不同的 LLM 模型与 VTON 底图：

| 场景 | 用户输入 | LLM 模型 | LLM 任务 | VTON 底图 | State 字段 |
|---|---|---|---|---|---|
| **A** | 无自拍照 + 文本描述 | 纯文本模型（qwen3.5-flash） | HyDE / note / feedback / select_top_outfits | 系统默认模特图（`default_model_image_url` 配置） | `use_default_model=True`, `user_visual_profile=None` |
| **B** | 有自拍照 + 文本描述 | 视觉模型（qwen3.5-flash） | `analyze_user_photo`（图像理解）+ 纯文本任务 | 用户自拍照（Redis 照片会话） | `use_default_model=False`, `user_visual_profile={gender, skin_tone, body_type, age_range, style_cue, preferred_colors}` |

关键组件：

| 组件 | 位置 | 说明 |
|---|---|---|
| `LlmClient` | shared/model_client/llm_client.py | 双模型路由：`text_model` / `vision_model` 独立 client |
| `analyze_user_photo` | LlmClient 方法 | OpenAI Vision 消息格式，用视觉模型分析照片提取 6 个结构化字段 |
| `_load_default_model_image` | ai-outfit/app/tools/nodes.py | 场景 A 兜底：从 `default_model_image_url` 下载默认模特图，加载失败降级 PIL 贴图 |
| `AgentState` | ai-outfit/app/schemas/agent_state.py | `user_visual_profile` + `use_default_model` 字段 |

不做性别过滤：中性衣服难识别、大模型过滤成本高、场景 B 已有视觉特征软性引导、场景 A 无性别信息可用（详见 `docs/AI核心功能设计.md` §3.12.2）。

穿搭品类共 7 类：上衣、下装、全身套装、鞋、帽子、包、配饰。全身套装指成套衣服、连衣裙、连体衣等一件即覆盖全身的衣物，等价于上衣 + 下装，VTON 一次完成。VTON 链式顺序为上衣 → 下装 → 全身套装 → 帽 → 包 → 配饰 → 鞋。

### 2.4 Java 侧新增内容

| 改动位置 | 内容 |
|---------|------|
| `hm-api` | 新增 `AiOutfitDTO` / `AiOutfitVO`、`AiModelGenerateDTO`（多商品 + 模特图来源 + 生成模式）、`AiModelResultMessage`、`ShopModelImageDTO` / `PlatformModelImageDTO`、`BodyProfileDTO` / `SizeRecommendRequest` / `SizeRecommendResult` 等 |
| `hm-api` | 新增 `constant/OutfitCategories.java`，含 `AI_MODEL_SUPPORT_CATEGORIES = [上衣, 下装, 全身套装, 帽子]` |
| `user-service` | 配额服务（Credits 积分制 + Quota 次数制双轨，三阶段 deduct/confirm/rollback） |
| `user-service` | 用户身体信息档案 CRUD（`/body-profile`）、用户衣橱 CRUD（`/wardrobe`）、浏览记录（`/browse-history`） |
| `item-service` | AI 模特生成接口（配额预扣 + MQ 入队）、模特图发布、系统模特图池 CRUD、OSS STS 临时凭证 |
| `item-service` | 尺码对照与推荐接口 `/items/size-chart/**`、内部接口 `/items/internal/inventory/batch`、`/items/internal/trending` |
| `cart-service` | 套装加购接口（批量加购 + 套装标识） |
| `trade-service` | 多店拆单交易 |
| `social-service` | 搭配发布到 Feed 接口 |
| `hm-gateway` | 新增 ai-models / ai-outfit 路由、user-service 路由扩展（credits/quota/body-profile/browse-history/wardrobe） |

Java 与 Python 之间通过 RabbitMQ 消息驱动与 HTTP 直连 Java REST 接口协作，不存在 Java 到 Python 的 Feign 直调。

### 2.5 AI 模特三种生成模式

生成模式由 MQ 消息中的 `generationMode` 字段控制，ai-models 消费时路由到对应工作流：

```
Java item-service（POST /items/admin/ai-model/generate）
   ↓ MQ ai.model.generate 消息（含 generationMode）
ai-models ModelMqConsumer._process_task
   ├─ "single" + 未启用多 Agent → ModelService.generate_model_images_chain（链式 VTON）
   ├─ "single" + 启用多 Agent   → model_director_graph（5 角色 Agent 工作流）
   ├─ "multi_outfit"             → multi_outfit_graph（多套组合并行 VTON）
   └─ "multi_pose"               → multi_pose_graph（1 次 VTON + N 次 wan2.7-image 图生图）
```

三种模式共享子图组件：

| 子图 | 用途 |
|------|------|
| `outfit_combination_subgraph.py` | 搭配组合推荐（multi_outfit 用，LLM 推荐 1-4 套合法组合 + 笛卡尔积降级） |
| `director_nodes.py` | 导演节点（plan / review / post_process） |
| `stylist_dual_subgraph.py` | 双地区衣品审美子图（EU + Asia 并行） |
| `photographer_subgraph.py` | 摄影子图（姿势/构图/光影） |
| `lighting_subgraph.py` | 灯光子图 |
| `makeup_subgraph.py` | 妆造子图 |
| `_llm.py` | LLM 调用封装（重试 + 超时控制） |

多 Agent 工作流在 ai-models 内部执行，无跨服务调用。

### 2.6 AI 随心搭子 Agent 与外部工具

#### 2.6.1 子 Agent 架构

```
ai-outfit LangGraph 工作流
   ├─ 节点1 intent_understanding
   │   └─ enable_intent_sub_agent=true 时调 LlmClient.react_intent
   │       └─ IntentToolExecutor（5 个 Tool）：parse_note / rewrite_query_hyde /
   │           analyze_user_photo / get_weather_season / encode_query_vector
   ├─ 节点2 qdrant_search（固定流程）
   │   └─ external_tools_enabled=true 时调 inventory_service.batch_query_stock 过滤缺货
   ├─ 节点3 outfit_combination（固定流程，LLM select Top3）
   ├─ 节点3.5 Reflection 自检（固定流程）
   ├─ 节点3.6 decision_agent
   │   └─ enable_decision_sub_agent=true 时调 LlmClient.react_decision
   │       └─ DecisionToolExecutor（5 个 Tool）：re_search / get_item_details /
   │           call_price_balance / call_trending_styles / search_fashion_trend
   ├─ 节点4 vton_generate（固定流程）
   └─ 节点5 feedback（仅在用户反馈时触发）
```

LangGraph 节点命名：`entry → NODE_INTENT → NODE_SEARCH → NODE_COMBINE → NODE_REFLECT → NODE_VTON → NODE_OSS → END`，含 `NODE_WARDROBE_OUTFIT` 用户选定模式分支（用户从衣橱选品时跳过 INTENT/SEARCH/COMBINE，直接进入 VTON）。子 Agent 为意图理解（ReAct）与搭配决策（ReAct）两类。

`get_weather_season` 调用策略：

- 调用条件：`has_picked_items=false` 且 `season_hint` 为空（纯风格驱动，风格标签不携带季节信息，必须调天气推导当前季节）
- 跳过条件 1：`has_picked_items=true`（用户已选定商品，商品隐含季节属性，互补商品应与选定商品季节一致）
- 跳过条件 2：`season_hint` 非空（用户明确指定季节，尊重用户意图）

#### 2.6.2 外部工具拓展

| 服务 | 实现 | 缓存 |
|------|------|------|
| `price_service.py` | 价格平衡分析（纯本地 statistics） | - |
| `inventory_service.py` | 实时库存查询（调 Java item-service） | Redis 5min（`ai:stock:`） |
| `fashion_trend_service.py` | 时尚潮流搜索（AnySearch API，社媒 + 通用双 tag，按 city/country 路由） | Redis 600s（`ai:fashion_trend:`） |
| `weather_service.py` | 天气/季节（uapis.cn API，默认城市北京，按城市名直查） | Redis 1800s（`ai:weather:`），失败降级按月份推断季节 |

配置开关（`ai-outfit/app/core/config.py`）：

| 开关 | 默认值 | 说明 |
|------|--------|------|
| `external_tools_enabled` | True | 外部工具总开关 |
| `weather_tool_enabled` | True | 天气工具 |
| `fashion_trend_tool_enabled` | True | 时尚潮流搜索 |
| `inventory_tool_enabled` | True | 实时库存查询 |
| `price_tool_enabled` | True | 价格平衡分析 |
| `trend_tool_enabled` | False | 旧版流行趋势工具（已被 fashion_trend 替代） |
| `enable_intent_sub_agent` | True | 意图理解子 Agent |
| `enable_decision_sub_agent` | True | 搭配决策子 Agent |

调用关系：price / fashion_trend 由 DecisionToolExecutor 在 ReAct 循环中自主调用；inventory 由节点 2 在向量检索后固定调用（过滤缺货候选）；weather 由 IntentToolExecutor 在 ReAct 循环中自主调用。

### 2.7 尺码推荐服务

```
用户端 zmall-portal（outfit-result.html 加购/下单时）
   ↓ HTTP
Java item-service SizeChartController
   ├─ POST /items/size-chart/recommend-by-item?itemId={itemId}
   │   ↓ 三级回退查询
   │   ├─ 1. 商品专用绑定（item.size_chart_id 非空）
   │   ├─ 2. 店铺品类通用表（shop_id + category + gender）
   │   └─ 3. 系统模板（shop_id=0 + category + gender）
   │   ↓ 基于用户身体信息匹配
   └─ 返回 SizeRecommendResult（recommendedSize / confidence / alternatives / reason）

Python ai-outfit（可选中转，JavaClient.recommend_size_by_item）
```

数据表分布：

| 表 | 数据库 | 用途 |
|----|--------|------|
| `size_chart_reference` | hm-item | 店铺尺码对照参考表（shop_id=0 系统模板，61 条预置数据：4 类品类 × 3 性别 × 6 尺码） |
| `user_body_profile` | hm-user | 用户身体信息档案（多档案支持） |
| `item.size_chart_id` | hm-item | 商品专用尺码表绑定字段（三级回退第 1 级） |

接口分组：

| 分组 | 端点前缀 | 调用方 | 用途 |
|------|---------|--------|------|
| 通用接口 | `GET/POST /items/size-chart/{reference,templates,item,recommend,recommend-batch,recommend-by-item}` | C 端用户 + AI 随心搭 + 商品详情页 | 查询尺码表 / 推荐尺码 |
| 商家后台接口 | `GET/POST/PUT/DELETE /items/size-chart/shop/**` | 商家端 zm-refresh-admin | 维护店铺尺码表（CRUD + 一键复制系统模板） |

### 2.8 性别与服装搭配

全平台/全店铺找搭配时避免跨性别推荐，性别信息来源于系统模特、用户自拍、身体档案，三者优先级递减。

性别来源优先级：

| 优先级 | 来源 | 字段位置 | 获取方式 | 适用场景 |
|--------|------|----------|----------|----------|
| 1 | 系统模特 | `system_model_image.gender` | 前端选定后直接传入 `systemModelGender` | 用户选系统模特图作为 VTON 底图 |
| 2 | 用户自拍分析 | `user_visual_profile.gender` | 节点 1 LLM 视觉分析上传照片 | 用户上传真人照片 |
| 3 | 身体档案 | `user_body_profile.gender` | 节点 1 调 user-service `/body-profile/{id}` | 用户仅登记身体档案，未传照片/未选模特 |

三者都为空时跳过性别过滤，记录日志向后兼容。

Qdrant 过滤条件（`shared/qdrant_client/searcher.py` 的 `search_complementary_items`）：

```python
if target_gender is not None:
    must_conditions.append(FieldCondition(
        key="target_gender",
        match=MatchAny(any=[target_gender, "unisex"]),
    ))
```

即男用户匹配 `male + unisex`，女用户匹配 `female + unisex`。LLM 搭配决策的 `OUTFIT_SELECT_PROMPT` 另有性别匹配原则作为双保险。

商品 `target_gender` 数据流：商家后台 → item-service 写 MySQL（`item.target_gender`）→ `ItemServiceImpl.buildItemSyncMessage` 构造 ItemSyncMessage → RabbitMQ `item.sync.exchange` → ai-outfit `item_sync_consumer.py` 消费 → `shared/qdrant_client/indexer.py` 写 Qdrant payload。全量入库脚本 `ai-outfit/scripts/index_items.py`，对账回填脚本 `ai-outfit/scripts/reconcile_mysql_qdrant.py --fix-inconsistent`。

### 2.9 用户行为事件采集

覆盖商品详情页浏览、加购物车、下单、搭配采纳 4 类关键事件，为个性化推荐画像提供原始数据。

```
Java 微服务（事件生产者）
   ├─ item-service：商品详情页访问，type=ITEM_VIEW
   ├─ cart-service：加入购物车，type=CART_ADD
   ├─ trade-service：下单，type=ORDER_PLACE
   └─ ai-outfit：搭配采纳，type=OUTFIT_ACCEPT
   ↓
RabbitMQ（user.behavior.exchange）
   ↓
Python UserBehaviorConsumer（ai-outfit/app/mq/user_behavior_consumer.py）
   ├─ 消费 MQ 消息
   ├─ 性别对齐检查
   ├─ 调向量模型编码商品
   └─ 写入 Qdrant zmall_user_behavior collection
```

事件类型与权重：

| type | 触发场景 | 权重 |
|------|----------|------|
| `ITEM_VIEW` | 用户访问商品详情页 | 1.0 |
| `CART_ADD` | 用户加入购物车 | 1.5 |
| `ORDER_PLACE` | 用户下单成功 | 2.0 |
| `OUTFIT_ACCEPT` | 用户采纳 AI 搭配 | 3.0 |

性别对齐检查：商品 `target_gender` 与用户性别冲突时（如男用户浏览女款），仅提取颜色/价格信息，不写入向量，payload 标记 `is_cross_gender=true`。此类记录仅用于判断用户是否为他人购买，不参与主画像聚合。当用户多次购买异性商品（≥3 次）时建立独立的 `family_buy_profile` 画像，仅用于礼物推荐场景，不用于随心搭主推荐。

### 2.10 个性化推荐画像

从历史行为中提取用户偏好信号，注入 LangGraph 工作流的 4 个关键节点，实现跨会话记忆。

数据源（`ai-outfit/app/services/profile_service.py`）：

| 数据源 | 类型 | 内容 |
|--------|------|------|
| Qdrant `zmall_user_behavior` collection | 行为向量 | CART_ADD / ORDER_PLACE / OUTFIT_ACCEPT |
| Qdrant `zmall_user_preference` collection | 显式偏好 | dislike_colors / like_styles |
| MySQL `user_browse_history` 表 | 浏览统计 | ITEM_VIEW |

画像产出字段：`top_styles`（Top3 风格）、`top_colors`（Top3 颜色）、`price_distribution`（价格分布）、`style_vector`（1024 维加权平均风格向量）、`profile_confidence`（0-1 置信度）。

信号权重与时间衰减：

- 权重：OUTFIT_ACCEPT=3.0，ORDER_PLACE=2.0，CART_ADD=1.5，ITEM_VIEW=1.0
- 衰减：浏览信号 30 天丢弃，购买/加购/采纳信号 90 天丢弃
- 置信度：`min(1.0, total_signal_weight / 20)`，数据量不足时按比例降权

推荐增强插入点：

| 插入点 | 位置 | 作用 |
|--------|------|------|
| ① 构造 initial_state 时加载画像 | `agent_service.py#recommend` | `top_styles` 合并到 `style_tags`，价格中位数 ×1.5 作为 `budget_max` 软约束 |
| ② 节点 1 query_vector 融合 | `nodes.py` 节点 1 | `final_vector = text_vector × (1-α) + style_vector × α`，`α = profile_confidence × 0.4` |
| ③ 节点 3 跨会话去重 | `nodes.py` 节点 3 | 已拒绝商品硬过滤，已采纳商品降权（×0.3） |
| ④ accept 时记录行为信号 | `outfit_agent.py#accept` | 发 OUTFIT_ACCEPT 事件到 MQ |

缓存策略：懒加载，`ai:profile:user:{userId}` TTL 24h，accept 时主动失效；聚合失败返回空画像（`profile_confidence=0`），推荐工作流按原逻辑执行。

---

## 三、通信协议设计

### 3.1 商品驱动请求流

```
前端 → Gateway → ai-outfit →（同步调 Java 配额预扣）→（同步调 Java 商品数据）→ 返回 taskId → HTTP 结束
                                                                          ↓
                                                    Python 内部异步：Qdrant 检索 → 换装 → OSS 上传
                                                                          ↓
                                                    WebSocket 推送结果 → 前端
                                                                          ↓
                                                    MQ 通知 Java 确认/回滚配额
```

用户点击商品详情页「AI 随心搭」：

1. 前端 → Gateway：`POST /api/v1/outfit/generate`（含 itemId + photoSessionKey）
2. Gateway → ai-outfit：转发请求（透传 user-info）
3. ai-outfit → Java user-service：同步调配额预扣（type=OUTFIT_VTON，5 credits）
4. 预扣失败 → 返回「次数或余额不足」
5. 预扣成功 → ai-outfit → Java item-service：同步获取商品详细数据
6. ai-outfit 生成 taskId → Redis 写任务状态（PROCESSING）→ HTTP 返回 `{ taskId }`
7. Python 内部异步：Qdrant 检索互补商品 → 虚拟试衣 → OSS 上传换装图
8. 完成 → Redis 更新状态 → WebSocket 推送前端 → MQ 通知 Java 确认/回滚配额

### 3.2 风格驱动请求流

```
前端 → Gateway → ai-outfit →（同步调 Java 配额预扣）→ 返回 taskId → HTTP 结束
                                                              ↓
                                        Python 内部异步：LangGraph 多步推理
                                          ├─ 节点1：意图理解（风格+场景+品类）
                                          ├─ 节点2：Qdrant 向量检索
                                          ├─ 节点3：组合排序（风格×热度×库存）
                                          ├─ 节点4：换装图生成（用户照片/默认照片）
                                          └─ 节点5：OSS 上传
                                                              ↓
                                        WebSocket 推送 3 套搭配 → 前端
                                                              ↓
                                        MQ 通知 Java 确认/回滚配额
```

### 3.3 AI 模特请求流

```
前端 →（STS 直传 OSS，可选）→ Gateway → Java 后端 → 校验 + 配额预扣 → MQ 入队 → HTTP 返回 taskId
                                                                                  ↓
                                                                  Python ai-models 消费
                                                                      ├─ 下载模特图（base）
                                                                      ├─ 按品类顺序下载商品图
                                                                      ├─ 链式 VTON（全身套装→上衣→下装→帽子）
                                                                      └─ 上传 N 张中间图 + 1 张最终图到 OSS
                                                                                  ↓
                                                                  MQ 结果回流 → Java 更新 DB + 确认配额
                                                                                  ↓
                                                                  商家刷新查看 / WS 通知
```

要点：模特图来源为系统模特图池（平台公共池 / 店铺池 / 商家临时上传）；商品数量 1-4 件；品类限上衣/下装/全身套装/帽子 4 类；链式顺序全身套装优先，避免被覆盖。MQ 消息含 `enableMultiAgent` 开关，开启时走多 Agent 工作流（策划、VTON 执行、评估、可选后处理、OSS 上传），返回含 starRating / overallScore / styleFeatures / agentEvaluations 等字段。

### 3.4 RabbitMQ 队列设计

| Exchange | Queue | Routing Key | 生产者 | 消费者 | 用途 |
|----------|-------|-------------|--------|--------|------|
| `ai.outfit.exchange` | `ai.outfit.result` | `ai.outfit.result` | ai-models / ai-outfit | Java user-service | 配额确认/回滚（商品驱动 + 风格驱动共用） |
| `ai.model.exchange` | `ai.model.generate.queue` | `ai.model.generate` | Java item-service | ai-models | 模特图生成任务下发 |
| `ai.model.exchange` | `ai.model.result.queue` | `ai.model.result` | ai-models | Java item-service | 模特图结果回流 + 配额确认 |
| `item.sync.exchange` | `item.sync.upsert.queue` / `item.sync.delete.queue` | `item.upsert` / `item.delete` | Java item-service | ai-outfit | 商品上下架/更新/删除同步到 Qdrant |
| `user.behavior.exchange` | `user.behavior.event.queue` | `user.behavior.{type}` | Java 微服务 / ai-outfit | ai-outfit | 用户行为事件采集 |

设计说明：

- AI 随心搭两种模式共用 `ai.outfit.exchange`，配额确认/回滚逻辑完全一致
- 生成任务不走 MQ，Python 内部异步 + WS 推送；MQ 只用于通知 Java 做配额确认/回滚
- 商品同步：Java item-service 商品保存/上下架时发 `item.sync.exchange`，ai-outfit 消费后更新 Qdrant（含 color/season/target_gender 字段），失败重试 3 次后进死信队列 `item.sync.dlq` 人工处理
- 消息持久化 + 消费 ack，callback 自处理 ack/nack 避免消息丢失或重复消费

### 3.5 WebSocket 推送设计

```
@ws_manager 按 userId 建连，支持多页面
ai-outfit：/ws/ai/{user_id}（换装推送）
ai-models：/ws/model/{user_id}（AI 模特图推送）
```

推送消息 7 种 type：

| type | 含义 |
|------|------|
| `OUTFIT_PRODUCT` | 商品驱动模式推送 |
| `OUTFIT_AGENT` | 风格驱动模式推送 |
| `OUTFIT_RECOMMEND_RESULT` | 阶段一候选推荐完成 |
| `OUTFIT_VTON_RESULT` | 阶段二 VTON 完成 |
| `OUTFIT_ACCEPTED` | 用户已采纳 |
| `OUTFIT_AGENT_FEEDBACK` | 反馈轮完成 |
| `AI_MODEL` | AI 模特图推送 |

消息字段：`taskId`、`type`、`status`（PROCESSING/SUCCESS/FAILED）、`stage`（recommend/vton）、`outfits`、`errorMsg`、`creditsBalance` 等。

前端通过 Gateway 的 WSS 端口连接，Gateway 透传 WebSocket 到 ai-outfit / ai-models。按 userId 建连而非 taskId，因为用户可能开多个页面。

### 3.6 兜底轮询

前端未收到 WS 推送时用 taskId 轮询：

- 商品驱动：`GET /api/v1/outfit/result/{taskId}`
- 风格驱动：`GET /api/v1/outfit/agent/result/{taskId}`
- AI 模特：`GET /api/v1/model/result/{taskId}`

Python 查 Redis 任务状态返回。轮询策略：前 10s 每 2s 一次，之后每 5s 一次，最长 60s。

### 3.7 Java ↔ Python 认证传递

Gateway 解析 JWT 后，将 `userId` 放入 `user-info` 请求头透传，Python 侧通过中间件解析：

```python
@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    user_info = request.headers.get("user-info")
    if user_info:
        request.state.user_id = int(user_info)
    return await call_next(request)
```

#### 3.7.1 WebSocket 鉴权

网关层校验为主、Python 兜底的双层防护：

| 层级 | 机制 |
|------|------|
| 网关层 | `AuthGlobalFilter` 对 WS 升级请求从 query param 提取 `token`，校验 JWT 签名与时效，通过后把 `userId` 写入 `user-info` header 透传 |
| Python 兜底 | `_extract_jwt_user_id` 解码 JWT payload 取 `userId`，与路径 `{user_id}` 一致才放行，不一致返回 403 防越权监听 |

Python 侧降级兜底：accept 后等待首条 `{"type":"auth","token":"xxx"}` 消息，校验 JWT 格式与 userId，防止网关被绕过（如内网直连）时路径 userId 被冒用。

---

## 四、数据存储设计

### 4.1 存储职责划分

| 存储 | 管理方 | 存什么 |
|------|--------|--------|
| **MySQL** | Java 服务 | 业务数据（用户/商品/订单/搭配记录/AI 任务记录/配额记录） |
| **Redis** | Java + Python | 缓存 + 用户照片会话级存储（TTL 30min）+ 配额计数 + 任务状态 + 冻结记录 |
| **Qdrant** | Python | 商品风格向量、用户行为向量、用户偏好向量 |
| **OSS** | Python + 前端 | 换装效果图、模特图、默认模特模板图、商家上传的商品白底图 |
| **RabbitMQ** | Java + Python | 异步任务队列 |

### 4.2 新增 MySQL 表

AI 相关表分布在两个数据库：

**hm-item 库（item-service / dashboard-service）**

| 表 | 用途 |
|----|------|
| `ai_task` | AI 任务记录。字段含 `task_type`（MODEL / OUTFIT_PRODUCT / OUTFIT_AGENT）、`status`（PENDING/PROCESSING/SUCCESS/FAILED/TIMEOUT）、`phase`、`generation_mode`（single/multi_outfit/multi_pose）、`enable_multi_agent`、`overall_score`、`star_rating`、`style_features`、`style_features_divergence`、`post_processed_image_url`、`agent_evaluations`、`outfit_combinations`、`combination_reasons`、`scene_results`、`pose_results`、`result_urls`、`item_categories` 等 |
| `ai_outfit_record` | AI 随心搭效果图入库，仅保存有用户操作的套装。`accepted` 三态：1=满意（加购/下单/保存到衣橱）、0=不满意（反馈调整）、2=未操作；含 `accepted_action`（cart/order/saved）、`accepted_type`、`feedback_summary`、`context_json`、`parent_task_id`、`credits_consumed` 等 |
| `ai_model_image_feedback` | AI 模特图评分与发布反馈。含 `feedback_type`（RATING/REJECT）、`star_rating`、`rating_tags`、`reject_reason`、`saved_to_pool`、`awarded_credits` 等 |
| `system_model_image` | 系统模特图池（全平台统一池，所有商家共用）。`source` 区分 0 商家上传 / 1 AI 任务后保存 / 2 平台运营 / 3 AI 自动生成；`gender` / `skin_tone` / `height` / `weight` / `age_range` / `body_type` / `style_tags` / `is_default` 等 |
| `size_chart_reference` | 店铺尺码对照参考表（shop_id=0 系统模板 + shop_id>0 店铺自维护），61 条预置系统模板 |
| `item`（扩展） | 新增 `target_gender`、`size_chart_id` 字段 |

**hm-user 库（user-service）**

| 表 | 用途 |
|----|------|
| `ai_credits_account` | 用户 credits 账户汇总（free_credits / paid_credits / 累计赠送/充值/消耗/回滚/奖励） |
| `ai_credits_recharge` | credits 充值记录（金额、credits、支付订单号幂等校验） |
| `user_body_profile` | 用户身体信息档案（性别/身高/体重/三围等，多档案支持） |
| `user_browse_history` | 用户商品详情页浏览记录（画像聚合的数据源之一） |
| `user_preference` | 用户偏好持久化（单一 JSON 字段 `preference_json`，存 dislikeColors/wantStyleTags/priceRange 等） |
| `user_wardrobe` | 用户衣橱。`item_type`：1=单品商品、2=自定义上传衣物图、3=全身自拍、4=AI 搭配效果图（accept 自动入库） |

### 4.3 Qdrant Collection 设计

| Collection | 向量维度 | 用途 |
|------------|----------|------|
| `item_style` | 1024 | 商品风格向量，payload 含 item_id/shop_id/category/color/season/style_tags/price/is_active/target_gender |
| `zmall_user_behavior` | 1024 | 用户行为向量（CART_ADD/ORDER_PLACE/OUTFIT_ACCEPT），payload 含 user_id/type/category/color/price/is_cross_gender |
| `zmall_user_preference` | 1024 | 用户显式偏好向量（dislike_colors / like_styles） |
| `zmall_user_episode` | 1024 | 情境记忆 |

品类中英文映射：上衣 ↔ tops，下装 ↔ bottoms，鞋 ↔ shoes，帽子 ↔ hat，包 ↔ bag，配饰 ↔ accessory。前端/MQ 用中文，Qdrant 存英文。

向量模型：文本向量使用通义 `text-embedding-v4`，图像向量使用 Jina CLIP v2，维度均为 1024（与 Qdrant collection 对齐）。

### 4.4 Redis Key 设计

```
# 照片会话管理（用户照片零持久化）
ai:photo:session:{userId}:{sessionId}        → 用户照片 base64（TTL 1800s）
ai:photo:session:url:{userId}:{sessionId}    → 照片 OSS URL（TTL 1800s，accept 入库用）

# 任务状态
ai:task:status:{taskId}                      → 任务状态 JSON（TTL 1h）
ai:task:idempotent:{taskId}                  → 幂等标记（TTL 1h，防 MQ 重复消费）

# Credits 积分制（Java user-service 管理）
ai:credits:free:{userId}                     → 赠送 credits 明细（Hash，field=过期时间戳秒，value=该批次剩余数量，30 天 TTL，FIFO 扣减）
ai:credits:paid:{userId}                     → 充值 credits 总余额（String，永久有效）
ai:credits:frozen:{userId}:{taskId}          → 预扣冻结记录（JSON 明细，TTL 1800s）

# 多轮反馈
ai:outfit:state:{task_id}                    → LangGraph state 快照（TTL 30min，首轮 SUCCESS 后保存，反馈轮重新加载）

# 并发控制
ai:outfit:session:{user_id}:count            → 「换一套」会话计数（TTL 30min）

# 外部工具缓存
ai:stock:{item_id}                           → 商品实时库存（TTL 5min）
ai:fashion_trend:{country}:{scene}:{style_tags} → 时尚潮流结果（TTL 600s）
ai:weather:{city}                            → 天气结果（TTL 1800s）

# 画像缓存
ai:profile:user:{userId}                     → 用户画像 JSON（TTL 24h，懒加载）
```

### 4.5 配额服务设计

配额逻辑全在 Java user-service，Python 不碰配额存储，只调接口。提供两套机制：

**Credits 积分制（`/credits/*`，CreditsController）**

| 接口 | 说明 |
|------|------|
| `POST /credits/deduct` | 预扣（FIFO：先扣赠送 30 天，再扣充值永久） |
| `POST /credits/confirm` | 确认消耗（删除冻结记录，不返还） |
| `POST /credits/rollback` | 回滚（按冻结明细原路返还） |
| `GET /credits/balance/{userId}` | 查询余额（含过期预警） |
| `POST /credits/recharge` | 充值（支付成功后调，幂等校验 payOrderNo） |
| `POST /credits/award` | 激励奖励（评分激励） |

**Quota 次数制（`/quota/*`，QuotaController，兼容保留）**

| 接口 | 说明 |
|------|------|
| `POST /quota/deduct` | 预扣（原子操作：先免费后付费） |
| `POST /quota/confirm` | 确认消耗 |
| `POST /quota/rollback` | 回滚释放 |

credits 扣减标准：

| 场景 | 类型 | credits |
|------|------|---------|
| 商品驱动（单套 VTON） | OUTFIT_VTON | 5 |
| 风格驱动阶段一（候选推荐） | OUTFIT_RECOMMEND | 2 |
| 风格驱动阶段二（VTON，5×N） | OUTFIT_VTON | 5×N |
| 风格驱动一阶段直出（推荐 + VTON Top3） | OUTFIT_DIRECT | 17 |
| 用户选定模式（1 套 VTON） | OUTFIT_VTON | 5 |
| AI 模特·single | MODEL | 5 |
| AI 模特·multi_outfit | MODEL | 18 |
| AI 模特·multi_pose | MODEL | 3 + 3 × poseCount |

其他规则：

- 用户首次使用 AI 随心搭赠送 50 credits，商家首次使用 AI 模特赠送 100 credits
- 充值方式：钱包余额扣减兑换（1 元 = 5 credits），套餐见 `ai_credits_recharge.package_id`
- 评分激励：商家评分 ≥4 星 + 发布奖励 1 credit，拒绝原因 ≥20 字奖励 1 credit，每日上限 5/3 次
- credits FIFO 扣减：优先扣赠送（30 天有效期），再扣充值（永久有效）
- 阶段一失败全额退还，阶段二 VTON 全部失败全额退还，部分失败不退还
- 预扣 → 成功确认 / 失败回滚，VTON 超时全额回滚
- 同一用户「换一套」每次生成都需扣费，会话计数仅用于并发控制

---

## 五、项目文件夹结构

```
ZMall/
├── zmall/                              # Java 微服务工程（现有）
│   ├── hm-common/                     # 公共模块
│   ├── hm-api/                        # Feign 客户端 + DTO（MQ 消息 + Python HTTP 直连 /items/internal/*）
│   ├── hm-gateway/                    # 网关（AI 路由 + 鉴权 + 限流）
│   ├── item-service/                  # 商品服务（AI 模特图生成/发布 + OSS STS + 尺码推荐）
│   ├── cart-service/                  # 购物车服务（套装加购）
│   ├── user-service/                  # 用户服务（配额/身体档案/衣橱/浏览记录）
│   ├── trade-service/                 # 交易服务（多店拆单）
│   ├── pay-service/                   # 支付服务
│   ├── social-service/                # 社交服务（搭配发布 Feed）
│   └── dashboard-service/             # 看板服务（AI 指标）
│
├── zmall-ai/                          # Python AI 服务工程（新增）
│   ├── ai-models/                     # FastAPI 业务后端（AI 模特图生成）
│   │   ├── app/
│   │   │   ├── api/v1/                # model.py / search.py / ws.py
│   │   │   ├── core/                  # 配置 + 安全 + 异常
│   │   │   ├── graphs/                # model_director_graph / multi_outfit_graph / multi_pose_graph
│   │   │   ├── subgraphs/             # 5 角色 Agent + 搭配组合推荐子图
│   │   │   ├── prompts/               # Prompt 模板
│   │   │   ├── schemas/               # 多 Agent state 定义
│   │   │   ├── services/              # model_service（链式 VTON）+ model_agent_service（多 Agent 入口）
│   │   │   ├── mq/model_consumer.py   # MQ 消费者（按 generationMode 路由）
│   │   │   └── main.py
│   │
│   ├── ai-outfit/                     # LangGraph Agent 服务（AI 随心搭）
│   │   ├── app/
│   │   │   ├── api/                   # outfit_agent.py / outfit_product.py / ws.py
│   │   │   ├── core/config.py         # 子 Agent 与外部工具开关
│   │   │   ├── graphs/outfit_graph.py # LangGraph 工作流
│   │   │   ├── schemas/               # agent_state.py / outfit.py
│   │   │   ├── services/              # agent_service.py / photo_session.py / profile_service.py
│   │   │   ├── tools/                 # intent_tool_executor / decision_tool_executor / agent_tools / nodes
│   │   │   ├── mq/                    # item_sync_consumer / item_sync_dlq_consumer / user_behavior_consumer
│   │   │   └── main.py
│   │   └── scripts/                   # index_items / reconcile_mysql_qdrant / download_unsplash_images
│   │
│   ├── shared/                        # 共享客户端库
│   │   ├── qdrant_client/             # client / indexer / searcher / category_mapping / user_behavior / user_preference / user_episode
│   │   ├── oss_client/                # OSS 封装
│   │   ├── model_client/              # vton_client / gen_client / refiner_client / llm_client / embed_client
│   │   ├── java_client/               # Java 服务调用（recommend_size_by_item 等）
│   │   ├── external_services/         # price / inventory / fashion_trend / weather
│   │   ├── mq_client/                 # RabbitMQ 客户端（consumer/producer）
│   │   ├── ws_manager/                # WebSocket 连接管理（按 userId 维护）
│   │   ├── db_client/                 # MySQL 客户端
│   │   ├── nacos_register/            # Nacos 服务注册
│   │   ├── nacos_discovery/           # Nacos 服务发现
│   │   ├── distributed_lock/          # 分布式锁
│   │   └── outfit_common/             # 穿搭公共工具（image_compose / session_counter）
│   │
│   ├── requirements.txt
│   └── README.MD
│
├── zmall-nginx/                       # 前端
│   └── html/
│       ├── zmall-portal/              # 用户端
│       ├── zmall-admin/               # 管理端
│       └── zm-refresh-admin/          # 刷新版管理端
│
├── docs/                              # 项目文档
│   ├── AI功能需求分析.md
│   ├── AI功能后端架构方案.md          # 本文件
│   └── AI核心功能设计.md
│
├── db/                                # 数据库脚本（hm-item / hm-user 等）
└── README.MD
```

设计要点：`zmall-ai/` 独立于 `zmall/`，Java 与 Python 工程隔离、独立构建部署；ai-models 与 ai-outfit 按功能模块拆分、独立扩缩容；shared 作为共享库只写一次；两个 Python 服务注册 Nacos，由 Gateway 统一路由。

---

## 六、Gateway 路由配置

AI 相关路由（`hm-gateway/src/main/resources/application.yml`）：

```yaml
# AI 模特图结果轮询 + 模特图 WS
- id: ai-models
  uri: lb://ai-models
  predicates:
    - Path=/api/v1/model/result/**,/ws/model/**
# AI 随心搭（商品驱动 + 风格驱动）+ 换装 WS
- id: ai-outfit
  uri: lb://ai-outfit
  predicates:
    - Path=/api/v1/outfit/generate,/api/v1/outfit/photo,/api/v1/outfit/result/**,/api/v1/outfit/agent/**,/ws/ai/**
```

user-service 路由谓词（配额 / 身体档案 / 浏览记录 / 衣橱）：

```yaml
- id: user
  uri: lb://user-service
  predicates:
    - Path=/users/**,/addresses/**,/credits/**,/quota/**,/body-profile/**,/browse-history/**,/wardrobe/**
```

说明：AI 随心搭两种模式统一在 `/api/v1/outfit/` 命名空间，全部路由到 ai-outfit（9001）；WebSocket 按功能区分，`/ws/ai/**`（换装推送）到 ai-outfit，`/ws/model/**`（模特图推送）到 ai-models。AI 模特图生成/发布走 item-service 的 `/items/admin/ai-model/*`（被 `/items/**` 路由覆盖）。

---

## 七、稳定性与可靠性设计

### 7.1 限流与超时

| 层级 | 机制 | 配置 |
|------|------|------|
| Gateway | 接口限流 | AI 接口单用户 10 次/小时；照片上传接口单独限流；结果轮询接口放宽（幂等 GET） |
| ai-models | 内部令牌桶 | 模型 API 并发 ≤ 5 |
| ai-outfit | LangGraph 超时 | 单次推荐 ≤ 60s |
| MQ 消费 | 超时补偿 | DLQ + 重试 backoff [2,4,8]s，MAX_RETRIES=3，超限 nack 进死信队列，DLQ 再试 1 次 |
| 分布式锁 | 看门狗续期 | Redis SET NX PX，每 10s 续租，最长续到 30s（对齐 Redisson RLock 语义） |
| Redis 任务状态机 | 兜底 | `ai:task:status:{taskId}` + Java 超时调度器扫描 ai_task 表标记 TIMEOUT 并回滚配额 |

### 7.2 降级策略

| 场景 | 降级方案 |
|------|---------|
| ai-models / ai-outfit 不可用 | 消息滞留队列，Java 超时调度器 11min 扫描 ai_task 标记 TIMEOUT 并回滚配额 |
| 模型 API 超时 | 返回商品平铺组合图 + 稍后查看 |
| Qdrant 检索失败 | 降级为按销量推荐 Top3 |
| 用户照片质量不达标 | 降级为默认模特照片换装 |
| LangGraph 推理超时 | 标记 FAILED + WS 推送失败 + MQ 通知回滚配额 |
| WebSocket 断连 | 前端轮询兜底（最长 60s） |
| multi_outfit 单套 VTON 失败 | 其他套正常返回，失败套标记 FAILED |
| multi_pose 图生图失败 | 降级复用 VTON 基准图，保证至少 1 张可用 |
| multi_outfit 搭配组合推荐失败 | 降级笛卡尔积（每件独立成套），保证 1-4 套组合 |
| weather_service 不可用 | 按月份推断季节 |
| inventory_service 不可用 | 返回空 dict，调用方不过滤候选 |
| price_service 不可用 | 返回默认 balance_score=0.5 |
| 子 Agent LLM 超时/未配置 | IntentAgent 拼 query_text 不生成向量；DecisionAgent 保留原 Top3 |
| 尺码推荐三级回退全部未命中 | 返回空列表，前端提示暂无尺码参考表 |

### 7.3 幂等性与超时补偿

| 场景 | 方案 |
|------|------|
| MQ 消息重复消费 | 消费前查 `ai_task.status`，已终态跳过（ack 确认） |
| WebSocket 重复推送 | 前端按 taskId 去重 |
| 配额确认/回滚重复调用 | Redis 冻结记录删除前检查存在性 |
| Python 生成超 5min 无响应 | Java 定时任务扫描 ai_task 标记 TIMEOUT + 回滚配额 |
| 模型 API 瞬时失败 | 重试 3 次（指数退避 2s/4s/8s），超 3 次标记 FAILED |
| MQ 消息丢失 | 消息持久化 + 消费 ack + 定时任务对账 |

### 7.4 数据一致性

| 场景 | 方案 |
|------|------|
| Java → Python 异步任务 | RabbitMQ 消息持久化 + 消费确认（ack） |
| AI 任务状态同步 | Python 写 Redis 任务状态 + WS 推送 + MQ 通知 Java 写 MySQL ai_task |
| OSS 图片上传与记录 | 先传 OSS → 写 MySQL → 失败时 OSS 定时清理孤儿文件 |
| Qdrant 与 MySQL 数据同步 | 商品上下架时 Java 发 MQ → Python 消费更新 Qdrant，配对账脚本回填 |
| 配额预扣与确认 | Redis 原子预扣 + 冻结记录 TTL + 定时任务对账 |

### 7.5 监控告警

| 指标 | 阈值 | 告警方式 |
|------|------|---------|
| AI 接口 P95 响应时间 | > 5s | 钉钉/邮件 |
| 换装生成失败率 | > 5% | 钉钉 |
| 模型 API 调用失败率 | > 10% | 电话 |
| RabbitMQ 队列堆积 | > 100 条 | 钉钉 |
| Qdrant 内存使用 | > 80% | 钉钉 |
| Python 服务实例存活 | Nacos 心跳丢失 | 电话 |
| ai_task 表 PROCESSING 超 5min | 定时任务扫描 | 钉钉 + 自动回滚配额 |

---

## 八、安全设计

### 8.1 认证与授权

| 层级 | 机制 |
|------|------|
| 前端 → Gateway | JWT Token（hmall.jks） |
| Gateway → Python | 透传 `user-info` 请求头（userId） |
| Python 内部 | 中间件解析 `user-info`，未携带则拒绝 |
| 商家端 AI 模特 | 校验 shop_id 归属 |
| 内部调用 | Python → Java 服务间调用，携带服务间签名（Nacos 内网信任） |

#### 8.1.1 IDOR 防护（任务归属校验）

任务操作接口校验任务归属，防止拿到他人 taskId 越权操作：

| 函数 | 校验逻辑 |
|------|---------|
| `_load_state(task_id, expected_user_id)` | 从 Redis 读 state 后校验 `state["user_id"] == expected_user_id`，不一致返回 403 |
| `get_task_result(task_id, expected_user_id)` | 从 Redis 读 task status 后校验 `status["userId"] == expected_user_id`，不一致返回 403 |

userId 来源统一从 Gateway 透传的 `user-info` header 获取（经 AuthMiddleware 解析写入 `request.state.user_id`），不信任客户端传入的 userId。

### 8.2 用户照片安全

| 风险 | 防护措施 |
|------|---------|
| 照片泄露 | 仅存 Redis（TTL 30min），不落 OSS/MySQL，加密传输（WSS） |
| 照片被爬 | 接口限流（10 次/小时）+ 人机验证（可选） |
| 未成年人照片 | 上传前年龄校验（user-service 查生日）+ 人脸年龄估计（可选） |
| 他人照片滥用 | 授权同意书明确仅上传本人照片 + 投诉举报通道 |

### 8.3 商家前端 OSS 直传安全

商家上传商品图流程：

1. 前端 → Java：`GET /api/v1/oss/sts` 获取 STS 临时凭证（有效期 15min）
2. Java 调阿里云 STS AssumeRole，返回 AccessKeyId / AccessKeySecret / SecurityToken / Expiration
3. 前端用 STS 直传 OSS → 获取 OSS URL
4. 前端把 OSS URL 发给后端（不经过 Java 中转文件流）

安全要点：STS Role 最小权限，只能上传到指定目录、只能写不能读；文件名规则 `{目录}/{shopId}/{itemId}/{timestamp}.jpg`；前端校验 JPG/PNG ≤5MB，后端二次校验。

### 8.4 模型 API 密钥管理

密钥从 Nacos 配置中心拉取，不硬编码。虚拟试衣、图像生成、OSS 等密钥统一由 Nacos 下发，Python 侧按需读取。

---

## 附录 · AI 模型清单

| 用途 | 模型 |
|------|------|
| 虚拟试衣（VTON） | 千问 `aitryon-plus` |
| 图像精修（图生图后处理） | 千问 `aitryon-refiner` |
| 配饰虚拟穿戴 / 人物姿态调整 | 千问 `wan2.7-image`（非 pro 版） |
| LLM 文本 / 视觉理解 | 千问 `qwen3.5-flash` |
| 文本向量编码 | 通义 `text-embedding-v4`（1024 维） |
| 图像向量编码 | Jina CLIP v2（1024 维） |

模型客户端封装在 `shared/model_client/`，方法签名统一，底层模型可独立替换，调用方无需改动。
