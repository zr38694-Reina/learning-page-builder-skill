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

同一批多页时（红线 8：一个概念只归一页），用 --used 串一个台账，逐页连用同一个文件：
    U=/tmp/本批概念台账.txt
    python3 scan_ai_concepts.py --page p1.html --outline 大纲.md --section "环节 3" --used "$U"
    python3 scan_ai_concepts.py --page p2.html --outline 大纲.md --section "环节 5" --used "$U"
--used 会：读入台账里已用的概念 → A/B 段标 ✗、C 段草案跳过 → 跑完把本页采用的概念追加回去。
--exclude "词A,词B" 可临时手动排除（词典 key 或中文词形都认）。
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


def resolve_keys(tokens, entries):
    """把「词典 key / 别名 / 展示名」解析成词典 key 集合。

    批次台账里存的是词典 key，但人（或手写的 --exclude）更可能写中文词形，
    两种都认；认不出来就原样收着，至少还能精确对上 key。
    """
    alias_map = {}
    for key, e in entries.items():
        alias_map[key.lower()] = key
        for a in e.get("aliases", []):
            alias_map[str(a).lower()] = key
        formal = str(e.get("formal", ""))
        if formal:
            alias_map[formal.lower()] = key
            base = re.sub(r"[（(][^）)]*[）)]", "", formal).strip()
            if base:
                alias_map.setdefault(base.lower(), key)

    out = set()
    for t in tokens:
        t = (t or "").strip()
        if not t:
            continue
        for cand in (t, re.sub(r"[（(][^）)]*[）)]", "", t).strip()):
            if cand and cand.lower() in alias_map:
                out.add(alias_map[cand.lower()])
                break
        else:
            out.add(t)
    return out


def read_ledger(path: Path):
    """读批次台账：支持 JSON 数组或「一行一个词」，# 开头的行忽略。"""
    if not path.exists():
        return []
    raw = path.read_text(encoding="utf-8").strip()
    if not raw:
        return []
    try:
        data = json.loads(raw)
        if isinstance(data, list):
            return [str(x) for x in data]
    except ValueError:
        pass
    return [ln.strip() for ln in raw.splitlines()
            if ln.strip() and not ln.strip().startswith("#")]


def related_of(key, entries):
    """同类别（category）的其它概念——第 ③ 层兜底的第一站：离线、有现成定义、可复现。"""
    cat = entries.get(key, {}).get("category")
    if not cat:
        return []
    return [(k, e) for k, e in entries.items() if e.get("category") == cat and k != key]


def build_drafts(ranked, entries, excluded, slots=3):
    """按槽位拼装卡片草案：① formal+def ② confusable+diff ③ verify。

    `excluded` = 本批其它页已经讲过的概念（同一批里一个词只在一页被解析），
    槽位选词时一律跳过——候选不够就少给一条，绝不跨页重复。
    """
    if not ranked:
        return []

    usable = [(k, m) for k, m in ranked if k not in excluded]
    if not usable:
        return []

    drafts = []
    top_key = usable[0][0]
    top = entries[top_key]

    drafts.append({
        "slot": "① 正式叫什么",
        "key": top_key,
        "text": "{}：{}".format(top.get("formal", top_key), top.get("def", "")),
    })

    # ② 易混区分：优先用「另一个概念」，没有就用首选概念自己的易混词
    second_key, second = None, None
    for key, _meta in usable[1:]:
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
    for key, _meta in usable:
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
    if result["excluded"]:
        L.append("本批已用（这些词本页不再解析，标记 ✗）：{}".format("、".join(result["excluded"])))
    L.append("")

    L.append("── A｜本页出现且词典命中（{} 条）──".format(len(A)))
    if not A:
        L.append("（无）")
    for item in A:
        L.append("• {}{}〔{}｜本页 {} 次 / 大纲 {} 次〕".format(
            "✗ " if item["excluded"] else "", item["key"], item["scope"], item["page_n"], item["outline_n"]))
        L.append("    {}".format(item["formal"]))
        L.append("    {}".format(item["def"]))
    L.append("")

    L.append("── B｜大纲本节命中、本页没提（{} 条）──".format(len(B)))
    L.append("（本课该讲但本页没出现的词——补卡时优先从这里挑）")
    if not B:
        L.append("（无）")
    for item in B:
        L.append("• {}{}〔大纲 {} 次〕".format("✗ " if item["excluded"] else "", item["key"], item["outline_n"]))
        L.append("    {}".format(item["formal"]))
        L.append("    {}".format(item["def"]))
    L.append("")

    L.append("── C｜建议卡片草案（固定 3 槽位，每条 1–2 句）──")
    if not C:
        L.append("（无）")
    for d in C:
        L.append("{}　[{}]".format(d["slot"], d["key"]))
        L.append("    {}".format(d["text"]))
    used_now = []
    for d in C:
        if d.get("key") and d["key"] not in used_now:   # ① 与 ③ 常是同一个概念
            used_now.append(d["key"])

    # 候选不足 → 给出第 ③ 层兜底候选（与本页主题同类的概念）
    if len(C) < 3 or len(used_now) < 2:
        if result["excluded"]:
            L.append("（本批其它页已占：{}）".format("、".join(result["excluded"])))
        if len(C) < 3:
            L.append("⚠️ 本页 + 本课凑不出 3 条槽位，卡建不起来 —— 必须走第 ③ 层。")
        else:
            L.append("ℹ️ 槽位齐了，但三个槽位只用到 1 个概念（①③ 是同一个词），卡偏薄。")
            L.append("   想更饱满，就从下面的同类里换一个更该讲的词当①（②仍是易混区分）。")
        if result["fallback"]:
            L.append("↳ 第 ③ 层兜底候选（与「{}」同属「{}」）：".format(
                result["fallback_basis"], result["fallback_category"]))
            for it in result["fallback"]:
                L.append("  • {}　{}".format(it["formal"], it["def"]))
            L.append("  用法：从这里挑**与本页主题强相关**的（沿用它的 def，别改写口径）；")
            L.append("        挑中的词照常填 `data-term`，并记进批内台账。")
        else:
            L.append("↳ 本页主题在词典里找不到同类词 → 按 `references/03` §1.6 走：")
            L.append("   ①联网搜「本页主题 + 相关 AI 概念」，选读者读完这页会自然想问的那个；")
            L.append("   ②把它的 1–2 句解释按 7 字段补进 {}，再引用（词典边用边长）；".format(DICT_FILE))
            L.append("   ③确与本页主题无关 → 整块省略概念卡，并在诊断清单写明理由。")
    L.append("")

    L.append("── D｜未收录概念（疑似 AI 词，词典里没有 → 提示补词典）──")
    if not D:
        L.append("（无）")
    for item in D:
        L.append("• {}（出现 {} 次）→ 建议补进 {}".format(item["term"], item["n"], DICT_FILE))
    L.append("")
    L.append("提示：C 段是草案，最终选哪 3 条由你拍板；D 段的词定好 1–2 句解释后，")
    L.append("      按 7 字段（6 字段 + category）补进 {}，下次扫描即自动命中。".format(DICT_FILE))
    return "\n".join(L)


def main(argv=None):
    ap = argparse.ArgumentParser(description="扫描 AI 概念（本页正文 + 本课大纲那一节）")
    ap.add_argument("--page", help="学习页 .html 或 .md")
    ap.add_argument("--outline", help="课程大纲 .md")
    ap.add_argument("--section", default=None, help="大纲里的本节标题（片段匹配），不给则扫全文")
    ap.add_argument("--exclude", default=None, help="本批其它页已讲过的概念，逗号分隔（词典 key 或中文词形都认）")
    ap.add_argument("--used", default=None, metavar="PATH",
                    help="批次台账：先读入其中已用概念并跳过，再把本页草案的概念追加进去（同一批逐页连用同一个文件）")
    ap.add_argument("--related", default=None, metavar="词或类别",
                    help="列出同类概念（第 ③ 层兜底用）。可传词典里的词，或类别名；不需要 --page/--outline")
    ap.add_argument("--json", action="store_true", dest="as_json", help="输出机器可读 JSON")
    args = ap.parse_args(argv)

    dict_path = Path(__file__).resolve().parent / DICT_FILE
    if not dict_path.exists():
        print("找不到词典：{}".format(dict_path), file=sys.stderr)
        return 2
    entries = load_dict(dict_path)

    # --related：单独一种用法，不需要 --page / --outline
    if args.related:
        raw = args.related.strip()
        cats = sorted({e.get("category") for e in entries.values() if e.get("category")})
        keys = [k for k in resolve_keys([raw], entries) if k in entries]
        if keys:
            for k in keys:
                print("「{}」的同类概念（{}）：".format(k, entries[k].get("category")))
                for ck, ce in related_of(k, entries):
                    print("• {}　{}".format(ce.get("formal", ck), ce.get("def", "")))
            return 0
        if raw in cats:
            print("类别「{}」下的全部概念：".format(raw))
            for ck, ce in entries.items():
                if ce.get("category") == raw:
                    print("• {}　{}".format(ce.get("formal", ck), ce.get("def", "")))
            return 0
        print("词典里没有「{}」。可用类别：{}".format(raw, "、".join(cats)), file=sys.stderr)
        print("也可以传一个词典里已有的词，看它同类的概念。", file=sys.stderr)
        return 2

    if not args.page or not args.outline:
        print("需要 --page 与 --outline（或用 --related 只查同类概念）", file=sys.stderr)
        return 2

    page_path = Path(args.page)
    outline_path = Path(args.outline)
    for p in (page_path, outline_path):
        if not p.exists():
            print("找不到文件：{}".format(p), file=sys.stderr)
            return 2

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

    # 批次去重：--exclude（手写） + --used（台账文件）合起来 = 本批其它页已讲过的概念
    excluded = set()
    if args.exclude:
        excluded |= resolve_keys(args.exclude.split(","), entries)
    ledger_path = Path(args.used) if args.used else None
    if ledger_path is not None:
        excluded |= resolve_keys(read_ledger(ledger_path), entries)

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
            "excluded": key in excluded,
        })

    B = []
    for key, _c, _p in outline_hits:
        if key not in page_keys:
            e = entries[key]
            B.append({
                "key": key, "formal": e.get("formal", key), "def": e.get("def", ""),
                "outline_n": outline_count.get(key, 0),
                "excluded": key in excluded,
            })
    B.sort(key=lambda x: (x["excluded"], -x["outline_n"]))

    C = build_drafts(ranked, entries, excluded)
    picks = []
    for d in C:
        if d.get("key") and d["key"] not in picks:   # ① 与 ③ 常常是同一个概念，去一次即可
            picks.append(d["key"])

    # 两种「不够」要分开看：槽位填不满（卡建不起来） / 槽位满了但只讲 1 个概念（卡偏薄）
    # → 前者必须兜底，后者给个提示即可。basis 取「本页最强命中」本身（哪怕已被别页占用）：
    # 「与本页主题相关」看的是本页，不是本批谁先抢到；占用的那条会在列表里按 excluded 过滤掉。
    fallback, basis, basis_cat = [], None, None
    if len(C) < 3 or len(picks) < 2:
        basis = ranked[0][0] if ranked else None
        if basis:
            basis_cat = entries[basis].get("category")
            fallback = [
                {"key": k, "formal": entries[k].get("formal", k), "def": entries[k].get("def", "")}
                for k, _e in related_of(basis, entries) if k not in excluded
            ][:8]

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
        "excluded": sorted(excluded),
        "used_file": str(ledger_path) if ledger_path else None,
        "fallback_basis": basis,
        "fallback_category": basis_cat,
        "fallback": fallback,
        "A": A, "B": B, "C": C, "D": D,
    }

    if args.as_json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(render(result))

    # 记账：把本页草案采用的概念追加进台账，供同一批的下一页 --used 读取
    if ledger_path is not None:
        known = read_ledger(ledger_path)
        merged = known + [k for k in picks if k not in known]
        ledger_path.parent.mkdir(parents=True, exist_ok=True)
        ledger_path.write_text(
            "# 本批已讲过的概念（scan_ai_concepts.py --used 维护，一行一个）\n"
            + "\n".join(merged) + "\n",
            encoding="utf-8",
        )
        if not args.as_json:
            print("\n已记账 → {}（累计 {} 条：{}）".format(ledger_path, len(merged), "、".join(merged)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
