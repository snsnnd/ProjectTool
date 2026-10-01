"""接口契约：固定模板的 markdown 文件（V1-C）。

## 为什么不是一等对象

第一版设计是新建 `Interface`（`IFACE-`）一等对象 + 按 kind 注册的 parser。
用户把需求降级成「类似 md 文件、模板随便做」，这个简化是**对的**：

- 接口文档的正文本来就是人写的散文，硬塞进 `spec: dict` 只会让人绕过工具
- diff / blame / 历史 Git 已经做得比任何自建机制好，不该重复造
- 真正的价值是「有一个固定的沟通区域 + 统一模板」，不是类型系统

所以接口 = **工作树里的 markdown 文件 + 注册成 Artifact**。这样：
文件用普通编辑器改、跟着 Git 走；ProjectTool 只负责**固定模板**与**检查**。

## 固定模板换来什么

front-matter 是**机器可读**的（将来做自动索引：谁依赖什么、哪些是 agreed），
必需章节是**强制沟通清单**。`pjt interface check` 把两者都验一遍。

「固定」不是文档里的一句话，而是有测试守着的：
未知 status 报错、缺必需字段报错、缺必需章节报错。

## 边界

- 模板里的字段**故意保持极少**。宁可少也不要一堆没人填的字段——
  没人填的必填字段比没有更糟，它只会训练大家绕过检查。
- `area` 与 Artifact 的 `related_area_ids` 是**双向**的：front-matter 写了
  area 就以它为准并同步进 Artifact，避免两处打架。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from project_tool.domain.errors import InvalidArgument

# ------------------------------------------------------------------ 词汇表

#: 接口状态。`agreed` 是唯一表示「大家认可」的取值，自动索引时只认它。
STATUSES = ("draft", "review", "agreed", "deprecated")

#: front-matter 无条件必填字段。
#:
#: `kind` **不在**这里：它由**这个项目的人**定义，工具不校验也不设默认值
#: （第一版 CLI help 把它写成了封闭集合、还默认 `module_api`，那是把工具的
#: 猜测焊进了数据）。不关心分类的项目可以完全不填；将来做自动索引时
#: 有值的那些自然会被归类。
REQUIRED_FIELDS = ("name", "status", "area")

#: **进入评审前**才必填的字段。
#:
#: 第一版把 `consumers` 也列成必填，结果 `pjt interface init` 不带
#: `--consumer` 直接失败——而「还没想清楚谁在用」恰恰是 draft 阶段的常态。
#: 没人填得上的必填字段比没有更糟：它只会训练大家绕过检查。
#:
#: 所以规则是按 `status` 分级的：`draft` 可以空着，`review`/`agreed`
#: 必须写清消费者。这条规则本身就是「什么时候算谈完」的判据。
CONDITIONAL_FIELDS = {"consumers": ("review", "agreed", "deprecated")}

#: 正文必需章节（按顺序）。刻意少而硬：这几节是「跨 Area 协作」真正会吵架的地方。
REQUIRED_SECTIONS = ("用途", "契约", "变更规则", "兼容策略", "变更历史")

#: 默认落盘位置（相对项目根）。`pjt interface init` 用它，可用 --path 覆盖。
DEFAULT_DIR = "docs/interfaces"

_FM_RE = re.compile(r"\A---\r?\n(.*?)\r?\n---\r?\n", re.S)
_H_RE = re.compile(r"(?m)^##\s+(.+?)\s*$")


# ------------------------------------------------------------------ 极简 front-matter


def parse_front_matter(text: str) -> tuple[dict[str, Any], str, str | None]:
    """拆出 (front-matter 字典, 正文, 错误)。

    只支持本工具自己写出来的形态：`key: value`、以及 `[a, b]` 形式的
    行内列表。刻意不引入 yaml 依赖——依赖越少，20 个人在各自机器上
    装出来的行为越一致（`docs/09-handover.md` 的整体取向）。
    """
    if not text.startswith("---"):
        return {}, text, "missing front-matter: file must start with '---'"
    match = _FM_RE.match(text)
    if match is None:
        return {}, text, "unterminated front-matter: no closing '---'"
    block = match.group(1)
    body = text[match.end():]
    data: dict[str, Any] = {}
    for raw in block.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if ":" not in line:
            return {}, body, f"malformed front-matter line: {raw!r}"
        key, _, value = line.partition(":")
        data[key.strip()] = _coerce(value.strip())
    return data, body, None


def _coerce(value: str) -> Any:
    if value.startswith("[") and value.endswith("]"):
        inner = value[1:-1].strip()
        if not inner:
            return []
        return [item.strip().strip("'\"") for item in inner.split(",") if item.strip()]
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
        return value[1:-1]
    if value in ("true", "false"):
        return value == "true"
    if value.isdigit():
        return int(value)
    return value


def dump_front_matter(data: dict[str, Any]) -> str:
    """只写已知字段，顺序固定——这样模板 diff 干净。"""
    lines = ["---"]
    for key in ("name", "kind", "status", "area", "owners", "consumers", "version"):
        if key not in data or data[key] in (None, "", []):
            continue
        value = data[key]
        if isinstance(value, list):
            rendered = "[" + ", ".join(str(item) for item in value) + "]"
        elif isinstance(value, bool):
            rendered = "true" if value else "false"
        else:
            rendered = str(value)
        lines.append(f"{key}: {rendered}")
    lines.append("---")
    return "\n".join(lines)


# ------------------------------------------------------------------ 校验


@dataclass(frozen=True)
class Finding:
    level: str  # "error" | "warning"
    message: str


def headings(body: str) -> list[str]:
    return [match.strip() for match in _H_RE.findall(body)]


def check_document(text: str, *, require_sections: bool = True) -> list[Finding]:
    """把一份接口文档验一遍。**纯函数**——不碰文件系统，所以好测。"""
    out: list[Finding] = []
    data, body, error = parse_front_matter(text)
    if error is not None:
        return [Finding("error", error)]

    for field in REQUIRED_FIELDS:
        if field not in data or data[field] in ("", []):
            out.append(Finding("error", f"front-matter missing required field: {field}"))

    status = data.get("status")
    if status is not None and status not in STATUSES:
        out.append(
            Finding(
                "error",
                f"unknown status {status!r}; allowed: {', '.join(STATUSES)}",
            )
        )
    elif status in CONDITIONAL_FIELDS.get("consumers", ()):
        if not data.get("consumers"):
            out.append(
                Finding(
                    "error",
                    f"consumers is required once status is {status!r} "
                    "(评审前必须说清谁在依赖这个接口)",
                )
            )

    if require_sections:
        present = headings(body)
        for section in REQUIRED_SECTIONS:
            if section not in present:
                out.append(Finding("error", f"missing required section: ## {section}"))
        if not present:
            out.append(Finding("error", "body has no '## ' sections"))

    body_text = body.strip()
    for section in REQUIRED_SECTIONS:
        if section not in headings(body):
            continue
        chunk = _section_text(body, section)
        if not chunk.strip():
            out.append(
                Finding("warning", f"section '## {section}' is empty — 写了标题没写内容")
            )
    if not body_text:
        out.append(Finding("error", "body is empty"))
    return out


def _section_text(body: str, section: str) -> str:
    """取某个 `## x` 章节到下一个 `## ` 之间的正文。"""
    pattern = re.compile(
        rf"(?m)^##\s+{re.escape(section)}\s*$(.*?)(?=^##\s|\Z)", re.S
    )
    match = pattern.search(body)
    return match.group(1) if match else ""


def require_valid(text: str, *, what: str = "interface document") -> dict[str, Any]:
    """校验失败就抛错——给写路径用（init / 改完再存）。"""
    findings = check_document(text)
    errors = [item for item in findings if item.level == "error"]
    if errors:
        raise InvalidArgument(
            f"{what} is invalid: " + "; ".join(item.message for item in errors)
        )
    data, _, _ = parse_front_matter(text)
    return data


# ------------------------------------------------------------------ 模板


def render_template(
    name: str,
    *,
    kind: str = "module_api",
    area: str = "",
    owners: list[str] | None = None,
    consumers: list[str] | None = None,
    summary: str = "",
    change_rule: str = "",
) -> str:
    """生成一份可直接提交评审的接口文档骨架。

    模板里**不留 TODO 占位符**——空标题比 `TODO` 好，check 会把空章节
    报成 warning，人自己知道要填。
    """
    data = {
        "name": name,
        "kind": kind,
        "status": "draft",
        "area": area,
        "owners": owners or [],
        "consumers": consumers or [],
        "version": 1,
    }
    kind_line = (
        f"kind: {kind}"
        if kind
        else "# kind: 由本项目自定，工具不校验（如 store_api / serial_frame）"
    )
    front = dump_front_matter(data).replace(
        "status: draft", f"{kind_line}\nstatus: draft"
    )
    return f"""{front}

# {name}

## 用途

{summary}

## 契约

输入 / 输出 / 前置条件 / 不变量。能写清「什么情况下它会坏」比列签名有用。

## 变更规则

谁有权改、怎么通知下游。跨 Area 的接口改动必须先在对应 Area 的 task 里说明。
{change_rule}

## 兼容策略

什么算破坏性变更、加字段能不能、老字段什么时候删。
下游没同步就不能删——这一节是后面「接口检查」的依据。

## 变更历史

| 日期 | 改动 | 人 |
|---|---|---|
|  | 初稿 |  |
"""


__all__ = [
    "CONDITIONAL_FIELDS",
    "DEFAULT_DIR",
    "REQUIRED_FIELDS",
    "REQUIRED_SECTIONS",
    "STATUSES",
    "Finding",
    "check_document",
    "dump_front_matter",
    "headings",
    "parse_front_matter",
    "render_template",
    "require_valid",
]
