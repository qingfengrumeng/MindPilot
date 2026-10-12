"""Summarize saved conversation activity without estimating missing usage."""
from collections import Counter
from datetime import timedelta, timezone

from sqlalchemy import select

from app.core.security import utcnow
from app.db.models import AgentRun, Conversation, Message


def number(value):
    try:
        return max(0, int(value))
    except (TypeError, ValueError, OverflowError):
        return 0


def profile_statistics(db, user_id):
    conversations = db.scalars(select(Conversation).where(Conversation.user_id == user_id)).all()
    messages = db.scalars(select(Message).join(Conversation).where(Conversation.user_id == user_id)).all()
    runs = db.scalars(select(AgentRun).join(Conversation).where(Conversation.user_id == user_id)).all()
    input_tokens = output_tokens = peak_tokens = longest_ms = missing = rounds = tools = 0
    days = set()
    features = Counter()
    labels = {}
    for message in messages:
        meta = message.metadata_json or {}
        if message.role == "user":
            rounds += 1
            stamp = message.created_at
            if stamp.tzinfo is None:
                stamp = stamp.replace(tzinfo=timezone.utc)
            days.add(stamp.astimezone(timezone(timedelta(hours=8))).date())
            skill = meta.get("skill")
            if isinstance(skill, dict) and skill.get("id"):
                key = str(skill["id"])
                features[key] += 1
                labels[key] = str(skill.get("label") or key)
        elif message.role == "assistant":
            trace = meta.get("trace") if isinstance(meta.get("trace"), dict) else {}
            tokens = meta.get("tokens") or trace.get("tokens") or {}
            if not isinstance(tokens, dict):
                tokens = {}
            incoming, outgoing = number(tokens.get("input")), number(tokens.get("output"))
            input_tokens += incoming
            output_tokens += outgoing
            peak_tokens = max(peak_tokens, incoming + outgoing)
            if not incoming and not outgoing:
                missing += 1
            longest_ms = max(longest_ms, number(meta.get("latencyMs")))
            calls = meta.get("toolCalls")
            if isinstance(calls, list):
                tools += len(calls)
    for run in runs:
        for stage in (run.trace_json or {}).get("stages", []):
            if isinstance(stage, dict) and stage.get("kind") in {"tool", "retrieval"} and stage.get("status") != "running":
                tools += 1
    longest_streak = streak = 0
    previous = None
    for day in sorted(days):
        streak = streak + 1 if previous and day - previous == timedelta(days=1) else 1
        longest_streak = max(longest_streak, streak)
        previous = day
    today = utcnow().astimezone(timezone(timedelta(hours=8))).date()
    current_streak = 0
    cursor = today if today in days else today - timedelta(days=1)
    while cursor in days:
        current_streak += 1
        cursor -= timedelta(days=1)
    return {
        "totalTokens": input_tokens + output_tokens, "inputTokens": input_tokens,
        "outputTokens": output_tokens, "peakTokens": peak_tokens,
        "conversationCount": len(conversations), "messageCount": rounds,
        "longestTaskMs": longest_ms, "longestStreak": longest_streak,
        "currentStreak": current_streak, "activeDays": len(days),
        "toolCallCount": tools, "featureCallCount": sum(features.values()),
        "missingUsageCount": missing,
        "features": [{"id": key, "label": labels[key], "count": count} for key, count in features.most_common()],
    }
