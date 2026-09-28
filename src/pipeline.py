"""Item dataclass chung + Stage 1 (filter rule-based, rẻ) + Stage 1 LLM batch
ranking + Stage 2 (LLM analyze full 6 mục).

Bước 2+: pipeline.py phình thêm hàm khi build tiếp (đúng kế hoạch ban đầu),
không tách file mới cho mỗi stage.
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from sources.source_registry import get_display_name

logger = logging.getLogger(__name__)

# type ∈ {research, funding, product, deep_tech, outside}
VALID_TYPES = {"research", "funding", "product", "deep_tech", "outside"}


@dataclass
class Item:
    """Đại diện chuẩn hoá cho mọi item từ mọi nguồn (§2 của brief).

    source_tier: mặc định = 3 (an toàn, "chưa uy tín tới khi được thêm vào
    bảng"). Việc tra bảng tier thật (source_registry.py) là bước 3 — ở bước 1
    field này chỉ là stub để các module sau gắn vào, KHÔNG implement registry.
    """

    id: str
    type: str
    title: str
    url: str
    source: str
    published_at: datetime
    raw_text: str = ""
    source_tier: int = 3
    score: float = 0.0

    def __post_init__(self) -> None:
        if self.type not in VALID_TYPES:
            raise ValueError(f"Item.type không hợp lệ: {self.type!r}")


def make_item_id(url: str, title: str) -> str:
    """Hash ổn định của url+title, dùng để dedupe qua state/seen.json."""
    key = f"{url}|{title}".strip().lower()
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]


def hours_since(published_at: datetime, now: Optional[datetime] = None) -> float:
    now = now or datetime.now(timezone.utc)
    if published_at.tzinfo is None:
        published_at = published_at.replace(tzinfo=timezone.utc)
    delta = now - published_at
    return delta.total_seconds() / 3600.0


@dataclass
class ThesisConfig:
    """Subset của thesis.yaml cần cho Stage 1 heuristic scoring + lựa mục outside."""

    tracking: list[str] = field(default_factory=list)
    deep_tech_tracking: list[str] = field(default_factory=list)
    keywords_boost: list[str] = field(default_factory=list)
    outside_lane_domains: list[str] = field(default_factory=list)


def score_item(item: Item, thesis: ThesisConfig, now: Optional[datetime] = None) -> float:
    """Heuristic Stage 1 (rule-based, không gọi LLM):
    - khớp keyword trong thesis.tracking / deep_tech_tracking / keywords_boost
    - độ mới (item mới hơn -> điểm cao hơn, giảm dần trong 24h)
    - HN points (đã chấm điểm sẵn trong item.score lúc fetch, cộng dồn vào đây)
    - match category arXiv (đã phản ánh qua item.type == "research")

    Trả về điểm số càng cao càng ưu tiên giữ lại ở Stage 1.
    """
    text = f"{item.title} {item.raw_text}".lower()
    score = 0.0

    # Khớp keyword thesis — mỗi từ khoá khớp +2 điểm.
    all_keywords = (
        thesis.tracking + thesis.deep_tech_tracking + thesis.keywords_boost
    )
    for kw in all_keywords:
        # so khớp từng từ trong cụm keyword (đơn giản, không cần NLP ở bước 1)
        kw_tokens = [t for t in kw.lower().replace("/", " ").split() if len(t) > 2]
        if kw_tokens and any(t in text for t in kw_tokens):
            score += 2.0

    # Độ mới: tuyến tính giảm từ +5 (vừa đăng) về 0 (24h trước).
    age_h = hours_since(item.published_at, now)
    freshness = max(0.0, 5.0 * (1 - age_h / 24.0))
    score += freshness

    # HN points / nguồn đã chấm sẵn (item.score được set lúc fetch, ví dụ
    # points HN scale xuống). Cộng trực tiếp vào heuristic tổng.
    score += item.score

    return round(score, 3)


def dedupe_against_seen(items: list[Item], seen_ids: set[str]) -> list[Item]:
    """Bỏ item đã có trong state/seen.json (theo hash id)."""
    return [it for it in items if it.id not in seen_ids]


def filter_stage1(
    items: list[Item],
    thesis: ThesisConfig,
    seen_ids: Optional[set[str]] = None,
    keep_top_n: int = 20,
    now: Optional[datetime] = None,
) -> list[Item]:
    """Stage 1 đầy đủ: dedupe -> chấm điểm heuristic -> cắt còn top N.

    Quyết định kỹ thuật (khác bước 1): cắt top N theo TỪNG type, không cắt
    top N toàn cục. Lý do: từ bước 2 có thêm nhiều nguồn (funding, product,
    deep_tech, github_trending...) với phân phối điểm rất khác nhau — ví dụ
    GitHub Trending luôn được +5 điểm "độ mới" (vì feed không có ngày publish
    theo từng repo, dùng now() làm published_at) nên có thể áp đảo hoàn toàn
    top-20 toàn cục, khiến funding/deep_tech bị loại sạch trước khi tới bước
    phân bổ theo cơ cấu (Stage 1 LLM ranking/allocation cần candidate từ MỌI
    type). Cắt theo từng type đảm bảo mọi nhánh (research/funding/product/
    deep_tech) đều có candidate sống sót để Stage 1 allocation chọn đúng cơ
    cấu 2 research/1 funding/1 product/1 deep_tech/1 outside.
    """
    seen_ids = seen_ids or set()
    deduped = dedupe_against_seen(items, seen_ids)

    for it in deduped:
        it.score = score_item(it, thesis, now=now)

    by_type: dict[str, list[Item]] = {}
    for it in deduped:
        by_type.setdefault(it.type, []).append(it)

    result: list[Item] = []
    # Chia keep_top_n đều cho số type đang có mặt, tối thiểu 4/type để mỗi
    # nhánh luôn có vài candidate cho LLM ranking lựa (không chỉ đúng 1).
    n_types = max(len(by_type), 1)
    # Tối thiểu 8/type (tăng từ 4): TARGET_ALLOCATION giờ cần tới 3 item/type
    # (research), nên pool candidate cho LLM ranking lựa phải rộng hơn allocation
    # khá nhiều, không chỉ đủ vừa khít.
    per_type_n = max(keep_top_n // n_types, 8)

    for item_type, type_items in by_type.items():
        type_items.sort(key=lambda it: it.score, reverse=True)
        result.extend(type_items[:per_type_n])

    result.sort(key=lambda it: it.score, reverse=True)
    return result


# Cơ cấu mục tiêu sau khi xếp hạng LLM batch (§5), MỞ RỘNG theo yêu cầu
# operator (digest "đầy đủ hơn"): tăng từ tổng ~6 lên ~11 item, mỗi mục có
# nhiều hơn 1 ví dụ để Stage 2 phân tích sâu/đa chiều hơn, không chỉ 1 lát
# cắt mỗi mục.
TARGET_ALLOCATION: dict[str, int] = {
    "research": 3,
    "funding": 2,
    "product": 2,
    "deep_tech": 2,
    "outside": 2,
}


def tag_outside_candidates(items: list, thesis: "ThesisConfig") -> list:
    """Không có nguồn nào tự nhiên emit type="outside" (§4 brief không định
    nghĩa fetcher riêng cho outside-lane, chỉ định nghĩa outside_lane_domains
    trong thesis.yaml như "chủ đề lệch khỏi thesis chính"). Quyết định kỹ
    thuật: tự retag item nào KHÔNG match thesis.tracking/deep_tech_tracking
    nhưng CÓ match outside_lane_domains thành type="outside" (copy, không sửa
    item gốc, để không phá vỡ phân loại research/funding/product/deep_tech
    dùng trong các bước khác).

    Nếu không tìm thấy ứng viên nào match outside_lane_domains, vẫn không bịa
    type — Stage 1.5/2 sẽ tự nói "không có ứng viên outside" qua allocation
    rỗng (đúng yêu cầu thà thiếu còn hơn ép tin không liên quan).
    """
    if not thesis.outside_lane_domains:
        return items

    import copy as _copy

    outside_keywords = []
    for kw in thesis.outside_lane_domains:
        tokens = [t for t in kw.lower().replace("/", " ").split() if len(t) > 2]
        outside_keywords.extend(tokens)

    thesis_keywords = []
    for kw in thesis.tracking + thesis.deep_tech_tracking:
        tokens = [t for t in kw.lower().replace("/", " ").split() if len(t) > 2]
        thesis_keywords.extend(tokens)

    tagged = []
    for it in items:
        text = f"{it.title} {it.raw_text}".lower()
        matches_outside = any(kw in text for kw in outside_keywords)
        matches_thesis = any(kw in text for kw in thesis_keywords)

        if matches_outside and not matches_thesis and it.type != "deep_tech":
            outside_copy = _copy.copy(it)
            outside_copy.type = "outside"
            tagged.append(outside_copy)
        else:
            tagged.append(it)

    return tagged


def _select_by_allocation(
    items: list, allocation: dict[str, int]
) -> list:
    """Chọn item theo đúng cơ cấu type, ưu tiên score cao nhất trong từng type.

    Dùng làm fallback khi không có LLM (heuristic thuần) VÀ làm bước chốt
    sau khi LLM xếp hạng lại thứ tự ưu tiên trong từng type.
    """
    selected = []
    by_type: dict[str, list] = {}
    for it in items:
        by_type.setdefault(it.type, []).append(it)
    for t in by_type:
        by_type[t].sort(key=lambda it: it.score, reverse=True)

    for item_type, count in allocation.items():
        candidates = by_type.get(item_type, [])
        selected.extend(candidates[:count])

    return selected


def _build_ranking_prompt(items: list, thesis: "ThesisConfig") -> str:
    lines = [
        "Đây là thesis của operator (lăng kính để đánh giá độ liên quan):",
        f"- tracking: {', '.join(thesis.tracking)}",
        f"- deep_tech_tracking: {', '.join(thesis.deep_tech_tracking)}",
        f"- keywords_boost: {', '.join(thesis.keywords_boost)}",
        "",
        "Dưới đây là danh sách item đã fetch, mỗi item có id số thứ tự, type, "
        "title, source. Hãy xếp hạng lại độ liên quan với thesis TRONG TỪNG "
        "type (không đổi type). Trả về DUY NHẤT một JSON object dạng "
        '{"ranked_ids": {"research": [id,...], "funding": [id,...], '
        '"product": [id,...], "deep_tech": [id,...], "outside": [id,...]}}, '
        "id sắp theo độ liên quan giảm dần. Không thêm chữ nào ngoài JSON.",
        "",
    ]
    for idx, it in enumerate(items):
        lines.append(f"id={idx} type={it.type} source={it.source} title={it.title}")
    return "\n".join(lines)


def llm_rank_and_select(
    items: list,
    thesis: "ThesisConfig",
    llm_client,
    allocation: dict[str, int] = TARGET_ALLOCATION,
) -> list:
    """Gọi LLM 1 lần (batch) để xếp hạng lại độ liên quan trong từng type, sau
    đó chọn theo cơ cấu allocation. Nếu LLM lỗi/parse fail -> fallback về
    heuristic score thuần (_select_by_allocation trên item.score gốc).

    Đây là phần "tăng dần, fallback an toàn" theo yêu cầu: pipeline KHÔNG được
    crash chỉ vì thiếu API key — fallback graceful, log rõ.
    """
    if llm_client is None:
        logger.warning(
            "llm_rank_and_select: không có llm_client (thiếu key) -> fallback "
            "heuristic score thuần, không gọi LLM batch ranking."
        )
        return _select_by_allocation(items, allocation)

    try:
        prompt = _build_ranking_prompt(items, thesis)
        response = llm_client.generate(prompt)
        logger.info(
            "Stage 1 LLM ranking [%s]: input_tokens=%s output_tokens=%s",
            response.engine,
            response.input_tokens,
            response.output_tokens,
        )
        text = response.text.strip()
        if text.startswith("```"):
            text = text.strip("`")
            if text.lower().startswith("json"):
                text = text[4:]
        parsed = json.loads(text)
        ranked_ids = parsed["ranked_ids"]

        selected = []
        for item_type, count in allocation.items():
            ids_for_type = ranked_ids.get(item_type, [])
            chosen = 0
            for idx in ids_for_type:
                if not isinstance(idx, int) or idx < 0 or idx >= len(items):
                    continue
                if items[idx].type != item_type:
                    continue
                selected.append(items[idx])
                chosen += 1
                if chosen >= count:
                    break
            if chosen < count:
                # LLM không trả đủ id cho type này -> bù bằng heuristic score.
                by_type_fallback = [it for it in items if it.type == item_type]
                by_type_fallback.sort(key=lambda it: it.score, reverse=True)
                already_ids = {it.id for it in selected}
                for it in by_type_fallback:
                    if it.id in already_ids:
                        continue
                    selected.append(it)
                    chosen += 1
                    if chosen >= count:
                        break
        return selected
    except Exception as exc:  # noqa: BLE001 - LLM lỗi không được sập Stage 1
        logger.warning(
            "llm_rank_and_select: LLM batch ranking lỗi (%s) -> fallback heuristic "
            "score thuần.",
            exc,
        )
        return _select_by_allocation(items, allocation)


def build_kb_summary(kb: dict, top_n: int = 5) -> str:
    """Tóm tắt knowledge base hiện tại (top themes/investors/tech) để feed vào
    Stage 2 prompt — đúng §5: "tóm tắt knowledge base hiện tại (top themes/
    investors/tech đang nổi, lấy từ kb.json)"."""

    def _top(category: dict, n: int) -> list[str]:
        ranked = sorted(category.items(), key=lambda kv: kv[1].get("count", 0), reverse=True)
        return [f"{name} (x{info.get('count', 0)})" for name, info in ranked[:n]]

    parts = []
    themes = _top(kb.get("themes", {}), top_n)
    companies = _top(kb.get("companies", {}), top_n)
    investors = _top(kb.get("investors", {}), top_n)
    tech = _top(kb.get("tech", {}), top_n)
    deep_tech = _top(kb.get("deep_tech", {}), top_n)

    if themes:
        parts.append(f"Themes đang nổi: {', '.join(themes)}")
    if companies:
        parts.append(f"Companies đã thấy nhiều lần: {', '.join(companies)}")
    if investors:
        parts.append(f"Investors đã thấy nhiều lần: {', '.join(investors)}")
    if tech:
        parts.append(f"Tech đang lặp lại: {', '.join(tech)}")
    if deep_tech:
        parts.append(f"Deep tech/nguyên lý đang lặp lại: {', '.join(deep_tech)}")

    return "\n".join(parts) if parts else "(Knowledge base còn rỗng, chưa có pattern tích luỹ.)"


def _build_analysis_prompt(
    verified_items: list, thesis: "ThesisConfig", kb_summary: str
) -> str:
    """Build user prompt cho Stage 2 — system prompt riêng (prompts.py),
    đây là phần "data" đưa vào: thesis + 6 item đã verify + kb summary."""
    lines = [
        "=== THESIS (lăng kính phân tích) ===",
        f"tracking: {', '.join(thesis.tracking)}",
        f"deep_tech_tracking: {', '.join(thesis.deep_tech_tracking)}",
        f"keywords_boost: {', '.join(thesis.keywords_boost)}",
        "",
        "=== KNOWLEDGE BASE HIỆN TẠI (pattern đang tích luỹ) ===",
        kb_summary,
        "",
        "=== ITEM ĐÃ CHỌN (kèm nhãn confidence đã gắn sẵn từ verify.py — DÙNG "
        "LẠI nhãn này, KHÔNG tự đổi) ===",
    ]
    for v in verified_items:
        it = v.item
        # Tính sẵn tên nguồn đẹp (vd "techcrunch.com" -> "TechCrunch") bằng
        # code, KHÔNG để LLM tự "dịch" — LLM hay lười và giữ nguyên domain thô
        # dù prompt đã cho ví dụ (xem source_registry.get_display_name).
        source_display = get_display_name(it.source)
        lines.append(
            f"\n[type={it.type}] confidence={v.confidence_emoji} "
            f"(tier={v.source_tier}, cross_confirmed={v.cross_confirmed})\n"
            f"Title: {it.title}\nSource display name (DÙNG ĐÚNG TÊN NÀY khi "
            f"trích dẫn, không tự đổi): {source_display}\nURL: {it.url}\n"
            f"Nội dung: {it.raw_text[:1500]}"
        )
    return "\n".join(lines)


@dataclass
class AnalysisResult:
    digest_text: str
    kb_update: Optional[dict] = None
    engine: Optional[str] = None
    input_tokens: Optional[int] = None
    output_tokens: Optional[int] = None
    json_parse_error: Optional[str] = None


def _split_digest_and_json(raw_text: str) -> tuple[str, Optional[dict], Optional[str]]:
    """Tách digest markdown và JSON block cuối (sau dòng '---JSON---').

    Parse an toàn (strip ```), nếu parse fail vẫn trả digest, kèm lỗi để log
    (đúng §5: "Parse JSON an toàn (strip ```), nếu parse fail thì vẫn gửi
    digest, log lỗi.")
    """
    marker = "---JSON---"
    if marker not in raw_text:
        return raw_text.strip(), None, "Không tìm thấy marker ---JSON--- trong response"

    digest_part, _, json_part = raw_text.partition(marker)
    digest_text = digest_part.strip()
    json_text = json_part.strip()

    if json_text.startswith("```"):
        json_text = json_text.strip("`")
        if json_text.lower().startswith("json"):
            json_text = json_text[4:].strip()

    try:
        kb_update = json.loads(json_text)
        return digest_text, kb_update, None
    except json.JSONDecodeError as exc:
        return digest_text, None, f"JSON parse lỗi: {exc}"


def analyze_stage2(
    verified_items: list,
    thesis: "ThesisConfig",
    kb_summary: str,
    llm_client,
    system_prompt: str,
) -> AnalysisResult:
    """Stage 2 — gọi LLM thật 1 lần với ~6 item đã verify + thesis + kb_summary.

    Nếu llm_client là None (thiếu cả GEMINI_API_KEY và DEEPSEEK_API_KEY) ->
    trả AnalysisResult với digest_text là thông báo rõ ràng "thiếu key", KHÔNG
    crash pipeline (yêu cầu: degrade gracefully).
    """
    if llm_client is None:
        msg = (
            "[Stage 2 KHÔNG chạy được] Thiếu GEMINI_API_KEY và DEEPSEEK_API_KEY "
            "trong biến môi trường — không thể gọi LLM để phân tích. Đã fetch + "
            "filter + verify thành công, nhưng digest đầy đủ 6 mục cần ít nhất 1 "
            "trong 2 key trên. Thêm key vào .env hoặc GitHub Secrets rồi chạy lại."
        )
        logger.warning(msg)
        return AnalysisResult(digest_text=msg, kb_update=None, json_parse_error="missing_llm_key")

    prompt = _build_analysis_prompt(verified_items, thesis, kb_summary)
    try:
        response = llm_client.generate(prompt, system=system_prompt)
    except Exception as exc:  # noqa: BLE001 - Stage 2 lỗi không được sập toàn pipeline
        msg = f"[Stage 2 LỖI] Gọi LLM thất bại: {exc}"
        logger.error(msg)
        return AnalysisResult(digest_text=msg, kb_update=None, json_parse_error=str(exc))

    logger.info(
        "Stage 2 analyze [%s]: input_tokens=%s output_tokens=%s (log để kiểm "
        "chứng chi phí ~$0)",
        response.engine,
        response.input_tokens,
        response.output_tokens,
    )

    digest_text, kb_update, parse_error = _split_digest_and_json(response.text)
    if parse_error:
        logger.warning("Stage 2: %s", parse_error)

    return AnalysisResult(
        digest_text=digest_text,
        kb_update=kb_update,
        engine=response.engine,
        input_tokens=response.input_tokens,
        output_tokens=response.output_tokens,
        json_parse_error=parse_error,
    )
