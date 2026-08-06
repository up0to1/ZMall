# AI 随心搭测试方案

> 目标：通过节点级埋点 + Prometheus 指标 + 日志文件 + 前端 console，在单点测试和 JMeter 压测时精准定位哪个环节慢或失败。

---

## 1. 工作流节点概览

AI 随心搭（风格驱动模式）LangGraph 工作流包含以下节点，按执行顺序：

| 节点名 | 装饰器标识 | 职责 | 主要外部调用 |
|--------|-----------|------|-------------|
| 节点1 意图理解 | `intent` | 解析风格/场景/颜色/note → 生成检索向量 + 加载模特图 | LLM (react_intent/parse_note/hyde/analyze_photo), Embed API |
| 节点1.5 用户选定 | `wardrobe` | 用户从衣橱/购物车选定商品时直接构建搭配 | JavaClient.get_items_by_ids |
| 节点2 Qdrant检索 | `search` | 按品类在 Qdrant 检索互补商品 | Qdrant 向量检索 |
| 节点3 组合决策 | `outfit` | 从候选商品中组合 3 套搭配 + LLM Top3 选择 | LLM (select_outfits) |
| 节点3.5 Reflection | `reflection` | 质检 3 套搭配的颜色/风格/季节 | LLM (reflect) |
| 节点4 VTON生成 | `vton` | 为每套搭配并行生成换装图（仅阶段二 select/accept 执行） | VTON API (aitryon-plus) |
| 精修（可选） | `refine` | 对 VTON 结果做二次精修 | Refiner API (aitryon-refiner) |
| 节点5 OSS上传 | `upload` | 上传换装图到 OSS，组装最终结果 | OSS |

反馈轮（用户提交反馈后）会重新走 节点1 → 节点2 → 节点3 → 节点3.5 → 节点5，跳过节点4 VTON（VTON 仅在阶段二 select/accept 时执行）。

---

## 2. 埋点与可观测性

### 2.1 日志文件

**位置**: `zmall-ai/ai-outfit/logs/ai-outfit.log`（50MB 轮转，保留 5 个备份）

**配置**: `ai-outfit/app/main.py` 使用 `RotatingFileHandler` 同时输出到文件和控制台。

**查看方式**: 测试后直接查看日志文件，搜索 `taskId` 串联整个请求链路。

### 2.2 节点级日志

每个节点执行完成/失败时输出一条 `[节点埋点]` 日志：

```
[节点埋点] intent SUCCESS: taskId=abc123, duration_ms=3500
[节点埋点] search SUCCESS: taskId=abc123, duration_ms=800
[节点埋点] outfit SUCCESS: taskId=abc123, duration_ms=5200
[节点埋点] vton FAILED: taskId=abc123, duration_ms=180000, error=VTON API timeout
```

**定位问题**: 搜索 `[节点埋点]` 即可看到所有节点的执行耗时和状态，快速定位哪个节点慢或失败。

### 2.3 Prometheus 指标

**端点**: `GET http://localhost:{port}/metrics`（ai-outfit 服务端口）

**核心指标**:

| 指标名 | 类型 | 标签 | 用途 |
|--------|------|------|------|
| `ai_agent_workflow_node_total` | Counter | `status`, `node` | 节点执行次数（SUCCESS/FAILED） |
| `ai_agent_workflow_node_duration_seconds` | Histogram | `node` | 节点耗时分布 |
| `ai_llm_call_total` | Counter | `action`, `status` | LLM 调用次数 |
| `ai_llm_call_duration_seconds` | Histogram | `action` | LLM 调用耗时分布 |
| `ai_vton_call_total` | Counter | `status`, `stage` | VTON 调用次数 |
| `ai_vton_call_duration_seconds` | Histogram | — | VTON 调用耗时分布 |

**查看方式**:

```bash
# 查看所有节点指标
curl http://localhost:{port}/metrics | findstr "ai_agent_workflow_node"

# 查看 LLM 调用指标
curl http://localhost:{port}/metrics | findstr "ai_llm_call"

# 查看 VTON 调用指标
curl http://localhost:{port}/metrics | findstr "ai_vton_call"
```

**LLM action 列表**: `parse_note`, `hyde`, `analyze_photo`, `parse_feedback`, `select_outfits`, `reflect`, `react_feedback`, `react_intent`, `react_decision`

**VTON stage 列表**: `create`（创建任务）, `poll`（轮询状态）, `download`（下载结果）, `chain_item`（链式 VTON）

### 2.4 前端 console 日志

在浏览器 DevTools Console 中，每次收到 WS 消息会输出：

```
[WS] type=OUTFIT_AGENT, status=SUCCESS, taskId=abc123
```

**用途**: 确认后端推送的消息类型和状态是否正确，判断问题是出在后端生成还是前端展示。

---

## 3. 单点测试策略

### 3.1 测试环境准备

1. 启动依赖服务：MySQL、Redis、RabbitMQ、Qdrant、Nacos
2. 启动微服务：hm-gateway、hm-user、hm-item、hm-cart、hm-trade、ai-outfit
3. 确认 `.env` 中千问 API Key 已配置（`LLM_API_KEY`）
4. 确认 `qwen_refiner_enabled=True`（如需测试精修）
5. 打开浏览器 DevTools → Console + Network 面板

### 3.2 风格驱动模式测试用例

#### 用例 1: 基础风格推荐（无照片）

**操作**: 选择风格标签（如"通勤"）→ 点击"AI 搭配"

**验证点**:
- Console: `[WS] type=OUTFIT_AGENT, status=SUCCESS` 是否出现
- 日志: 搜索 `taskId`，确认 节点1→2→3→3.5→5 全部 SUCCESS（首轮阶段一不含 VTON / 换装图）
- 指标: `ai_agent_workflow_node_total{status="SUCCESS"}` 各 node 各 +1
- 前端: 3 套搭配图是否正常展示

**常见问题**:
- 节点1 FAILED → 检查 LLM API Key / Embed API 是否正常
- 节点2 FAILED → 检查 Qdrant 是否有商品数据
- 节点4 FAILED → 检查 VTON API 是否可用 / OSS 是否配置

#### 用例 2: 带照片的风格推荐

**操作**: 上传真人照片 + 选择风格标签 → 点击"AI 搭配"

**额外验证点**:
- 日志: 搜索 `analyze_photo`，确认 LLM 视觉特征分析完成
- 日志: 搜索 `target_gender`，确认性别过滤生效
- 指标: `ai_llm_call_total{action="analyze_photo",status="success"}` +1

#### 用例 3: 反馈轮 - 替换品类

**操作**: 在推荐结果页 → 输入"换一双鞋" → 提交反馈

**验证点**:
- 日志: 搜索 `[节点埋点]`，确认反馈轮节点重新执行
- 日志: 搜索 `react_feedback` 或 `parse_feedback`，确认反馈解析正确
- 前端: 鞋子是否被替换

#### 用例 4: 反馈轮 - 精修

**操作**: 在推荐结果页 → 输入"精修第1套" → 提交反馈

**验证点**:
- 日志: 搜索 `[精修]`，确认精修流程执行
- 指标: `ai_agent_workflow_node_total{node="refine"}` +1
- 前端: 换装图是否变得更清晰/还原度更高

#### 用例 5: 用户选定模式

**操作**: 从衣橱/购物车选择商品 → 点击"AI 搭配"

**验证点**:
- 日志: 搜索 `[节点埋点] wardrobe`，确认跳过了 Qdrant 检索和组合决策
- 前端: 直接展示选定商品的搭配结果

### 3.3 问题定位流程

```
前端结果异常
  ├─ Console 有 [WS] 消息？
  │   ├─ 是 → 后端推送了，问题在前端展示
  │   └─ 否 → 后端未推送，查看日志
  │       ├─ 日志有 [节点埋点] FAILED？
  │       │   ├─ 是 → 定位到具体节点，查看 error 信息
  │       │   │   ├─ intent FAILED → LLM/Embed API 问题
  │       │   │   ├─ search FAILED → Qdrant 问题
  │       │   │   ├─ outfit FAILED → LLM 决策问题
  │       │   │   ├─ vton FAILED → VTON API 问题（查看 stage）
  │       │   │   └─ upload FAILED → OSS 问题
  │       │   └─ 否 → 节点都 SUCCESS，但结果不对
  │       │       └─ 查看节点内详细日志（搜索 [节点N]）
  │       └─ 日志无 [节点埋点]？
  │          └─ 请求未到达 ai-outfit，检查网关/认证
  └─ Console 无 [WS] 消息？
      └─ 检查 WS 连接是否建立（Network 面板 WS 标签）
```

### 3.4 性能分析

测试后查看 `/metrics` 端点，关注：

```bash
# 节点耗时 P95（哪些节点慢）
curl http://localhost:{port}/metrics | findstr "ai_agent_workflow_node_duration_seconds_quantile"

# LLM 调用耗时 P95
curl http://localhost:{port}/metrics | findstr "ai_llm_call_duration_seconds_quantile"

# VTON 调用耗时 P95
curl http://localhost:{port}/metrics | findstr "ai_vton_call_duration_seconds_quantile"

# 失败率
curl http://localhost:{port}/metrics | findstr "ai_agent_workflow_node_total"
# 计算 FAILED / (SUCCESS + FAILED) 得到失败率
```

**预期耗时参考**:
- 节点1 intent: 2-8s（含 LLM ReAct 多轮 + Embed）
- 节点2 search: 0.5-2s（Qdrant 向量检索）
- 节点3 outfit: 3-10s（含 LLM select_outfits）
- 节点3.5 reflection: 2-5s（LLM 自检）
- 节点4 vton: 30-120s（VTON API 异步任务，3 套并行；仅阶段二 select/accept 执行）
- 节点5 upload: 1-3s（OSS 上传）
- **总计**: 阶段一（节点1-5 不含 VTON）10-30s + 阶段二 VTON 30-120s（首轮）；反馈轮无 VTON，更快

---

## 4. JMeter 压测策略

### 4.1 测试目标

- 验证并发下各节点的稳定性和耗时
- 发现资源瓶颈（LLM API 限流、VTON API 并发限制、Qdrant 连接池）
- 验证 WS 消息推送的可靠性

### 4.2 JMeter 测试计划要点

1. **setUp 线程组**: 清除 Redis/MySQL 测试数据，确保环境干净
2. **主线程组**:
   - 线程数：5-10（AI 功能不建议高并发，千问 API 有 QPS 限制）
   - Ramp-up: 5s
   - 循环次数：1
3. **请求**:
   - POST `/api/v1/outfit/agent/recommend`（风格驱动模式）
   - Body: `{"styleTags":["通勤"],"sceneDesc":"日常通勤"}`
4. **结果验证**:
   - 轮询 `GET /api/v1/outfit/agent/result/{taskId}` 直到 status=SUCCESS 或 FAILED
   - 超时设置 300s（VTON 耗时较长）

### 4.3 压测后分析

1. **JMeter 结果树**: 查看 HTTP 响应码和响应时间
2. **ai-outfit 日志**: `logs/ai-outfit.log`，搜索各 taskId 的 `[节点埋点]` 日志
3. **Prometheus 指标**: 在压测期间持续采集 `/metrics`

**关键分析**:
- `ai_agent_workflow_node_total{status="FAILED"}` 压测后 FAILED 是否增加 → 并发导致失败
- `ai_llm_call_duration_seconds` P95 是否显著升高 → LLM API 限流
- `ai_vton_call_duration_seconds` P95 是否显著升高 → VTON API 排队
- `ai_vton_call_total{status="failed",stage="create"}` → VTON API 并发限制

### 4.4 JMeter 注意事项

- **并发数控制**: 千问 API 有 QPS 限制，建议并发不超过 10
- **超时设置**: HTTP Request 超时设为 300s（VTON 异步任务耗时长）
- **结果目录**: 使用纯英文目录（如 `test-results/outfit-agent/`）
- **数据重置**: 每轮测试前清除 Redis 和 MySQL 测试数据
- **SyncTimer**: 如需瞬时并发，groupSize 与线程数匹配，分 5 批释放

---

## 5. 修改文件清单

| 文件 | 修改内容 |
|------|---------|
| `shared/metrics/__init__.py` | 新增节点级、LLM、VTON 指标定义 + record 函数 |
| `ai-outfit/app/tools/nodes.py` | 新增 `_trace_node` 装饰器，应用到 7 个节点函数；`refine_vton_result` 内联埋点 |
| `shared/model_client/llm_client.py` | 8 个 LLM 方法添加 `record_llm_call` 指标 |
| `shared/model_client/vton_client.py` | `QwenVtonClient` 4 个方法添加 `record_vton_call` 指标 |
| `ai-outfit/app/main.py` | 添加 `RotatingFileHandler` 日志输出到文件 |
| `zmall-nginx/html/zmall-portal/outfit-result.html` | `handleMessage` 添加 WS 消息 console.log |
| `zmall-nginx/html/zmall-portal/outfit-product.html` | `handleMessage` 添加 WS 消息 console.log |
