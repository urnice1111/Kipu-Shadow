import re
from decimal import Decimal

from app.ingestion.client import Source

MENTION = re.compile(r"<@([A-Z0-9]+)(?:\|[^>]*)?>")


def display_name(user: dict) -> str:
    profile = user.get("profile") or {}
    for value in (
        user.get("real_name"),
        profile.get("real_name"),
        profile.get("display_name"),
        user.get("name"),
    ):
        if value:
            return value
    return ""


def message_author(message: dict, users: dict[str, dict]) -> str:
    if message.get("subtype") == "bot_message" and message.get("username"):
        return message["username"]
    user = users.get(message.get("user", ""))
    name = display_name(user) if user else ""
    return name or message.get("username") or "Usuario desconocido"


def resolve_mentions(text: str, users: dict[str, dict]) -> str:
    def replace(match: re.Match) -> str:
        user = users.get(match.group(1))
        name = display_name(user) if user else ""
        return f"@{name}" if name else match.group(0)

    return MENTION.sub(replace, text)


def build_chat_records(
    channels: list[dict], users: list[dict], messages: dict[str, list[dict]]
) -> list[dict]:
    """messages maps channel name -> raw Slack messages from every date of that channel."""
    by_id = {u["id"]: u for u in users}
    order = {c["name"]: i for i, c in enumerate(channels)}
    rows = []
    for channel, msgs in messages.items():
        for m in msgs:
            rows.append((order.get(channel, len(order)), Decimal(m["ts"]), channel, m))
    rows.sort(key=lambda r: (r[0], r[1]))

    records = []
    for _, _, channel, m in rows:
        records.append(
            {
                "id": m["client_msg_id"],
                "thread_id": f"{channel}:{m.get('thread_ts') or m['ts']}",
                "author": message_author(m, by_id),
                "ts": m["ts"],
                "text": resolve_mentions(m.get("text") or "", by_id),
                "attachments": [
                    {"filename": f.get("name") or f.get("title") or ""} for f in m.get("files") or []
                ],
            }
        )
    return records


def read_chats(source: Source) -> list[dict]:
    channels = source.json("/chats/channels")
    users = source.json("/chats/users")
    messages: dict[str, list[dict]] = {}
    for channel in channels:
        name = channel["name"]
        messages[name] = []
        for date in source.json(f"/chats/{name}"):
            messages[name].extend(source.json(f"/chats/{name}/{date}"))
    return build_chat_records(channels, users, messages)
