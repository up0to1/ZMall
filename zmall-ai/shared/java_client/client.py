"""
Java 服务 HTTP 客户端

Python ai-models / ai-outfit 通过 Nacos 发现 Java 微服务实例，
然后通过 HTTP 调用配额预扣、商品查询等接口。
"""
import logging

import httpx

from shared.nacos_discovery import NacosDiscovery

logger = logging.getLogger(__name__)


class JavaClient:
    """Java 微服务统一 HTTP 客户端（Nacos 发现 + user-info 透传）"""

    def __init__(self, discovery: NacosDiscovery):
        self.discovery = discovery
        # trust_env=False: 忽略 HTTP_PROXY/HTTPS_PROXY 环境变量，
        # Java 微服务是内网服务，不走代理（QdrantClientWrapper 会设置全局代理环境变量，
        # 但其 NO_PROXY 的 CIDR 表示法 httpx 不支持，导致内网调用误走代理）
        self._http = httpx.AsyncClient(timeout=15.0, trust_env=False)

    async def _call(self, service_name: str, method: str, path: str,
                    user_id: int | None = None,
                    json: dict | None = None,
                    params: dict | None = None) -> httpx.Response | None:
        """调用 Java 微服务

        Args:
            service_name: Nacos 服务名（如 user-service）
            method: HTTP 方法 GET/POST/PUT/DELETE
            path: 请求路径（如 /quota/deduct）
            user_id: 用户ID（透传到 user-info 请求头）
            json: 请求体
            params: query 参数
        Returns:
            httpx.Response 或 None（服务不可用时）
        """
        base_url = await self.discovery.get_service_url(service_name)
        if base_url is None:
            logger.error("Java 服务不可用: service=%s", service_name)
            return None

        headers = {}
        if user_id is not None:
            headers["user-info"] = str(user_id)

        url = f"{base_url}{path}"
        try:
            resp = await self._http.request(
                method, url, headers=headers, json=json, params=params
            )
            return resp
        except Exception as e:
            logger.error("调用 Java 服务异常: service=%s, url=%s, error=%s", service_name, url, e)
            return None

    # ===== 配额服务 =====

    async def quota_confirm(self, user_id: int, quota_type: str, quota_id: int, task_id: str) -> bool:
        """配额确认消耗"""
        resp = await self._call(
            "user-service", "POST", "/quota/confirm",
            user_id=user_id,
            json={"type": quota_type, "id": quota_id, "taskId": task_id},
        )
        return resp is not None and resp.status_code == 200

    async def quota_rollback(self, user_id: int, quota_type: str, quota_id: int, task_id: str) -> bool:
        """配额回滚"""
        resp = await self._call(
            "user-service", "POST", "/quota/rollback",
            user_id=user_id,
            json={"type": quota_type, "id": quota_id, "taskId": task_id},
        )
        return resp is not None and resp.status_code == 200

    # ===== Credits 积分制配额 =====
    # 对应 Java CreditsController: POST /credits/deduct, /credits/confirm, /credits/rollback
    # 走 OUTFIT_RECOMMEND（2 credits）/ OUTFIT_VTON（5×N credits）双阶段模式

    async def credits_deduct(
        self, user_id: int, quota_type: str, task_id: str, credits: int,
    ) -> dict | None:
        """v3 credits 预扣（FIFO：先扣赠送 30 天，再扣充值永久）

        Args:
            user_id: 用户 ID
            quota_type: OUTFIT_RECOMMEND / OUTFIT_VTON（isCreditsMode=true 的类型）
            task_id: 任务 ID（冻结记录 Key）
            credits: 本次预扣的 credits 数量

        Returns:
            {"success": true, "credits": 2, "balance": 48,
             "freeBalance": 30, "paidBalance": 18, "expiringSoon": [...]} 或
            {"success": false, "msg": "余额不足"} 或 None（服务不可用）
        """
        resp = await self._call(
            "user-service", "POST", "/credits/deduct",
            user_id=user_id,
            json={
                "type": quota_type,
                "userId": user_id,
                "taskId": task_id,
                "credits": credits,
            },
        )
        if resp and resp.status_code == 200:
            return resp.json()
        logger.error("Credits 预扣失败: status=%s, body=%s",
                      resp.status_code if resp else "None",
                      resp.text if resp else "")
        return None

    async def credits_confirm(
        self, user_id: int, quota_type: str, task_id: str,
    ) -> bool:
        """v3 credits 确认消耗（删除冻结记录，不返还）"""
        resp = await self._call(
            "user-service", "POST", "/credits/confirm",
            user_id=user_id,
            json={"type": quota_type, "userId": user_id, "taskId": task_id},
        )
        return resp is not None and resp.status_code == 200

    async def credits_rollback(
        self, user_id: int, quota_type: str, task_id: str,
    ) -> bool:
        """v3 credits 回滚（按冻结明细原路返还）"""
        resp = await self._call(
            "user-service", "POST", "/credits/rollback",
            user_id=user_id,
            json={"type": quota_type, "userId": user_id, "taskId": task_id},
        )
        return resp is not None and resp.status_code == 200

    # ===== AI 随心搭满意套装入库 =====
    # 对应 Java OutfitController: POST /items/admin/outfit/records
    # 用户在阶段二 VTON 结果中选 [满意-加购整套] 或 [满意-下单整套] 时调用

    async def create_outfit_record(self, user_id: int, record_dto: dict) -> dict | None:
        """入库满意的搭配套装到 ai_outfit_record 表（v3）

        Args:
            user_id: 用户 ID（透传 user-info 头，Java 侧也用 UserContext 二次校验）
            record_dto: AiOutfitRecordCreateDTO 字段：
                - taskId: 阶段二 VTON 任务 ID
                - userId: 用户 ID
                - round: 推荐轮次（同会话内多轮反馈时递增）
                - outfitIndex: Top3 中的索引 0/1/2
                - outfitJson: 套装详情 JSON 字符串
                - vtonResultUrl: VTON 最终效果图 URL
                - modelImageSource: photo/system_pool/ai_generated
                - modelImageId: 模特图 ID（可空）
                - acceptedAction: cart/order
                - creditsConsumed: 本次 VTON 消耗的 credits 数（审计用）

        Returns:
            AiOutfitRecordDTO（含 id/createdAt 等）或 None（失败）
        """
        resp = await self._call(
            "item-service", "POST", "/items/admin/outfit/records",
            user_id=user_id,
            json=record_dto,
        )
        if resp and resp.status_code == 200:
            data = resp.json()
            # 兼容包装格式 {code:200, data:{...}}
            if isinstance(data, dict) and data.get("data") is not None:
                data = data["data"]
            return data if isinstance(data, dict) else None
        logger.error("入库搭配记录失败: status=%s, body=%s",
                     resp.status_code if resp else "None",
                     resp.text if resp else "")
        return None

    async def get_outfit_record_by_task(
        self, user_id: int, task_id: str, outfit_index: int,
    ) -> dict | None:
        """按 taskId + outfitIndex 查询搭配记录（Redis 过期兜底用）

        对应 Java OutfitController GET /items/admin/outfit/records/by-task

        Returns:
            AiOutfitRecordDTO 或 None（不存在/失败）
        """
        resp = await self._call(
            "item-service", "GET", "/items/admin/outfit/records/by-task",
            user_id=user_id,
            params={"taskId": task_id, "outfitIndex": outfit_index},
        )
        if resp and resp.status_code == 200:
            data = resp.json()
            if isinstance(data, dict) and data.get("data") is not None:
                data = data["data"]
            return data if isinstance(data, dict) else None
        return None

    async def delete_outfit_record(self, user_id: int, record_id: int) -> bool:
        """删除搭配记录（生成中占位记录失败清理用）

        对应 Java OutfitController DELETE /items/admin/outfit/records/{id}

        Returns:
            True=删除成功/接口返回正常，False=删除失败
        """
        resp = await self._call(
            "item-service", "DELETE", f"/items/admin/outfit/records/{record_id}",
            user_id=user_id,
        )
        if resp and resp.status_code == 200:
            return True
        logger.error("删除搭配记录失败: recordId=%s, status=%s",
                     record_id, resp.status_code if resp else "None")
        return False

    # ===== 商品服务 =====

    async def get_shop_name(self, shop_id: int) -> str | None:
        """按商家 ID 查询店铺名（单品来源标签展示用）

        对应 social-service ShopProfileController GET /merchant/profile/shop-name?userId=...

        Returns:
            店铺名字符串；查不到/失败返回 None
        """
        resp = await self._call(
            "social-service", "GET", "/merchant/profile/shop-name",
            params={"userId": shop_id},
        )
        if resp and resp.status_code == 200:
            # 兼容三种响应格式：
            # 1. JSON 包装 {code:200, data:"店铺名"}
            # 2. JSON 字符串 "店铺名"
            # 3. text/plain 裸字符串 店铺名（实测 social-service 返回该格式）
            try:
                data = resp.json()
                if isinstance(data, str):
                    return data or None
                if isinstance(data, dict) and data.get("data") is not None:
                    return str(data["data"]) or None
            except Exception:
                text = resp.text.strip()
                if text:
                    return text
        logger.warning("查询店铺名失败: shopId=%s, status=%s",
                       shop_id, resp.status_code if resp else "None")
        return None

    async def get_items_by_ids(self, item_ids: list[int]) -> list[dict]:
        """批量查询商品

        兼容 Java 返回裸 list 或 {code:200, data:[...]} 包装格式
        """
        if not item_ids:
            return []
        ids_str = ",".join(str(i) for i in item_ids)
        resp = await self._call(
            "item-service", "GET", "/items",
            params={"ids": ids_str},
        )
        if resp and resp.status_code == 200:
            data = resp.json()
            # 兼容包装格式 {code:200, data:[...]}
            if isinstance(data, list):
                return data
            if isinstance(data, dict) and isinstance(data.get("data"), list):
                return data["data"]
            return []
        logger.warning("批量查询商品失败: ids=%s, status=%s",
                       ids_str[:80], resp.status_code if resp else "None")
        return []

    # ===== 我的衣橱（节点2 衣橱商品注入）=====
    # 注：衣橱条目 ID 由前端直接传 wardrobeItemIds，agent_service 调 get_wardrobe_items_by_ids 解析为商品 ID

    async def get_wardrobe_items_by_ids(self, wardrobe_ids: list[int]) -> list[dict]:
        """根据衣橱条目 id 批量查询（用于反馈轮按 id 重新拉取）

        对应 Java WardrobeController#queryWardrobeByIds: GET /wardrobe/items?ids=1,2,3
        """
        if not wardrobe_ids:
            return []
        ids_str = ",".join(str(i) for i in wardrobe_ids)
        resp = await self._call(
            "user-service", "GET", "/wardrobe/items",
            params={"ids": ids_str},
        )
        if resp and resp.status_code == 200:
            return resp.json() or []
        logger.warning("批量查询衣橱条目失败: ids=%s, status=%s",
                       wardrobe_ids, resp.status_code if resp else "None")
        return []

    # ===== AI 满意搭配自动入衣橱 =====
    # 对应 Java WardrobeController: POST /wardrobe/internal
    # Python ai-outfit accept 流程在 create_outfit_record 成功后调用，把 AI 搭配效果图写入 user_wardrobe（item_type=4）

    async def add_wardrobe_outfit(
        self,
        user_id: int,
        outfit_result_url: str,
        original_photo_url: str | None,
        outfit_json: str,
        record_id: int,
    ) -> dict | None:
        """accept 入库后同步写入 user_wardrobe（item_type=4 AI 搭配效果图）

        Args:
            user_id: 用户 ID（透传 user-info 头 + 显式参数双重传递，Java 二次校验）
            outfit_result_url: AI 穿搭效果图 URL（来自 ai_outfit_record.vton_result_url）
            original_photo_url: 用户原自拍照 URL（场景 A 用系统模特图时为 None）
            outfit_json: AI 搭配单品详情 JSON 字符串
            record_id: 关联 ai_outfit_record.id（跨服务关联）

        Returns:
            WardrobeDTO（含 id/createTime 等）或 None（失败）
            失败不阻塞 accept 主流程（调用方 try/except + warning 日志）
        """
        payload = {
            "userId": user_id,
            "itemType": 4,
            "outfitResultUrl": outfit_result_url,
            "originalPhotoUrl": original_photo_url,
            "outfitJson": outfit_json,
            "recordId": record_id,
        }
        resp = await self._call(
            "user-service", "POST", "/wardrobe/internal",
            user_id=user_id,
            json=payload,
        )
        if resp and resp.status_code == 200:
            data = resp.json()
            # 兼容包装格式 {code:200, data:{...}}
            if isinstance(data, dict) and data.get("data") is not None:
                data = data["data"]
            return data if isinstance(data, dict) else None
        logger.warning(
            "写入 AI 搭配效果图到衣橱失败（不阻塞 accept）: userId=%s, recordId=%s, status=%s, body=%s",
            user_id, record_id,
            resp.status_code if resp else "None",
            resp.text if resp else "",
        )
        return None

    # ===== 用户身体信息档案（尺码推荐用）=====
    # 对应 Java BodyProfileController:
    #   GET /body-profile/{id}  查询单个档案
    #   GET /body-profile/list?userId=xxx  查询用户档案列表

    async def get_body_profile(self, profile_id: int) -> dict | None:
        """查询单个身体信息档案

        对应 Java BodyProfileController#queryBodyProfile: GET /body-profile/{id}
        AI 随心搭节点1 拉取用户选中的身体信息档案时调用。
        """
        if not profile_id:
            return None
        resp = await self._call(
            "user-service", "GET", f"/body-profile/{profile_id}",
        )
        if resp and resp.status_code == 200:
            data = resp.json()
            if isinstance(data, dict) and data.get("data") is not None:
                data = data["data"]
            return data if isinstance(data, dict) else None
        logger.warning("查询身体信息档案失败: profileId=%s, status=%s",
                       profile_id, resp.status_code if resp else "None")
        return None

    async def get_user_body_profiles(self, user_id: int) -> list[dict]:
        """查询用户身体信息档案列表

        对应 Java BodyProfileController#queryUserBodyProfiles: GET /body-profile/list?userId=xxx
        AI 随心搭前端展示用户身体信息选择器时调用（获取默认档案 + 其他档案）。
        """
        if not user_id:
            return []
        resp = await self._call(
            "user-service", "GET", "/body-profile/list",
            params={"userId": user_id},
        )
        if resp and resp.status_code == 200:
            return resp.json() or []
        logger.warning("查询用户身体信息档案列表失败: userId=%s, status=%s",
                       user_id, resp.status_code if resp else "None")
        return []

    # ===== 尺码推荐（用户选购时调用）=====
    # 对应 Java SizeChartController:
    #   POST /items/size-chart/recommend-batch  批量尺码推荐

    async def recommend_size_batch(
        self,
        body_profile: dict,
        item_ids: list[int],
    ) -> dict:
        """批量推荐尺码（搭配选购场景，按商品三级回退查询）

        对应 Java SizeChartController#recommendSizeBatch: POST /items/size-chart/recommend-batch
        用户查看 AI 搭配的多件单品时，一次性获取每件单品的推荐尺码。

        内部走 recommendSizeByItem 三级回退查询，
        自动按 itemId 找到对应店铺的尺码表。

        Args:
            body_profile: 用户身体信息 dict
            item_ids: 商品ID列表
        Returns:
            {itemId(str): SizeRecommendResult} 映射 dict
            （注意：JSON 反序列化后 key 是 str 类型）
        """
        if not item_ids:
            return {}
        payload = {
            "bodyProfile": body_profile,
            "itemIds": item_ids,
        }
        resp = await self._call(
            "item-service", "POST", "/items/size-chart/recommend-batch",
            json=payload,
        )
        if resp and resp.status_code == 200:
            data = resp.json()
            if isinstance(data, dict) and data.get("data") is not None:
                data = data["data"]
            return data if isinstance(data, dict) else {}
        logger.warning("批量尺码推荐失败: itemIds=%s, status=%s",
                       item_ids, resp.status_code if resp else "None")
        return {}

    async def recommend_size_by_item(
        self,
        body_profile: dict,
        item_id: int,
    ) -> dict | None:
        """按商品推荐尺码（含三级回退查询，AI 随心搭场景推荐使用）

        对应 Java SizeChartController#recommendSizeByItem:
        POST /items/size-chart/recommend-by-item?itemId={item_id}

        自动按商品 itemId 查询对应的尺码表（三级回退）：
            1. 商品专用绑定（item.size_chart_id 非空时）
            2. 店铺品类通用表（shop_id + category + gender）
            3. 系统模板（shop_id=0 + category + gender）
        再基于用户身体信息计算匹配度。

        与 recommend_size 的区别：
            - recommend_size 基于"系统模板"，仅按 category 匹配
            - recommend_size_by_item 基于"商品对应店铺的尺码表"，支持店铺自定义

        Args:
            body_profile: 用户身体信息 dict
            item_id: 商品ID
        Returns:
            SizeRecommendResult dict（recommendedSize / confidence / alternatives / reason）
        """
        resp = await self._call(
            "item-service", "POST", "/items/size-chart/recommend-by-item",
            params={"itemId": item_id},
            json=body_profile,
        )
        if resp and resp.status_code == 200:
            data = resp.json()
            if isinstance(data, dict) and data.get("data") is not None:
                data = data["data"]
            return data if isinstance(data, dict) else None
        logger.warning("按商品尺码推荐失败: itemId=%s, status=%s",
                       item_id, resp.status_code if resp else "None")
        return None

    # ===== 系统模特图池（v2 统一池，AI 随心搭场景 A 兜底用）=====

    async def get_random_default_model_image(self, user_id: int | None = None) -> dict | None:
        """随机获取一张系统默认模特图（v2 统一池，全平台共用）

        对应 Java AiModelController#getRandomDefault: GET /items/admin/ai-model/system-images/random-default
        返回 SystemModelImageDTO 的 JSON，含 imageUrl（可能是相对路径 /uploads/model-images/xxx.jpg 或完整 OSS URL）。
        系统池为空时返回 None。

        Args:
            user_id: 当前用户ID（透传 user-info 头，便于 Java 侧审计/限流；可空）
        Returns:
            {"id": ..., "imageUrl": "...", "gender": ..., "skinTone": ..., ...} 或 None
        """
        resp = await self._call(
            "item-service", "GET", "/items/admin/ai-model/system-images/random-default",
            user_id=user_id,
        )
        if resp is None:
            logger.warning("查询系统默认模特图失败：item-service 不可用")
            return None
        if resp.status_code != 200:
            logger.warning("查询系统默认模特图失败: status=%s, body=%s",
                           resp.status_code, resp.text[:200] if resp.text else "")
            return None
        data = resp.json()
        # 兼容包装格式 {code:200, data:{...}}
        if isinstance(data, dict) and data.get("data") is not None:
            data = data["data"]
        if not isinstance(data, dict) or not data.get("imageUrl"):
            logger.info("系统模特图池为空（Java 返回空数据）")
            return None
        return data

    async def list_system_model_images(
        self,
        user_id: int | None = None,
        gender: str | None = None,
        page: int = 1,
        size: int = 50,
    ) -> dict | None:
        """查询系统模特图列表（性别过滤扩展）

        对应 Java AiModelController#listSystemImages:
        GET /items/admin/ai-model/system-images?gender=xxx&page=1&size=50

        供 AI 随心搭前端用户端调用，让用户选定男/女模特作为 VTON base，
        并据此进行 Qdrant 性别过滤（男模特只配男款+中性款，女模特只配女款+中性款）。

        Args:
            user_id: 当前用户ID（透传 user-info 头）
            gender: 可选性别过滤 male/female，None 时返回全部
            page: 页码（1-based）
            size: 每页数量（默认 50，足够前端展示）
        Returns:
            {"list": [...SystemModelImageDTO], "total": N, "pages": M} 或 None
        """
        params = {"page": page, "size": size}
        if gender in ("male", "female"):
            params["gender"] = gender
        resp = await self._call(
            "item-service", "GET", "/items/admin/ai-model/system-images",
            user_id=user_id,
            params=params,
        )
        if resp is None:
            logger.warning("查询系统模特图列表失败：item-service 不可用")
            return None
        if resp.status_code != 200:
            logger.warning("查询系统模特图列表失败: status=%s, body=%s",
                           resp.status_code, resp.text[:200] if resp.text else "")
            return None
        data = resp.json()
        # 兼容包装格式 {code:200, data:{...}}
        if isinstance(data, dict) and data.get("data") is not None:
            data = data["data"]
        # Java 返回 PageDTO 格式：{list, total, pages}
        if not isinstance(data, dict):
            return {"list": [], "total": 0, "pages": 0}
        return {
            "list": data.get("list") or [],
            "total": data.get("total", 0),
            "pages": data.get("pages", 0),
        }

    async def close(self):
        await self._http.aclose()
