"""Stage 3 — Accumulate (§6 của brief): đọc/ghi/append knowledge/kb.json,
lưu digest vào archive/YYYY-MM-DD.md, cập nhật state/seen.json.

Đây là LỚP TÍCH LUỸ quan trọng nhất theo brief — không cắt gọn.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

EMPTY_KB = {
    "themes": {},
    "companies": {},
    "investors": {},
    "tech": {},
    "deep_tech": {},
}


def load_kb(path: Path) -> dict:
    if not path.exists():
        logger.info("memory.py: %s chưa tồn tại, khởi tạo kb rỗng.", path)
        return json.loads(json.dumps(EMPTY_KB))  # deep copy đơn giản

    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        for key in EMPTY_KB:
            data.setdefault(key, {})
        return data
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("memory.py: lỗi đọc %s, dùng kb rỗng: %s", path, exc)
        return json.loads(json.dumps(EMPTY_KB))


def save_kb(kb: dict, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(kb, f, ensure_ascii=False, indent=2, sort_keys=True)
        f.write("\n")


def _today_str() -> str:
    return datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d")


def _merge_simple_list(kb_section: dict, names: list, today: str) -> None:
    """themes/tech: list[str] -> merge count + first_seen/last_seen."""
    for name in names:
        if not isinstance(name, str) or not name.strip():
            continue
        name = name.strip()
        entry = kb_section.setdefault(
            name, {"count": 0, "first_seen": today, "last_seen": today, "notes": []}
        )
        entry["count"] = entry.get("count", 0) + 1
        entry["last_seen"] = today
        entry.setdefault("first_seen", today)
        entry.setdefault("notes", [])


def _merge_companies(kb_section: dict, investors_section: dict, companies: list, today: str) -> None:
    """Merge companies vào kb_section; investors nhắc tới trong mỗi round cũng
    được tích vào investors_section (đồng bộ, truyền trực tiếp thay vì global)."""
    for c in companies:
        if not isinstance(c, dict):
            continue
        name = (c.get("name") or "").strip()
        if not name:
            continue
        entry = kb_section.setdefault(
            name, {"count": 0, "rounds": [], "first_seen": today, "last_seen": today}
        )
        entry["count"] = entry.get("count", 0) + 1
        entry["last_seen"] = today
        entry.setdefault("first_seen", today)
        round_info = {"round": c.get("round"), "investors": c.get("investors", []), "date": today}
        entry.setdefault("rounds", []).append(round_info)

        # Investors xuất hiện trong company round cũng được tích vào "investors".
        for investor in c.get("investors") or []:
            if not isinstance(investor, str) or not investor.strip():
                continue
            inv_entry = investors_section.setdefault(
                investor.strip(),
                {"count": 0, "pattern_notes": [], "first_seen": today, "last_seen": today},
            )
            inv_entry["count"] = inv_entry.get("count", 0) + 1
            inv_entry["last_seen"] = today
            inv_entry.setdefault("first_seen", today)


def _merge_deep_tech(kb_section: dict, deep_tech_items: list, today: str) -> None:
    for dt in deep_tech_items:
        if not isinstance(dt, dict):
            continue
        name = (dt.get("name") or "").strip()
        if not name:
            continue
        entry = kb_section.setdefault(
            name,
            {
                "count": 0,
                "domain": dt.get("domain", ""),
                "first_seen": today,
                "last_seen": today,
            },
        )
        entry["count"] = entry.get("count", 0) + 1
        entry["last_seen"] = today
        entry.setdefault("first_seen", today)
        if dt.get("domain"):
            entry["domain"] = dt["domain"]


def merge_kb_update(kb: dict, kb_update: Optional[dict], today: Optional[str] = None) -> dict:
    """Merge block JSON từ Stage 2 vào kb.json đang có (§6 schema).

    kb_update có thể None (Stage 2 LLM lỗi/thiếu key/parse fail) -> không
    merge gì, trả kb nguyên trạng (KHÔNG crash).
    """
    today = today or _today_str()
    for key in EMPTY_KB:
        kb.setdefault(key, {})

    if not kb_update:
        logger.info("memory.py: không có kb_update (Stage 2 không trả JSON hợp lệ) -> giữ kb nguyên trạng.")
        return kb

    try:
        _merge_simple_list(kb["themes"], kb_update.get("themes", []) or [], today)
        _merge_simple_list(kb["tech"], kb_update.get("tech", []) or [], today)
        _merge_companies(
            kb["companies"], kb["investors"], kb_update.get("companies", []) or [], today
        )
        _merge_deep_tech(kb["deep_tech"], kb_update.get("deep_tech", []) or [], today)
    except Exception as exc:  # noqa: BLE001 - merge lỗi không được làm mất kb cũ
        logger.warning("memory.py: lỗi merge kb_update, giữ kb trước đó: %s", exc)

    return kb


def save_archive(digest_text: str, archive_dir: Path, date_str: Optional[str] = None) -> Path:
    """Lưu digest vào archive/YYYY-MM-DD.md."""
    date_str = date_str or _today_str()
    archive_dir.mkdir(parents=True, exist_ok=True)
    path = archive_dir / f"{date_str}.md"
    with open(path, "w", encoding="utf-8") as f:
        f.write(digest_text.rstrip() + "\n")
    logger.info("memory.py: đã lưu digest vào %s", path)
    return path


def load_seen_ids(path: Path) -> set[str]:
    if not path.exists():
        return set()
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return set(data.get("seen_ids", []))
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("memory.py: không đọc được %s, coi như rỗng: %s", path, exc)
        return set()


def update_seen_ids(
    path: Path, new_ids: list[str], max_keep: int = 5000
) -> set[str]:
    """Thêm new_ids vào state/seen.json. Giới hạn max_keep để file không phình
    vô hạn theo thời gian (giữ id mới nhất — quyết định kỹ thuật vì brief
    không nói rõ chiến lược trim)."""
    existing = load_seen_ids(path)
    merged = list(existing) + [i for i in new_ids if i not in existing]
    if len(merged) > max_keep:
        merged = merged[-max_keep:]

    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"seen_ids": merged}, f, ensure_ascii=False, indent=2)
        f.write("\n")

    return set(merged)
