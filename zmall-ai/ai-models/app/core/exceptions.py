"""
异常定义
"""
from fastapi import HTTPException


class TaskNotFoundException(HTTPException):
    """任务不存在异常"""
    def __init__(self, detail: str = "任务不存在或已过期"):
        super().__init__(status_code=404, detail=detail)
