"""
话术追踪器：检测LLM回复中是否包含触发短语，并管理计数器
"""

import re

# 触发短语列表（匹配"不理你了"及其变体）
TRIGGER_PATTERNS = [
    re.compile(r"不理你[了啦哦啊]?"),
    re.compile(r"真的不理你[了啦哦啊]?"),
]


def detect_silence_phrase(text: str) -> bool:
    """
    检测文本中是否包含"不理你了"或"真的不理你了"等触发短语

    Args:
        text: LLM回复的文本内容

    Returns:
        bool: 是否匹配到触发短语
    """
    if not text:
        return False
    for pattern in TRIGGER_PATTERNS:
        if pattern.search(text):
            return True
    return False


def get_trigger_phrases_display() -> str:
    """获取触发短语的展示文本"""
    return '"不理你了" / "真的不理你了"'
