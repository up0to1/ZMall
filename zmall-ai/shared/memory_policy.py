"""长期记忆写入策略。

一次反馈里的“这次不要某颜色”只应影响当前任务，不应直接污染跨会话画像。
该模块不依赖业务服务，供 Agent 编排层和 ReAct Tool 共同使用。
"""


_TASK_SCOPE_MARKERS = (
    "这次", "本次", "这轮", "当前", "这个搭配", "这套", "这件", "换掉",
)
_DURABLE_SCOPE_MARKERS = (
    "以后", "今后", "长期", "一直", "总是", "记住", "我的偏好", "再也不要", "不要再",
)


def should_persist_preference(
    *texts: str | None,
    explicit_user_field: bool = False,
) -> bool:
    """判断反馈中的偏好是否足够明确，可以写入长期记忆。

    - 前端明确提交的 dislikeColors 等结构化字段视为用户确认；
    - 自然语言需要出现长期范围表达；
    - 同时出现“这次/这套”等任务范围词时，以任务范围为准。
    """
    if explicit_user_field:
        return True
    text = " ".join(str(value).strip() for value in texts if value and str(value).strip())
    if not text:
        return False
    if any(marker in text for marker in _TASK_SCOPE_MARKERS):
        return False
    return any(marker in text for marker in _DURABLE_SCOPE_MARKERS)
