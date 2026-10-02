"""守住文档里那几个**接口规模**数字。

## 为什么只守这三个

文档里的数字分两类，性质完全不同：

- **接口规模**（registry method 数、CLI 命令数、分组数）：变了就意味着**对外
  契约变了**，必须同步文档。这类值得用测试守住。
- **测试数量**（`566 passed`）：每加一个测试就变一次，守它等于给每次改代码
  加一道"顺手改文档"的摩擦，而它承载的信息量远低于上面三个。所以文档里改成
  「560+ tests，以实际输出为准」这种不精确表述，由本文件代为说明真实值。

## 为什么不是扫全部散文

`个 method` 这一个短语在文档里混着**三个不同语义**的数字——总数（123）、
有 CLI 入口的（112）、真空缺口的（5）。正则一扫就全乱了。所以本文件只认
三处**权威声明**，每处用足够独特的锚点定位，锚点变了测试会失败并指出
「该更新锚点」，而不是静默放过。

## 这套闸门自己的历史

第一次全项目复查就是靠 agent 人工比对才发现 README 停在 V0.2.1、
`AGENTS.md` 声称「CLI 全部触达」而实际有 11 个缺口。四份文档各自漂移，
没有一处会自己报警。加这个文件是因为「修了但没有闸门」等于半年后重演。
"""

from __future__ import annotations

import pathlib
import re
import tempfile

import pytest

from project_tool.application.registry import build_registry
from project_tool.application.service import ProjectService
from project_tool.cli.main import cli_surface
from project_tool.storage import init_project

ROOT = pathlib.Path(__file__).resolve().parent.parent


@pytest.fixture(scope="module")
def facts() -> dict[str, int]:
    opened = init_project(pathlib.Path(tempfile.mkdtemp()), name="DocFacts")
    surface = cli_surface()
    return {
        "registry_methods": len(build_registry(ProjectService(opened))),
        "cli_commands": len([c for c in surface if c["kind"] == "command"]),
        "cli_groups": len([c for c in surface if c["kind"] == "group"]),
    }


def read(name: str) -> str:
    return (ROOT / name).read_text(encoding="utf-8")


#: 每份文档一处权威声明。三个数都出现在同一句里，所以一次匹配全拿到。
#: 锚点刻意写死整句——改了措辞测试就会失败，那比静默放过好。
#:
#: 映射值是 `((facts_key, group_name), ...)`：**两个名字**都要给出。
#: `facts_key` 是下面 `facts` 里的键，`group_name` 是上面正则里的命名组——
#: 两者不同名（`cli_commands` vs `commands`），写成同一个就会在
#: `matches.group()` 上抛 IndexError，而那行代码看起来完全合理。
ANCHORS: dict[str, tuple[str, tuple[tuple[str, str], ...]]] = {
    "README.md": (
        r"CLI：(?P<commands>\d+) 个命令 \+ (?P<groups>\d+) 个分组",
        (("cli_commands", "commands"), ("cli_groups", "groups")),
    ),
    "AGENTS.md": (
        r"Service \*\*(?P<methods>\d+)\*\* 个 method，"
        r"CLI 命令 \*\*(?P<commands>\d+)\*\* 个（\+ (?P<groups>\d+) 个分组）",
        (
            ("registry_methods", "methods"),
            ("cli_commands", "commands"),
            ("cli_groups", "groups"),
        ),
    ),
    # 注意这里 `**123 个 method**` 的星号在**文字两侧**，而 AGENTS.md 用的是
    # `**123** 个 method`（星号紧贴数字）—— 两种写法，正则不同。
    "docs/09-handover.md": (
        r"registry，\*\*(?P<methods>\d+) 个 method\*\*；"
        r"CLI \*\*(?P<commands>\d+) 个命令\*\* \+ (?P<groups>\d+) 个分组",
        (
            ("registry_methods", "methods"),
            ("cli_commands", "commands"),
            ("cli_groups", "groups"),
        ),
    ),
}


@pytest.mark.parametrize("doc", sorted(ANCHORS))
def test_documented_interface_size_matches_the_code(doc: str, facts: dict[str, int]):
    pattern, keys = ANCHORS[doc]
    text = read(doc)

    matches = re.search(pattern, text)
    assert matches, (
        f"{doc} 里找不到权威声明（锚点变了）。\n"
        f"期望匹配到形如：{pattern}\n"
        f"如果只是措辞改了，请同步更新 tests/test_docs_facts.py 里的 ANCHORS；"
        f"如果接口规模真的变了，请改文档并确认新数字：{facts}"
    )

    for fact_key, group_name in keys:
        claimed = int(matches.group(group_name))
        assert claimed == facts[fact_key], (
            f"{doc} 说 {fact_key} = {claimed}，实际是 {facts[fact_key]}。"
            f"接口规模变了 = 对外契约变了，文档必须同步。"
        )


def test_docs_facts_gate_covers_every_document_that_states_the_size():
    """守住这份清单本身：新增一份"会声明接口规模"的文档时，别忘了加锚点。

    这类清单最容易腐化成"看起来在守着，实际漏了某份文档"。
    """
    #: 已知会声明接口规模、因此必须有锚点的文档
    must_cover = {
        "README.md",
        "AGENTS.md",
        "docs/09-handover.md",
    }
    assert must_cover <= set(ANCHORS), (
        f"这些文档声明了接口规模但没有锚点：{sorted(must_cover - set(ANCHORS))}"
    )


def test_features_flags_in_docs05_match_the_code(facts):
    """`docs/05` 里那份 features 示例必须和 `system.capabilities` 一致。

    这不是形式检查：第一次全项目复查时 `docs/05` 写着
    `"artifact": false`，而代码里从 V1-A 起就是 `true`——文档与实现相反，
    而且它自己在同一份文件里又把 `artifact.*` 标成已实现。
    """
    opened = init_project(pathlib.Path(tempfile.mkdtemp()), name="DocFeatures")
    actual = ProjectService(opened).call("system.capabilities", {})["features"]

    text = read("docs/05-interfaces.md")
    block = re.search(r'"features"\s*:\s*\{(.*?)\}', text, re.S)
    assert block, "docs/05-interfaces.md 里找不到 features 示例块"

    documented = {
        key: value.lower() == "true"
        for key, value in re.findall(r'"(\w+)"\s*:\s*(true|false)', block.group(1))
    }
    assert documented == actual, (
        f"docs/05 写的 features 与代码不符。\n"
        f"  文档: {documented}\n"
        f"  代码: {actual}"
    )


# ================================================================== 版本号


#: 声明「本文对齐某版本」的文档。锚点是括号里那个版本号。
VERSIONED_DOCS = (
    "README.md",  # ## 状态（V0.6.9）
    "AGENTS.md",  # - 版本 `0.6.9`，
    "docs/02-architecture.md",
    "docs/04-storage.md",
    "docs/05-interfaces.md",
    "docs/08-events.md",
    "docs/09-handover.md",
)

#: 每个文档里版本号出现的形式。顺序与 VERSIONED_DOCS 一致。
VERSION_ANCHORS = (
    r"## 状态（V(?P<v>\d+\.\d+\.\d+)）",
    r"- 版本 `(?P<v>\d+\.\d+\.\d+)`",
    r"架构设计（对齐 v(?P<v>\d+\.\d+\.\d+)）",
    r"存储与一致性设计（对齐 v(?P<v>\d+\.\d+\.\d+)）",
    r"接口规范（对齐 v(?P<v>\d+\.\d+\.\d+)）",
    r"Event Contract（对齐 v(?P<v>\d+\.\d+\.\d+)）",
    r"交接文档（对齐 v(?P<v>\d+\.\d+\.\d+)",
)


@pytest.mark.parametrize("doc,pattern", list(zip(VERSIONED_DOCS, VERSION_ANCHORS, strict=True)))
def test_documented_version_matches_version_py(doc: str, pattern: str):
    """文档里声明的版本必须等于 `project_tool/version.py`。

    加这条的直接原因：AGENTS.md 写着「`version.py` 是唯一版本来源」，
    **它自己却停在 `0.3.1`**，而真实版本已经走到 0.6.9。前一轮复查把它的
    method 数、测试数都改了，单单漏掉版本号——而版本号恰恰是所有数字里
    最显眼的一个。
    """
    import project_tool.version as version_module

    text = read(doc)
    matches = re.search(pattern, text)
    assert matches, (
        f"{doc} 里找不到版本声明（锚点变了）。期望匹配：{pattern}\n"
        f"真实版本是 {version_module.__version__}"
    )
    assert matches.group("v") == version_module.__version__, (
        f"{doc} 说 {matches.group('v')}，version.py 是 {version_module.__version__}"
    )
