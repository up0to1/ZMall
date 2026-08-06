"""
通用 Pydantic 模型（多个 router 共用）
"""
import re
from typing import Optional

from fastapi import HTTPException
from pydantic import BaseModel


# H8：task_id UUID 格式校验
# 内部 task_id 由 str(uuid.uuid4()) 生成，用户传入的 task_id 必须匹配 UUID 格式，
# 防止注入特殊字符污染 Redis key（ai:task:status:{task_id} / ai:outfit:state:{task_id} 等）
_TASK_ID_PATTERN = re.compile(
    r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$',
    re.IGNORECASE,
)


def validate_task_id(task_id: Optional[str]) -> str:
    """校验 task_id 是否为合法 UUID 格式

    在 API 入口调用，非法格式直接返回 400，避免恶意字符串进入 Redis key 或日志。
    """
    if not task_id or not _TASK_ID_PATTERN.match(task_id):
        raise HTTPException(status_code=400, detail="taskId 格式非法")
    return task_id


class TaskResponse(BaseModel):
    """任务提交响应"""
    taskId: str
    status: str = "PROCESSING"
    msg: str = "已收到，静候结果"
