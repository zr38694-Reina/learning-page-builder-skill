#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""扫描「AI 相关概念解析」卡可用素材。

来源从「本页正文」放宽到「本页正文 + 本课在大纲里的那一节」，
定义一律取自同目录的 ai_concepts.json（概念词典，随 skill 版本化）。

算法：确定性扫描 + 拼装。脚本不做判断——
最终「选哪 3 条、未收录词的 1–2 句定义怎么写」由 Claude 拍板，
写完顺手补进词典（词典边用边长）。

仅标准库：json / re / sys / argparse / pathlib / html

用法：
    python3 scan_ai_concepts.py --page 页.html --outline 大纲.md
    python3 scan_ai_concepts.py --page 页.html --outline 大纲.md --section "环节 3｜第一版 v1"
    python3 scan_ai_concepts.py --page 页.html --outline 大纲.md --json
"""

import argparse
import html
import json
import re
import sys
from pathlib import Path

DICT_FILE = "ai_concepts.json"

# D 段用：疑似 AI 词但词典尚未收录的候选（脚本只会「提示补词典」，不自动下定义）
WATCHLIST = [
    "神经网络", "深度学习", "机器学习", "训练数据", "数据集", "标注",
    "强化学习", "RLHF", "对齐", "蒸馏", "量化", "剪枝",
    "分词", "词表", "采样", "top-p", "top_k", "beam search",
    "护栏", "越狱", "提示注入", "评测", "基准", "benchmark",
    "语音识别", "图像生成", "扩散模型", "文生图", "语音合成",
    "会话历史", "会话", "长文本", "文档切块", "分块", "重排", "rerank",
    "混合检索", "语义搜索", "指令微调", "思维树", "自洽性",
    "向量", "余弦相似度", "索引", "召回", "精排",
    "自动化", "批处理", "流式输出", "结构化输出", "函数库",
    "多智能体", "编排器", "状态机", "钩子", "hook",
    "本地模型", "开源模型", "闭源模型", "推理成本", "显存",
    "Copilot", "Cursor", "Claude", "GPT", "Gemini", "DeepSeek", "Qwen", "Kimi",
]


# ---------- 输入读取 ----------

def strip_html(raw: str) -> str:
    """粗剥 HTML：去 script/style，去标签，还原实体。"""
    raw = re.sub(r"(?is)<(script|style)\b.*?</\1>", " ", raw)
    raw = re.sub(r"(?s)<!--.*?-->", " ", raw)
    raw = re.sub(r"(?s)<[^>]+>", " ", raw)
    raw = html.unescape(raw)
    return re.sub(r"[ \t ]+", " ", raw)


def read_text(path: Path) -> str:
    text = path.read_text(encoding="utf-8", errors="ignore")
    if path.suffix.lower() in (".html", ".htm"):
        return strip_html(text)
    return text


HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)$")


def split_section(outline: str, section: str):
    """取大纲里 `section` 这个标题到下一个同级（或更高级）标题之间的那段。

    返回 (匹配到的标题原文, 段落文本)；找不到返回 (None, None)。
    """
    lines = outline.splitlines()
    start = level = None
    title = None
    for i, line in enumerate(lines):
        m = HEADING_RE.match(line.strip())
        if not m:
            continue
        if section in m.group(2):
            start, level, title = i, len(m.group(1)), m.group(2).strip()
            break
    if start is None:
        return None, None

    out = []
    for line in lines[start + 1:]:
        m = HEADING_RE.match(line.strip())
        if m and len(m.group(1)) <= level:
            break
        out.append(line)
    return title, "\n".join(out)


# ---------- 匹配 ----------

def build_pattern(alias: str):
    """词条别名 → 正则。纯 ASCII 的加左右边界，避免 API 命中 rapid / CLI 命中 client。"""
    esc = re.escape(alias)
    if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9 \-_.]*", alias):
        return re.compile(r"(?<![A-Za-z0-9])" + esc + r"s?(?![A-Za-z0-9])", re.IGNORECASE)
    return re.compile(esc)


def load_dict(path: Path):
    data = json.loads(path.read_text(encoding="utf-8"))
    return {k: v for k, v in data.items() if not k.startswith("_")}


def scan(entries, text: str):
    """返回 [(key, count, first_pos), ...]，按出现顺序。"""
    hits = []
    for key, entry in entries.items():
        total, first = 0, None
        for alias in entry.get("aliases", []):
            pat = build_pattern(alias)
            for m in pat.finditer(text):
                total += 1
                if first is None or m.start() < first:
                    first = m.start()
        if total:
            hits.append((key, total, first))
    hits.sort(key=lambda h: (h[2], h[0]))
    return hits


def rank(page_hits, outline_hits):
    """本页权重 2、大纲权重 1；同分按首次出现位置靠前优先。

    只用于「哪些词值得进卡」的粗排；卡片草案另按本页优先（rank_page_first）。
    """
    counts = {}
    for key, c, pos in page_hits:
        counts[key] = counts.get(key, {"n": 0, "pos": pos, "page": 0, "outline": 0})
        counts[key]["n"] += 2 * c
        counts[key]["page"] = c
        counts[key]["pos"] = min(counts[key]["pos"], pos)
    for key, c, pos in outline_hits:
        d = counts.setdefault(key, {"n": 0, "pos": pos, "page": 0, "outline": 0})
        d["n"] += c
        d["outline"] = c
        d["pos"] = min(d["pos"], pos)
    return sorted(counts.items(), key=lambda kv: (-kv[1]["n"], kv[1]["pos"]))


def rank_page_first(page_hits, outline_hits):
    """卡片草案的排序：**本页命中优先**（按本页频次，再按首现位置），

    本页没有的词才轮到大纲。红线要求「三句里至少两句点着本页」，
    所以草案必须以本页概念打底，绝不能被大纲里出现几十次的词顶掉。
    """
    ranked = []
    for key, c, pos in sorted(page_hits, key=lambda h: (-h[1], h[2])):
        ranked.append((key, {"page": c, "outline": 0, "pos": pos}))
    outline_ranked = rank([], outline_hits)
    seen = {k for k, _ in ranked}
    for key, meta in outline_ranked:
        if key not in seen:
            ranked.append((key, meta))
    return ranked


def build_drafts(ranked, entries, slots=3):
    """按槽位拼装卡片草案：① formal+def ② confusable+diff ③ verify。"""
    if not ranked:
        return []

    drafts = []
    top_key = ranked[0][0]
    top = entries[top_key]

    drafts.append({
        "slot": "① 正式叫什么",
        "key": top_key,
        "text": "{}：{}".format(top.get("formal", top_key), top.get("def", "")),
    })

    # ② 易混区分：优先用「另一个概念」，没有就用首选概念自己的易混词
    second_key, second = None, None
    for key, _meta in ranked[1:]:
        if entries[key].get("confusable"):
            second_key, second = key, entries[key]
            break
    if second is None and top.get("confusable"):
        second_key, second = top_key, top
    if second:
        drafts.append({
            "slot": "② 别和它搞混",
            "key": second_key,
            "confusable": second.get("confusable"),
            "text": "别和「{}」搞混：{}".format(second.get("confusable"), second.get("diff", "")),
        })

    # ③ 30 秒验证
    for key, _meta in ranked:
        if entries[key].get("verify"):
            drafts.append({
                "slot": "③ 花 30 秒验一下",
                "key": key,
                "text": entries[key]["verify"],
            })
            break

    return drafts[:slots]


# ---------- 输出 ----------

def render(result):
    L = []
    A, B, C, D = result["A"], result["B"], result["C"], result["D"]
    L.append("== 概念扫描 ==")
    L.append("本页：{}".format(result["page"]))
    L.append("大纲：{}{}".format(
        result["outline"],
        "｜本节：{}".format(result["section_title"]) if result["section_title"] else "（全文）",
    ))
    if result["section_requested"] and not result["section_title"]:
        L.append("⚠️ 大纲里没找到本节标题「{}」，已退化为扫全文。".format(result["section_requested"]))
    L.append("")

    L.append("── A｜本页出现且词典命中（{} 条）──".format(len(A)))
    if not A:
        L.append("（无）")
    for item in A:
        L.append("• {}〔{}｜本页 {} 次 / 大纲 {} 次〕".format(item["key"], item["scope"], item["page_n"], item["outline_n"]))
        L.append("    {}".format(item["formal"]))
        L.append("    {}".format(item["def"]))
    L.append("")

    L.append("── B｜大纲本节命中、本页没提（{} 条）──".format(len(B)))
    L.append("（本课该讲但本页没出现的词——补卡时优先从这里挑）")
    if not B:
        L.append("（无）")
    for item in B:
        L.append("• {}〔大纲 {} 次〕".format(item["key"], item["outline_n"]))
        L.append("    {}".format(item["formal"]))
        L.append("    {}".format(item["def"]))
    L.append("")

    L.append("── C｜建议卡片草案（固定 3 槽位，每条 1–2 句）──")
    if not C:
        L.append("（本页与本节都没有命中，考虑整块省略概念卡并写明理由）")
    for d in C:
        L.append("{}　[{}]".format(d["slot"], d["key"]))
        L.append("    {}".format(d["text"]))
    L.append("")

    L.append("── D｜未收录概念（疑似 AI 词，词典里没有 → 提示补词典）──")
    if not D:
        L.append("（无）")
    for item in D:
        L.append("• {}（出现 {} 次）→ 建议补进 {}".format(item["term"], item["n"], DICT_FILE))
    L.append("")
    L.append("提示：C 段是草案，最终选哪 3 条由你拍板；D 段的词定好 1–2 句解释后，")
    L.append("      按 6 字段格式补进 {}，下次扫描即自动命中。".format(DICT_FILE))
    return "\n".join(L)


def main(argv=None):
    ap = argparse.ArgumentParser(description="扫描 AI 概念（本页正文 + 本课大纲那一节）")
    ap.add_argument("--page", required=True, help="学习页 .html 或 .md")
    ap.add_argument("--outline", required=True, help="课程大纲 .md")
    ap.add_argument("--section", default=None, help="大纲里的本节标题（片段匹配），不给则扫全文")
    ap.add_argument("--json", action="store_true", dest="as_json", help="输出机器可读 JSON")
    args = ap.parse_args(argv)

    page_path = Path(args.page)
    outline_path = Path(args.outline)
    for p in (page_path, outline_path):
        if not p.exists():
            print("找不到文件：{}".format(p), file=sys.stderr)
            return 2

    dict_path = Path(__file__).resolve().parent / DICT_FILE
    if not dict_path.exists():
        print("找不到词典：{}".format(dict_path), file=sys.stderr)
        return 2

    entries = load_dict(dict_path)
    page_text = read_text(page_path)
    outline_text = outline_path.read_text(encoding="utf-8", errors="ignore")

    section_title = None
    section_text = outline_text
    if args.section:
        section_title, section_text = split_section(outline_text, args.section)
        if section_title is None:
            section_text = outline_text

    page_hits = scan(entries, page_text)
    outline_hits = scan(entries, section_text)
    page_keys = {k for k, _c, _p in page_hits}
    outline_keys = {k for k, _c, _p in outline_hits}

    # A 段按「本页频次 → 首现位置」排；C 段草案同样以本页概念打底
    outline_count = {k: c for k, c, _p in outline_hits}
    ranked = rank_page_first(page_hits, outline_hits)

    A = []
    for key, c, _pos in sorted(page_hits, key=lambda h: (-h[1], h[2])):
        e = entries[key]
        A.append({
            "key": key, "formal": e.get("formal", key), "def": e.get("def", ""),
            "page_n": c, "outline_n": outline_count.get(key, 0),
            "scope": "两处都命中" if key in outline_keys else "仅本页",
        })

    B = []
    for key, _c, _p in outline_hits:
        if key not in page_keys:
            e = entries[key]
            B.append({
                "key": key, "formal": e.get("formal", key), "def": e.get("def", ""),
                "outline_n": dict((k, c) for k, c, _ in outline_hits)[key],
            })
    B.sort(key=lambda x: -x["outline_n"])

    C = build_drafts(ranked, entries)

    # D：疑似 AI 词但词典没收录（词典已能匹配到的，跳过）
    covered = " \n".join(
        " ".join(e.get("aliases", [])) for e in entries.values()
    )
    D = []
    for term in WATCHLIST:
        if build_pattern(term).search(covered):
            continue
        n = len(build_pattern(term).findall(page_text)) + len(build_pattern(term).findall(section_text))
        if n:
            D.append({"term": term, "n": n})
    D.sort(key=lambda x: -x["n"])

    result = {
        "page": str(page_path),
        "outline": str(outline_path),
        "section_requested": args.section,
        "section_title": section_title,
        "entries_in_dict": len(entries),
        "A": A, "B": B, "C": C, "D": D,
    }

    if args.as_json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(render(result))
    return 0


if __name__ == "__main__":
    sys.exit(main())
