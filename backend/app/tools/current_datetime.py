"""Trusted current date and time for direct clock questions."""

from datetime import datetime, timedelta, timezone
import re


CHINA_TIME = timezone(timedelta(hours=8), "Asia/Shanghai")
WEEKDAYS = "一二三四五六日"
_DATE_QUESTION = re.compile(
    r"(?:今天|今日|现在|当前)(?:是|为)?(?:几号|几月几号|几月几日|什么日期|日期|哪一天|星期几|周几|几点|几点了|什么时间|时间)"
    r"|(?:今天|今日)(?:是)?(?:星期几|周几)"
)


def is_current_datetime_question(query: str, has_attachments: bool = False) -> bool:
    """Recognize standalone clock questions; compound requests still use the normal workflow."""
    if has_attachments:
        return False
    cleaned = re.sub(r"[\s?？!！。,.，呀啊呢吗请问告诉我]", "", query)
    return bool(_DATE_QUESTION.fullmatch(cleaned))


def current_datetime_answer(query: str, now: datetime | None = None) -> tuple[str, dict]:
    current = (now or datetime.now(CHINA_TIME)).astimezone(CHINA_TIME)
    weekday = f"星期{WEEKDAYS[current.weekday()]}"
    if any(word in query for word in ("几点", "时间")):
        answer = (f"现在是北京时间 {current.year} 年 {current.month} 月 {current.day} 日 "
                  f"{current:%H:%M}，{weekday}。")
    elif any(word in query for word in ("星期", "周几")):
        answer = f"今天是 {current.year} 年 {current.month} 月 {current.day} 日，{weekday}。"
    else:
        answer = f"今天是 {current.year} 年 {current.month} 月 {current.day} 日，{weekday}。"
    return answer, {"timezone": "Asia/Shanghai", "isoTime": current.isoformat(), "source": "服务器时钟"}
