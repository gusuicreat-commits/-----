"""独立命令行的文件读写和格式检查。"""
import argparse
import json
import math
from pathlib import Path
import sys
from typing import Any


class Parser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        self.exit(2, f"命令参数无效：{message}；请运行 --help 查看必填参数与可选值。\n")


def read_json(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError) as exc:
        raise ValueError(f"无法读取 JSON 文件 {path}：请检查路径、UTF-8 编码和 JSON 语法（{exc}）") from exc
    if not isinstance(value, dict):
        raise ValueError(f"文件 {path} 的顶层必须为对象")
    return value


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def fail(exc: Exception) -> int:
    print(f"处理失败：{exc}", file=sys.stderr)
    return 2


def schema_errors(value: Any, schema: dict, field: str = "shotlist") -> list[dict]:
    """执行随包 schema 使用的关键字；不依赖第三方校验库。"""
    errors: list[dict] = []

    def add(message: str) -> None:
        errors.append({"field": field, "message": message, "fix": f"修改 {field}：{message}"})

    types = {
        "object": isinstance(value, dict), "array": isinstance(value, list),
        "string": isinstance(value, str), "null": value is None,
        "number": isinstance(value, (float, int)) and not isinstance(value, bool) and math.isfinite(value),
        "integer": isinstance(value, int) and not isinstance(value, bool),
    }
    if "type" in schema and not any(types.get(t, False) for t in (
        schema["type"] if isinstance(schema["type"], list) else [schema["type"]]
    )):
        add(f"应为 {schema['type']} 类型，数字必须有限")
        return errors
    if "const" in schema and value != schema["const"]:
        add(f"固定值应为 {schema['const']}")
    if "enum" in schema and value not in schema["enum"]:
        add("可选值：" + "、".join(map(str, schema["enum"])))
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if "exclusiveMinimum" in schema and value <= schema["exclusiveMinimum"]:
            add(f"必须大于 {schema['exclusiveMinimum']}")
        if "minimum" in schema and value < schema["minimum"]:
            add(f"不得小于 {schema['minimum']}")
    if isinstance(value, str) and len(value) < schema.get("minLength", 0):
        add("不得为空字符串")
    if isinstance(value, list):
        if len(value) < schema.get("minItems", 0):
            add(f"至少需要 {schema['minItems']} 个条目")
        if schema.get("uniqueItems") and len({json.dumps(v, sort_keys=True) for v in value}) != len(value):
            add("条目不得重复")
        for i, item in enumerate(value):
            errors.extend(schema_errors(item, schema.get("items", {}), f"{field}[{i}]"))
    if isinstance(value, dict):
        for key in schema.get("required", []):
            if key not in value:
                errors.append({"field": f"{field}.{key}", "message": "缺少必填字段", "fix": f"补充 {field}.{key}"})
        for key, item in value.items():
            props = schema.get("properties", {})
            if key in props:
                errors.extend(schema_errors(item, props[key], f"{field}.{key}"))
            elif schema.get("additionalProperties") is False:
                add(f"不支持字段 {key}；可用字段：{'、'.join(props)}")
    for branch in schema.get("allOf", []):
        if "if" not in branch:
            errors.extend(schema_errors(value, branch, field))
        elif not schema_errors(value, branch["if"], field):
            errors.extend(schema_errors(value, branch.get("then", {}), field))
    return errors
