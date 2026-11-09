from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError
from app import llm, storage
from app.events import tool_call
from app.ingest import pdf

FACT_SCHEMA = {
    "type": "object", "additionalProperties": False, "required": ["facts"],
    "properties": {"facts": {"type": "array", "items": {
        "type": "object", "additionalProperties": False,
        "required": ["id", "name", "value", "unit", "page", "quote"],
        "properties": {"id": {"type": "string"}, "name": {"type": "string"},
                       "value": {"type": "number"}, "unit": {"type": "string"},
                       "page": {"type": "integer"}, "quote": {"type": "string"}}
    }}}
}
SYSTEM = """你是起重机技术文档参数抽取员。只抽取文档中明确写出的数值参数。
quote 必须从原文逐字复制，包含该数值，不超过40字；page 为所在页码。
表格行的 quote 写成『项目名 数值 单位』，例如『额定起重量 1230 t』（原文中项目名与数值之间的换行/空格可省略，核验时会去除空白）。
id 优先使用以下规范 id 与单位：
F_rated_load(t)、F_girder_length(m)、F_overall_height(m)、F_span(m)、F_lift_height(m)、
F_hoist_speed(m/min)、F_trolley_speed(m/min)、F_gantry_speed(m/min)、F_leg_height(m)、
F_girder_height(m)、F_weld_tolerance(mm)、F_total_mass(t)、F_wheel_count(个)。
没有对应的使用 F_ 开头的小写下划线 id。范围值（如 0～8 m/min）取最大值并在 name 中注明「最大」。
不得推算、换算或补全。不要把文件编号和标准编号当成参数。同一参数只抽取一次。"""


class ExtractedFact(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    id: str = Field(pattern=r"^F_[a-z][a-z_]*$")
    name: str
    value: float = Field(allow_inf_nan=False)
    unit: str
    page: int
    quote: str


class FactPatch(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    value: float | None = Field(default=None, allow_inf_nan=False)
    unit: str | None = None
    status: Literal["verified", "needs_review", "confirmed", "rejected"] | None = None


def user_prompt(pages: list[dict]) -> str:
    return "\n\n".join(f"=== 第{page['page']}页 ===\n{page['text']}" for page in pages)


def extract_facts(pid: str, run: str, pdf_path: Path) -> dict:
    with tool_call(pid, run, "ingest", "pdf.extract", "正在抽取文档页文本") as call:
        pages = pdf.extract_pages(pdf_path)
        call.ok(f"已抽取 {len(pages)} 页文档文本")
    with tool_call(pid, run, "ingest", "llm.opus.extract_facts", "正在提取文档中的数值参数") as call:
        result = llm.complete_json("extract_facts", SYSTEM, user_prompt(pages), FACT_SCHEMA, pid=pid)
        try:
            extracted = [ExtractedFact.model_validate(item) for item in result["facts"]]
        except (KeyError, TypeError, ValidationError) as exc:
            raise llm.LLMError("参数抽取结果格式无效") from exc
        call.ok(f"已提取 {len(extracted)} 条候选参数")
    with tool_call(pid, run, "ingest", "verify.facts", "正在逐条核验参数出处") as call:
        page_text = {page["page"]: pdf.normalize(page["text"]) for page in pages}
        facts: dict[str, dict] = {}
        for item in extracted:
            if item.id in facts:
                continue
            quote = pdf.normalize(item.quote)
            number = str(int(item.value)) if item.value.is_integer() else str(item.value)
            verified = bool(quote) and quote in page_text.get(item.page, "") and number in quote
            facts[item.id] = {"id": item.id, "name": item.name, "value": item.value, "unit": item.unit,
                              "source": {"doc": pdf_path.name, "page": item.page, "quote": item.quote},
                              "status": "verified" if verified else "needs_review"}
        count = sum(item["status"] == "verified" for item in facts.values())
        with storage.LOCK:
            existing = storage.read_json(pid, "facts.json", {"facts": []})
            merged = {item["id"]: item for item in existing["facts"]}
            for fid, item in facts.items():
                if merged.get(fid, {}).get("status") not in {"confirmed", "rejected"}:
                    merged[fid] = item
            result = {"facts": list(merged.values())}
            storage.write_json(pid, "facts.json", result)
        summary = f"核验 {len(facts)} 条参数：{count} 条通过，{len(facts) - count} 条待人工确认"
        (call.ok if count == len(facts) else call.warn)(summary)
    return result


def update_fact(pid: str, fid: str, patch: dict) -> dict:
    try:
        checked = FactPatch.model_validate(patch)
        updates = checked.model_dump(exclude_unset=True)
        if any(value is None for value in updates.values()):
            raise ValueError("参数字段不能为 null")
    except ValidationError as exc:
        raise ValueError("参数修改格式无效，仅允许修改数值、单位和状态") from exc
    if "value" in updates:
        updates["status"] = "confirmed"
    with storage.LOCK:
        result = storage.read_json(pid, "facts.json", {"facts": []})
        for item in result["facts"]:
            if item["id"] == fid:
                item.update(updates)
                storage.write_json(pid, "facts.json", result)
                return item
    raise KeyError("参数不存在")
