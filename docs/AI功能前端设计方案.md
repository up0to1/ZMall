# ZMall 前端架构方案（AI 扩展）

本文档基于 `zmall-nginx` 实际前端代码编写，覆盖两个 AI 功能模块的前端架构：AI 随心搭（用户端 `zmall-portal`）与 AI 模特（商家端 `zm-refresh-admin`）。内容包括总体架构、页面结构、组件设计、接口调用、WebSocket 接入、状态管理与视觉规范。

配套文档：
- [AI核心功能设计.md](./AI核心功能设计.md)
- [AI功能后端架构方案.md](./AI功能后端架构方案.md)
- [AI功能需求分析.md](./AI功能需求分析.md)

---

## 一、总体架构

### 1.1 双前端分离

ZMall 前端由三个独立站点组成，AI 功能落地在其中的两个上：

| 站点 | 端口 | 技术栈 | 承载 AI 功能 | 用户角色 |
|------|------|--------|--------------|----------|
| `zmall-portal` | 18080 | 多页面 HTML + Vue 2 CDN | AI 随心搭（含衣橱、搭配历史、浏览记录） | C 端消费者 |
| `zm-refresh-admin` | 18082 | 单页 HTML + Vue 2 + Element UI | AI 模特（生成、任务列表、模特图池） | B 端商家 |
| `zmall-admin` | 18081 | 多页面 HTML + Vue 2 + Element UI | 不承载 AI 功能 | B 端商家历史站点 |

两个承载 AI 功能的站点物理隔离、无代码共享：导航、布局、组件、CSS、token 存储 key 均独立。唯一共享点在后端 credits 配额池，商家维度 `shopId=userId` 与用户维度 `userId` 共用 `ai_credits_account` 表。

### 1.2 技术栈

| 项 | zmall-portal（用户端） | zm-refresh-admin（商家端） |
|----|------------------------|----------------------------|
| 框架 | Vue 2.x CDN（`./js/vue.js`） | Vue 2.x CDN + Element UI 2.x |
| 模板 | 一个功能一个 HTML 文件，每页独立 `new Vue({el:"#app"})` | 单 `index.html`，通过 `currentMenu` + `v-if` 切换 |
| 状态管理 | `localStorage` + 全局 `util`（`common.js`） | `localStorage` + 全局 `ZM` 对象 + `this.$root.currentMenu` |
| HTTP | axios，`baseURL="/api"`，拦截器注入 token | axios 实例 `ZM.http`，`baseURL="/api"`，注入 `zm-admin-token` |
| UI | 自定义 CSS，无组件库 | Element UI（el-menu/el-dialog/el-table/el-rate 等） |
| 鉴权 | JWT `localStorage.token`，401 跳 `/login.html` | JWT `localStorage.zm-admin-token`，401 跳 `/login.html` |
| 路由 | 多页面跳转 `location.href`，无 history 栈 | `currentMenu` 字符串切换，无 URL 变化 |

### 1.3 nginx 路由

`zmall-nginx/conf/nginx.conf` 按端口区分三个站点。以用户端 18080 为例：

```nginx
server {
    listen 18080;                  # 用户端
    location / { root html/zmall-portal; }

    # /api/v1/ 不 rewrite，原路径转发到网关（匹配 /api/v1/** Controller）
    location /api/v1/ {
        proxy_pass http://localhost:8080;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    }
    # /api 去前缀后转发（rewrite /api/(.*) → /$1 break）
    location /api {
        rewrite /api/(.*) /$1 break;
        proxy_pass http://localhost:8080;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    }
    # /ws/ WebSocket 透传，长连接读超时 3600s
    location /ws/ {
        proxy_pass http://localhost:8080;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_read_timeout 3600s;
    }
}
```

商家端 18082 采用同样的 `/api` 去前缀转发，并让 `/css/`、`/js/`、`/img/`、`/fonts/` 等静态资源直接由 nginx 返回不经过鉴权。

**路由要点**：
- `/api/v1/` 不 rewrite，匹配 Spring Boot `/api/v1/**` 控制器（如 `/api/v1/outfit/**`）
- `/api` 去前缀后转发，匹配 `/items/**`、`/credits/**`、`/carts/**` 等接口
- `/ws/` WebSocket 透传，`proxy_read_timeout 3600s` 适配 AI 长任务推送

新增 AI 页面无需改 nginx：HTML 直接放入对应 `html/` 目录，API 走 `/api` 或 `/api/v1/` 反向代理，WS 走 `/ws/` 透传。

### 1.4 功能边界与配额池共享

```
┌────────────────────────────────────────────────────┐
│              用户端 zmall-portal · AI 随心搭          │
│  ├─ 风格驱动（一阶段直出：检索 + 决策 + VTON）        │
│  ├─ 用户选定（衣橱/购物车/订单/搜索挑单品直接 VTON）   │
│  ├─ 商品驱动（商品详情页入口，直接 VTON）             │
│  ├─ 衣橱管理 / 搭配历史 / 浏览记录                   │
│  └─ Credits 余额与充值                              │
└──────────────────────────┬─────────────────────────┘
                           │ 共享 ai_credits_account
                           ▼
┌────────────────────────────────────────────────────┐
│           商家端 zm-refresh-admin · AI 模特           │
│  ├─ 生成模特图（single / multi_pose / multi_outfit） │
│  ├─ 任务列表（WS 实时刷新）                          │
│  ├─ 模特图池管理（CRUD + 可见性）                    │
│  ├─ 评分 / 发布 / 拒绝链式流程                       │
│  └─ Credits 与充值（与用户端共用结构）               │
└────────────────────────────────────────────────────┘
```

- AI 随心搭是消费者场景：用户上传照片或选风格，AI 生成换装效果图并引导加购、下单
- AI 模特是商家工具：商家选商品选模特图，AI 生成商品展示模特图，可发布到商品主图
- 两侧独立开发、独立部署，共享后端 `/credits/**` 接口和 `ai_credits_account` 表

---

## 二、AI 随心搭 · 用户端设计

### 2.1 功能定位与两种入口

AI 随心搭为 C 端用户提供两类入口：

| 入口 | 模式 | credits | 生成路径 |
|------|------|---------|----------|
| 风格驱动 | `platform` 全平台 / 指定店铺 | 17（一阶段直出，推荐 + VTON 合并） | `POST /v1/outfit/agent/recommend` |
| 用户选定 | `picked` 从衣橱/购物车/订单/商品挑选 | 5 | `POST /v1/outfit/agent/recommend` |
| 商品驱动 | 商品详情页单商品直接生成 | 5 | `POST /v1/outfit/generate` |

三条路径共享照片会话、credits 余额、衣橱、搭配历史与充值入口，但 Vue 实例、组件、接口、CSS 完全分离。

### 2.2 页面结构与跳转关系

`zmall-portal` 下共 8 个 AI 相关 HTML 页面：

| HTML | 职责 | 入口来源 | 主要跳转去向 |
|------|------|----------|--------------|
| outfit-agent.html | 风格驱动 / 用户选定的表单提交页 | top.js「AI 搭配」 | `POST /v1/outfit/agent/recommend` → outfit-result.html |
| outfit-product.html | 商品驱动结果页 | item-detail.html「AI 随心搭」按钮 | WS 推送结果后停留在本页 |
| outfit-result.html | 风格驱动结果展示页（VTON 结果 + 满意/不满意） | outfit-agent 提交跳转 | accept → 购物车 / 下单 / 衣橱 / 搭配历史 |
| wardrobe.html | 我的衣橱（按 itemType 分类） | top.js「我的衣橱」 | wardrobe-upload / outfit-agent / outfit-history |
| wardrobe-upload.html | 衣橱添加页 | wardrobe「+ 添加衣橱」 | `POST /wardrobe` → wardrobe.html |
| outfit-history.html | 搭配历史列表（6 状态页签） | top.js 间接 / outfit-result | 一键加购 / 删除 |
| item-detail.html | 商品详情页（已改造） | 全站商品链接 | 「AI 随心搭」→ outfit-product.html |
| browse-history.html | 浏览记录管理（查看/删除/清空） | top.js「浏览记录」 | 点击记录 → item-detail.html |

跳转关系：

```
top.js「AI 搭配」 ─→ outfit-agent.html ─recommend→ outfit-result.html
                                             ├─ accept ─→ 购物车 / 下单 / 衣橱 / 搭配历史
                                             └─ 重新填写 ─→ outfit-agent.html

item-detail.html ─AI 随心搭─→ outfit-product.html ─generate→ WS 推送结果

wardrobe.html ⇄ wardrobe-upload.html      outfit-result（accept 后写入衣橱）
```

### 2.3 顶部导航与商品详情页入口

- `top.js` 在「秒杀」与「订单」等之间加入「AI 搭配」「我的衣橱」「浏览记录」三个链接，AI 搭配链接加粗标红高亮
- `item-detail.html` 详情页操作区加入「AI 随心搭」与「加入衣橱」两个按钮，库存 ≤ 0 时禁用
  - AI 随心搭未登录跳 `/login.html`，已登录跳 `/outfit-product.html?id={itemId}`
  - 加入衣橱前先 `GET /wardrobe/my-item-ids` 判断是否已在衣橱，更新按钮态

### 2.4 风格驱动模式（outfit-agent）

`outfit-agent.html` 是折叠式表单页，核心字段包括 credits、照片会话、系统模特选择、身体档案、天气城市、风格标签、颜色、品类、指定店铺、场景描述、自然语言备注。表单草稿 1 小时持久化到 `localStorage.outfit_form_draft`，`created` 钩子自动恢复。

表单提交 `POST /v1/outfit/agent/recommend`，分两类提交内容：

- 风格驱动（platform）：提交 `styleTags / color / categories / shopIds / sceneDesc / note / photoSessionKey / systemModelId / systemModelGender`，风格标签、颜色、场景、备注至少填一项
- 用户选定（picked）：通过挑选模态框从衣橱（`/wardrobe`）、购物车（`/carts`）、已购订单（`/orders/user/page`）、商品搜索选好单品后提交，单品上限 5 件、同品类互斥

提交成功后跳转 `outfit-result.html?taskId=xxx&stage=vton`。

### 2.5 商品驱动模式（outfit-product）

`outfit-product.html` 由商品详情页进入，针对单商品直接生成 VTON 换装图：

1. 加载主商品 `GET /items/{itemId}`
2. 照片准备：默认选系统模特，或通过 `POST /v1/outfit/photo` 上传真人照片取得照片会话 Key
3. 提交前强制校验身体档案（`GET /body-profile`），未登记时阻断并引导去 wardrobe.html 登记
4. `POST /v1/outfit/generate`（扣 5 credits），启动 Loading 浮层 + WebSocket
5. WS 推送 `OUTFIT_PRODUCT` 后渲染结果：主商品锁定不可换、互补商品可换、可批量加购、可反馈调整

### 2.6 结果展示页（outfit-result）

`outfit-result.html` 展示 VTON 效果图及满意 / 不满意操作。采用一阶段直出，进入时以 `stage=vton` 展示换装结果。

满意操作区：
- 加购整套：`POST /v1/outfit/agent/accept`（acceptedAction=cart），先经尺码确认弹窗（`POST /items/size-chart/recommend-batch` 推荐尺码），再批量写入 `/carts`
- 立即下单：accept（acceptedAction=order）后携带搭配上下文跳转订单确认页结算
- 保存到衣橱：`POST /items/outfit/records`（accepted=1，写入 `user_wardrobe` itemType=4）

不满意操作区：
- 反馈调整：弹 feedback-dialog，`POST /v1/outfit/agent/feedback`，扣 5 credits / 轮，最多 3 轮
- 直接退出：写入 `ai_outfit_record`（accepted=0）
- 标记不满意时同步 `DELETE /items/outfit/wardrobe/by-task` 回收已入衣橱的搭配条目

结果页状态恢复：进入时根据 URL 中 `taskId` 调 `GET /v1/outfit/agent/result/{taskId}` 拉取上一次结果与轮次信息，并用 `history.replaceState` 同步到 URL 支持刷新与分享。

### 2.7 组件设计

`zmall-portal/js/components/` 下 5 个 AI 随心搭组件：

| 文件 | 类型 | 注册名 | 职责 |
|------|------|--------|------|
| ai-outfit-ws.js | 工具类 | AiOutfitWS / AiOutfitPoller / AiOutfitLoading | WS 与轮询降级、Loading 浮层 |
| credits-bar.js | Vue 组件 | credits-bar | 顶部余额条 + 充值入口 |
| recharge-dialog.js | Vue 组件 | recharge-dialog | 4 档套餐充值对话框 |
| feedback-dialog.js | Vue 组件 | feedback-dialog | 风格驱动多轮反馈对话框 |
| product-feedback-dialog.js | Vue 组件 | product-feedback-dialog | 商品驱动多轮反馈对话框 |

recharge-dialog 套餐：

| 套餐 | 金额 | credits | 规则 |
|------|------|---------|------|
| 1 | 10 元 | 50 | 无加成 |
| 2（推荐） | 20 元 | 110 | 基础 100 + 加成 10 |
| 3 | 50 元 | 300 | 基础 250 + 加成 50 |
| 4 | 100 元 | 650 | 基础 500 + 加成 150 |

充值规则 1 元 = 5 credits，首充额外赠送 50 credits，接口 `POST /credits/recharge`（金额、支付订单号、套餐 ID）。充值入口从个人中心钱包发起，经支付页完成回调。

### 2.8 WebSocket 与轮询降级

#### 2.8.1 AiOutfitWS

- 端点 `ws(s)://{host}/ws/ai/{userId}`，`onopen` 后发送首条 `{type:"auth", token}` 消息鉴权
- 客户端 30s 发送 `"ping"` 心跳，服务端回 `"pong"`
- 仅处理 `msg.taskId === 当前 taskId` 的消息
- 不主动重连，被动 `onclose` 才触发降级轮询回调；`onerror` 清理心跳定时器

#### 2.8.2 AiOutfitPoller

前端未收到 WS 推送时用 taskId 兜底轮询，双阶段策略：

- 阶段 0：`interval=2000ms, count=5`（前 10s 每 2s 一次）
- 阶段 1：`interval=5000ms, count=10`（之后每 5s 一次）
- 总轮询至多 15 次、最长 60s

轮询路径调用方传入区分模式：风格驱动默认 `/v1/outfit/agent/result/{taskId}`，商品驱动传 `/v1/outfit/result/{taskId}`。

#### 2.8.3 AiOutfitLoading

分阶段进度文案，按 elapsed 时间分桶（理解需求 → 检索商品 → 挑选搭配 → 生成换装图 → 最后调整），进度条封顶 95%。

#### 2.8.4 WS 消息类型

| type | 触发场景 | 携带字段 |
|------|----------|----------|
| `OUTFIT_PRODUCT` | 商品驱动结果 | outfits（含 resultUrl） |
| `OUTFIT_AGENT` | 风格驱动结果 | patterns（含 resultUrl） |
| `OUTFIT_RECOMMEND_RESULT` | 候选推荐结果 | outfits（无 resultUrl） |
| `OUTFIT_VTON_RESULT` | VTON 换装结果（一阶段直出主要推送） | outfits（含 resultUrl） |
| `OUTFIT_ACCEPTED` | 用户采纳完成 | outfitIndex, acceptedAction |
| `OUTFIT_AGENT_FEEDBACK` | 多轮反馈完成 | status=ACCEPTED |

风格驱动与用户选定模式对外 stage 统一为 `vton`（一阶段直出，LangGraph 内部 `recommend`/`user_picked` 仅作节点路由，不外传），因此实际收到的成果多是 `OUTFIT_VTON_RESULT`；前端 switch 兼容处理 `OUTFIT_RECOMMEND_RESULT` 与 `OUTFIT_AGENT` 以适配不同后端推送。

WS 不推送 credits 余额，所有扣费操作后前端需要主动刷新余额。

### 2.9 credits 余额与充值

- 页面进入时 `GET /credits/balance/{userId}` 加载余额
- 每次扣费操作（推荐、生成、反馈）成功或失败后立即刷新
- WS 不携带余额，扣费类操作需手动刷新
- 余额展示规则由 credits-bar 统一处理：
  - 余额 = 0：红色闪烁，主按钮置灰
  - 余额 < 7：黄色高亮，提示建议充值
  - 余额 = -1：文案「服务不可用」，后端降级标记
  - 世期余额 > 0：橙色提示「X credits 即将于 M 月 D 日过期」
- 提交后端返回 403 余额不足时，前端拦截后重新拉取余额并弹充值对话框引导充值

### 2.10 我的衣橱与搭配历史

#### 2.10.1 衣橱（wardrobe.html）

按 itemType 分类：1 关联商品单品（用户主动添加）、2 自定义上传、3 全身插拍、4 AI 搭配效果图（accept 流程自动入库，用户不可手动添加）。itemType=4 卡片展示原图与 VTON 效果图、单品列表、满意动作标签与创建时间。

#### 2.10.2 搭配历史（outfit-history.html）

- 接口 `GET /items/outfit/history?tab=xxx` 按页签分组查询
- 6 状态页签：全部 / 生成中 / 已采纳 / 待采纳 / 不满意 / 生成失败
- 操作：效果图预览、一键加购（`POST /carts`）、删除记录（`DELETE /items/outfit/records/{id}`）

#### 2.10.3 浏览记录（browse-history.html）

- 列表分页 `GET /browse-history/page`
- 单条删除 `DELETE /browse-history/{id}`、批量删除 `DELETE /browse-history/batch`、清空 `DELETE /browse-history/clear`
- 点击记录跳转 item-detail.html

### 2.11 状态管理与 localStorage

不引入 Pinia / Vuex，全部用全局 `util` + localStorage。复用的工具方法：`isLogin`、`getUserId`、`hasUserPhoto`、`store.set/get/del`、`getUrlParam`、`formatPrice` 等。

localStorage key：

| key | 作用 | 有效期 |
|-----|------|--------|
| `token` | JWT 鉴权 | 永久（退出时清除） |
| `user-info` | 用户基本信息 | 永久 |
| `outfit_photo_session` | 照片会话 Key + 时间戳 + 预览 URL | 30 分钟（与后端对齐） |
| `outfit_form_draft` | 风格驱动表单草稿 | 1 小时 |
| `outfit_user_prefs` | 风格驱动不喜欢颜色累积 | 跨轮持久 |
| `outfit_product_prefs` | 商品驱动不喜欢颜色累积 | 跨轮持久 |

页面转换时通过 URL 传 `taskId` + `stage`，刷新时从 URL 重新读取，无需 localStorage 持久化任务状态（后端 Redis 已存）。

### 2.12 错误处理与降级

| 场景 | 处理 |
|------|------|
| 401 | axios 拦截器自动跳登录页 |
| 400 | 参数错误，读 detail 提示，不重试 |
| 403 | credits 不足，弹余额不足对话框引导充值 |
| 404 | 任务不存在 / stage 已过期，跳 outfit-agent.html |
| 409 | 阶段一未完结 / 已采纳，刷新页面状态 |
| 429 | 并发限流，提示稍候，不重试 |
| 500 | 服务异常，后端自动回滚预扣 credits |
| 503 | AI 服务不可用，顶部提示条 + 主按钮置灰 |
| WS 断开 | 自动降级为轮询 |
| VTON 部分失败 | 失败套卡片显示「生成失败」+ 灰遮罩，成功套仍可加购 |

前端并发保护：点击任意按钮立即锁定 `submitting` 并禁用所有按钮，收到 WS 或轮询到终态后才解锁。

### 2.13 视觉规范

主色为品牌红 `#e54346`，hover `#c72032`，辅助橙色 `#d9700`、警告 `#e6a23c`、成功 `#67c23a`（仅采纳按钮）。样式集中在 `css/ai-outfit.css`，按钮系统为主/次/幽灵，多选 Chip、模态框、候选卡片、VTON 卡片、衣橱、历史列表、Loading 浮层、Toast 均有对应样式类。响应式：`max-width: 900px` 时列表改单列、衣橱改两列。

---

## 三、AI 模特 · 商家端设计

### 3.1 功能定位

AI 模特是商家工具，用于为商品生成 AI 展示模特图。商家在 `zm-refresh-admin` 后台选择商品与模特图，AI 自动合成模特穿着商品的展示图，可发布到商品主图，并通过评分/发布/拒绝构成反馈闭环，高质量图可入系统池供全平台复用。

### 3.2 单页架构与菜单路由

`zm-refresh-admin` 是单页应用，仅 `index.html` + `login.html` 两个 HTML。AI 模特页面注册为 Vue 全局组件，通过根实例的 `currentMenu` 字符串 + `v-if` 切换，无 vue-router、无构建工具链，切换时旧页面 DOM 完全卸载。

菜单目录：

```
el-submenu index=ai-model  ├─ ai-model-system-images（模特图池）
                           ├─ ai-model-generate（生成模特图）
                           └─ ai-model-tasks（任务列表）
```

### 3.3 核心页面

| 菜单 index | 组件 | 文件 | 职责 |
|------------|------|------|------|
| ai-model-system-images | system-images-page | js/pages/ai-model/system-images.js | 模特图池 CRUD / 上传 / 可见性 |
| ai-model-generate | generate-page | js/pages/ai-model/generate.js | 选商品 + 选模特图 + 提交生成 + 评分/发布/拒绝 |
| ai-model-tasks | tasks-page | js/pages/ai-model/tasks.js | 任务列表 + 实时刷新 + 评分/发布/拒绝 |
| ai-stats | ai-stats-page | js/pages/stats/ai-stats.js | 生成类型统计看板 |

页面间通过 `this.$root.currentMenu = 'xxx'` 互相跳转。

### 3.4 生成页核心逻辑

`generate.js` 支持三种生成模式：

| 模式 | 商品上限 | credits | 结果结构 |
|------|----------|---------|----------|
| single 单图 | 3 件 | 5 | `resultUrls[]`，最后一张为最终图 |
| multi_pose 多姿势 | 3 件 | 3 + poseCount × 3 | `poseResults[]` 按姿势分组 |
| multi_outfit 多换装 | 4 件 | 18 | `sceneResults[]` 按组合分组 |

商品选择走 `GET /items/admin/page?status=1&onlyMine=true`，同类目互斥且超出上限禁选。模特图走 `GET /items/admin/ai-model/system-images` 分页，按性别 / 肤色筛选，点选高亮。

提交流程：`POST /items/admin/ai-model/generate`，传 `{ itemIds, modelImageId, generationMode, poseCount? }`，成功后返回 `taskId + queuePosition`，可切到任务列表查看进度。生成页本身不建 WS / 轮询，采用异步提交模式。

### 3.5 任务列表页

`tasks.js` 顶部展示 credits 余额条，筛选栏按状态（PENDING / PROCESSING / SUCCESS / FAILED / TIMEOUT）过滤，表格列含任务 ID、最终图缩略图、商品、状态、耗时、评分、入池 / 发布标记、创建时间与操作。

实时刷新：
- `mounted` 时 `loadList()` + `loadCredits()` + 建立 WS 订阅 + 秒级耗时计算
- WS 收到 `AI_MODEL` 消息时局部更新对应行状态/结果图/耗时，终态时弹出通知
- 存在正在进行任务时启动 30s 兜底轮询，任务结束后自动停止
- `beforeDestroy` 关闭 WS、清理定时器

### 3.6 系统模特图池

`system-images.js`：

- `GET /items/admin/ai-model/system-images` 分页（默认 12/service），按性别 / 肤色筛选，`mineOnly` 客户端过滤
- 卡片展示图片、性别 / 肤色 / 体型 / 风格标签 tag，按来源区分（商家上传 / AI 入池 / 平台运营 / AI 自动生成）并使用不同角标
- 上传走 `manualUpload()` 兜底：因 `styleTags` 数组不能直接 toString，用 FormData 逐项追加字段再 `POST /items/admin/ai-model/system-images`
- 上传表单校验性别必填、肤色必填，图片仅 JPG/PNG/WebP 且 ≤5MB
- 可见性切换 / 编辑 / 删除均复用 `PUT /items/admin/ai-model/system-images/{id}` 与 `DELETE /items/admin/ai-model/system-images/{id}`，失败回滚开关状态

### 3.7 评分 / 发布 / 拒绝链式流程

任务 SUCCESS 后可评分、发布、拒绝：

- 评分：`POST /items/admin/ai-model/rating`，五星制 + 标签 + 备注 + 是否入池。评分较高 + 勾选入池则自动入系统级；评分较低仅记录反馈
- 发布：`POST /items/admin/ai-model/publish`，选取已批商品后替换该商品主图
- 拒绝：`POST /items/admin/ai-model/reject`，填写拒绝原因（≤512 字）；评分很低且拒绝时弹发送失败引导（重新选品 / 调整模特来源 / 联系客服）

### 3.8 评分激励与反馈奖励

| 场景 | 触发 | 奖励 | 上限 |
|------|------|------|------|
| 评分激励 | 评分较高 + 入池 + 发布 | 1 credit | 5 次/日 |
| 反馈奖励 | 拒绝原因 ≥20 字 | 1 credit | 3 次/日 |

奖励通过接口同步回调，前端在响应后弹出提示，展示奖励值与剩余次数。

### 3.9 组件设计

`zm-refresh-admin/js/components/` 下 5 个组件：

| 文件 | 类型 | 职责 |
|------|------|------|
| ai-model-ws.js | 工具类（AiModelWS / AiModelPoller / AiModelLoading） | WS / 轮询 / Loading |
| rating-dialog.js | Vue 组件 | 评分对话框 |
| publish-dialog.js | Vue 组件 | 发布对话框 |
| reject-dialog.js | Vue 组件 | 拒绝原因 + 致歉引导 |
| recharge-dialog.js | Vue 组件 | credits 充值对话框 |

### 3.10 WebSocket 与兜底轮询

- 端点 `ws(s)://{host}/ws/model/{userId}`
- 鉴权：`onopen` 后发送 `{type:"auth", token}`（商家端用 `zm-local-admin-token`）
- 30s 心跳 `"ping"`
- `taskId=null` 不过滤，订阅该用户所有任务消息（任务列表页用）
- 不主动重连，被动 `onclose` 触发降级轮询

AiModelPoller 面向长任务：阶段 0 `interval=2000ms`，阶段 1 `interval=5000ms`，总时长约 600s 对齐后端超时阈值。AiModelLoading 按 6 阶段分桶展示长任务进度文案。

AI 模特 WS 消息结构：

```javascript
{
  taskId: 'xxx',
  type: 'AI_MODEL',
  status: 'PENDING' | 'PROCESSING' | 'SUCCESS' | 'FAILED' | 'TIMEOUT',
  resultUrls: [...],          // SUCCESS 时携带，最后一张为最终图
  itemCategories: [...],
  itemIds: [...],
  starRating: 4,
  savedToPool: 1,
  publishedItemId: 123,
  rejectReason: '...',
  errorMsg: '...',
  finishedAt: '...',
  queuePosition: 0,
}
```

### 3.11 视觉规范

沿用 Element UI 默认色系 + 品牌红 `#e54346`。主色用于按钮、角牌、进度条；成功 / 警告 / 危险 / 信息分别对齐 Element 的 default 色值。样式集中在 `css/main.css`，`.model-grid` 响应式宽度（`>1400px` 4 列、`>900px` 3 列、`≤900px` 2 列）。

---

## 四、横向设计

### 4.1 接口调用清单

#### 4.1.1 AI 随心搭（用户端）

| 接口 | 调用方 | 场景 |
|------|--------|------|
| `POST /v1/outfit/photo` | outfit / 商品 | 上传自拍或图，返回 photoSessionKey |
| `DELETE /v1/outfit/photo` | outfit/商品 | 清除照片会话 |
| `POST /v1/outfit/generate` | outfit-product | 商品驱动提交，扣 5 credits |
| `GET /v1/outfit/result/{taskId}` | outfit-product 轮询 | 商品驱动查询结果 |
| `POST /v1/outfit/feedback` | product-feedback | 商品驱动多轮反馈，扣 5 credits/轮 |
| `POST /v1/outfit/agent/recommend` | outfit-agent | 风格驱动 / 用户选定，扣 17 / 5 credits |
| `POST /v1/outfit/agent/accept` | outfit-result | 满意入库（cart/order）写衣橱 + 搭配历史 |
| `POST /v1/outfit/agent/feedback` | feedback-dialog | 风格驱动多轮反馈，扣 5 credits/轮 |
| `GET /v1/outfit/agent/result/{taskId}` | outfit-result | 查询/恢复 + 轮询降级 |
| `GET /v1/outfit/agent/profile` | outfit-agent | 查询用户画像置信度与偏好 |
| `GET /v1/outfit/agent/system-models` | outfit-agent / 商品 | 系统模特列表（性别过滤） |
| `GET /credits/balance/{userId}` | 所有页面 | 加载余额 |
| `POST /credits/recharge` | 充值对话框 | 充值 |
| `GET /wardrobe`、`POST /wardrobe`、`DELETE /wardrobe/{id}` | wardrobe 相关 | 衣橱增删查 |
| `GET /wardrobe/my-item-ids` | item-detail | 判断是否已在衣橱 |
| `GET /body-profile` | outfit-agent / 商品 | 加载身体档案（性别等） |
| `GET /items/outfit/history` | outfit-history | 搭配历史（tab 分组） |
| `POST /items/outfit/records` | outfit-result / 历史 | 满意入库 / 更新记录 |
| `DELETE /items/outfit/records/{id}` | outfit-history | 删除历史记录 |
| `GET /items/outfit/records/by-task` | outfit-result | 按 task 查记录 |
| `DELETE /items/outfit/wardrobe/by-task` | outfit-result | 回收衣橱条目 |
| `POST /items/size-chart/recommend-batch` | outfit-result | 尺码推荐 |
| `GET /items/{itemId}` | 商品 / 衣橱 | 商品详情 |
| `GET /items/search` | wardrobe-upload | 商品搜索 |
| `GET /orders/user/page`、`GET /carts`、`POST /carts` | outfit-agent / 历史 / 衣橱 | 商品来源 / 加购 |
| `GET /shop/list` | outfit-agent | 店铺列表 |
| `GET /browse-history/page`、`DELETE /browse-history/{id}`、`DELETE /browse-history/batch`、`DELETE /browse-history/clear` | browse-history | 浏览记录管理 |

#### 4.1.2 AI 模特（商家端）

| 接口 | 调用方 | 场景 |
|------|--------|------|
| `POST /items/admin/ai-model/generate` | generate.js | 提交生成任务 |
| `GET /items/admin/ai-model/tasks` | tasks.js | 任务列表（按状态筛选） |
| `POST /items/admin/ai-model/rating` | rating-dialog | 评分提交 |
| `POST /items/admin/ai-model/reject` | reject-dialog | 拒绝原因提交 |
| `POST /items/admin/ai-model/publish` | publish-dialog | 发布到商品主图 |
| `GET /items/admin/ai-model/system-images` | generate / system-images | 模特图分页 |
| `POST /items/admin/ai-model/system-images` | system-images | multipart 上传 |
| `PUT /items/admin/ai-model/system-images/{id}` | system-images | 编辑 / 切换可见 |
| `DELETE /items/admin/ai-model/system-images/{id}` | system-images | 软删模特图 |
| `GET /items/admin/page` | generate.js | 商品选择 |
| `GET /credits/balance/{userId}`、`POST /credits/recharge` | generate / tasks / 充值 | 余额与充值 |

### 4.2 鉴权机制

- 用户端：JWT 存于 `localStorage.token`，axios 拦截器自动注入 `authorization` 请求头，401 统一跳 `/login.html`；WebSocket `onopen` 后发送 `{type:"auth", token}` 鉴权
- 商家端：JWT 存于 `localStorage.zm-admin-token`，`ZM.http` 实例注入相同请求头，401 跳商家登录页；WebSocket 用同一 token 通过首条鉴权消息传递

### 4.3 性能优化

- 商品图、换装图统一走 OSS CDN，衣橱用懒加载
- 风格驱动表单 debounce 300ms 后激活主按钮；独立接口并行请求
- 分页加载（默认 12–20 条/页）
- 所有 `setTimeout` 引用收集到 `_timeouts[]`，`beforeDestroy` 统一清除，防止内存泄漏
- WS 仅在任务页面建立，离开页面 `cleanup()` 释放