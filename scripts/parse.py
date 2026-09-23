# -*- coding: utf-8 -*-
"""
Parse 莲斋医意立斋案疏精简版.txt into structured JSON.
Structure:
  - 门类 header lines (e.g. 元气亏损内外伤外感等症) and 补遗 marker
  - Cases 【案N】 ... with 原文, footnotes (①②...), inline 〔校按：...〕, and 崧疏曰：...
"""
import json
import re
import sys

SRC = r"C:\Users\Administrator\Downloads\莲斋医意立斋案疏精简版.txt"
OUT_DIR = r"C:\Users\Administrator\WorkBuddy\2026-09-23-07-41-27\lianzhai-yianshu"
OUT = OUT_DIR + r"\data\cases.json"

HEADER_RE = re.compile(r"^[^【崧【].{2,30}等?(症|证)\s*$")
CASE_RE = re.compile(r"^【案(\d+)】\s*")
FOOTNOTE_RE = re.compile(r"^([①②③④⑤⑥⑦⑧⑨⑩])\s*[　 ]?")
JIAOAN_RE = re.compile(r"〔校按：(.+?)〕")
FORMULA_RE = re.compile(r"[\u4e00-\u9fa5]{1,10}?(?:汤|丸|散|饮子|饮|膏|丹|煎)")
# formulas often abbreviated like 六君(子)、补中(益气)、八味(丸)、六味(地黄丸)
BAD_FORMULA = set("喜冷饮 喜热饮 冷饮 热饮 石膏 滚痰丸 芪附汤 参附等汤 芪附等汤 饮食 茶饮 前汤 前丸 前散 前药 因饮 善饮 日饮 每饮 节饮 过饮 常饮 体肥善饮 素善饮".split())


def clean_formula(name: str) -> bool:
    if len(name) < 2 or name in BAD_FORMULA or "前" in name[:3]:
        return False
    for bad in ("之", "以", "其", "此", "故", "或", "而", "不", "为", "与", "者", "也", "又", "自", "可"):
        # keep formulas that contain these chars only in known names; crude filter: reject leading 之/以/其/此/或/而/与
        pass
    if name[0] in "之以其此故而或不与又自可者亦盖且夫然虽若云斯": 
        return False
    if name.startswith(("余", "立斋", "东垣", "丹溪", "仲景", "钱仲阳")):
        return False
    return True


def main():
    with open(SRC, encoding="utf-8-sig") as f:
        raw_lines = [ln.rstrip("\r\n") for ln in f]

    sections = []  # list of {part, category, cases: [...]}
    cur_part = "正编"
    cur_cat = None
    cur_case = None
    buf_role = None  # 'original' or 'shu'
    footnotes = []

    def flush_case():
        nonlocal cur_case, footnotes
        if cur_case is None:
            return
        cur_case["footnotes"] = footnotes
        footnotes = []
        cur_cat["cases"].append(cur_case)
        cur_case = None

    def flush_cat():
        nonlocal cur_cat
        flush_case()
        if cur_cat is not None:
            sections.append(cur_cat)
        cur_cat = None

    for ln in raw_lines:
        line = ln.strip()
        if not line:
            continue
        # 补遗 marker
        if line == "补遗":
            flush_cat()
            cur_part = "补遗"
            continue
        # category header (but not a case line)
        if HEADER_RE.match(line) and not CASE_RE.match(line):
            flush_cat()
            cur_cat = {"part": cur_part, "category": line, "cases": []}
            continue
        # case start
        m = CASE_RE.match(line)
        if m:
            flush_case()
            cur_case = {
                "no": int(m.group(1)),
                "original": line[m.end():].strip(),
                "shu": "",
                "jiaoju": [],
            }
            buf_role = "original"
            continue
        # footnote line
        fm = FOOTNOTE_RE.match(line)
        if fm and cur_case is not None:
            # remove marker char, keep text
            footnotes.append({"mark": fm.group(1), "text": line[fm.end():].strip()})
            continue
        # 崧疏 start
        if line.startswith("崧疏曰：") or line.startswith("崧疏曰:"):
            buf_role = "shu"
            cur_case["shu"] += line.split("曰：", 1)[-1].strip() if "曰：" in line else line.split("曰:", 1)[-1].strip()
            continue
        # continuation lines
        if cur_case is None:
            # stray text outside cases (e.g. header area)
            continue
        if buf_role == "shu":
            cur_case["shu"] += line
        else:
            cur_case["original"] += line
    flush_cat()

    # post-process each case
    all_cases = []
    for sec in sections:
        for c in sec["cases"]:
            orig = c["original"]
            shu = c["shu"]
            # extract 校按 from original & shu
            ja = JIAOAN_RE.findall(orig) + JIAOAN_RE.findall(shu)
            c["jiaoju"] = ja
            # clean original: keep inline 〔校按...〕 for readability
            # patient: text before first ，。
            pm = re.split(r"[，。]", orig, maxsplit=1)
            c["patient"] = pm[0][:60] if pm else ""
            # outcome
            outcome = ""
            for w in ("而痊", "而愈", "痊愈", "悉愈", "而安", "而苏", "得愈", "渐愈", "顿安", "而殁", "而殒", "不治", "不起", "后果然"):
                if w in orig:
                    outcome = w
                    break
            c["outcome"] = outcome
            # formulas from original
            formulas = []
            NOISE = "用服以和佐将先后朝夕晚午与遂又复乃仍但合煎送并兼投进令宜当欲可预"
            for fm_ in FORMULA_RE.finditer(orig):
                name = fm_.group(0)
                while len(name) > 2 and name[0] in NOISE:
                    name = name[1:]
                # 加减X / 加味X / 加X → prefer the base formula if it is known
                changed = True
                while changed and len(name) > 3:
                    changed = False
                    for pfx in ("加减", "加味"):
                        if name.startswith(pfx):
                            name = name[len(pfx):]
                            changed = True
                    if name.startswith("加"):
                        name = name[1:]
                        changed = True
                if len(name) >= 2 and clean_formula(name) and name not in formulas:
                    formulas.append(name)
            # normalize common abbreviations
            norm = {
                "补中益气汤": "补中益气汤", "补中益气": "补中益气汤",
                "六君子汤": "六君子汤", "六君子": "六君子汤", "六君": "六君子汤",
                "六味地黄丸": "六味地黄丸", "六味丸": "六味地黄丸", "地黄丸": "六味地黄丸",
                "八味丸": "八味丸", "加减八味丸": "八味丸",
                "十全大补汤": "十全大补汤",
                "归脾汤": "归脾汤", "加味归脾汤": "归脾汤",
                "逍遥散": "逍遥散", "加味逍遥散": "逍遥散",
                "八珍汤": "八珍汤", "四君子汤": "四君子汤", "四物汤": "四物汤",
                "小柴胡汤": "小柴胡汤", "左金丸": "左金丸",
                "附子理中汤": "附子理中汤", "升阳益胃汤": "升阳益胃汤",
                "四神丸": "四神丸", "二神丸": "二神丸", "五味子散": "五味子散",
                "花蕊石散": "花蕊石散", "独参汤": "独参汤",
                "滋肾丸": "滋肾丸", "还少丹": "还少丹",
                "藿香正气散": "藿香正气散", "人参养胃汤": "人参养胃汤",
                "香砂六君子汤": "香砂六君子汤", "升阳除湿防风汤": "升阳除湿防风汤",
                "秦艽升麻汤": "秦艽升麻汤", "三生饮": "三生饮",
                "地黄饮子": "地黄饮子", "竹叶黄芪汤": "竹叶黄芪汤",
                "黄芩清肺饮": "黄芩清肺饮", "参苏饮": "参苏饮",
                "愈风丹": "愈风丹", "愈风汤": "愈风汤",
            }
            normed = []
            for name in formulas:
                n = norm.get(name, name)
                if n not in normed:
                    normed.append(n)
            c["formulas"] = normed[:12]
            c["category"] = sec["category"]
            c["part"] = sec["part"]
            all_cases.append(c)

    # sort by case no
    all_cases.sort(key=lambda x: x["no"])
    # sanity checks
    assert len(all_cases) == 257, f"expected 257 cases, got {len(all_cases)}"
    assert [c["no"] for c in all_cases] == list(range(1, 258)), "case numbers not continuous 1..257"

    # category summary
    cat_summary = []
    for sec in sections:
        cat_summary.append({
            "part": sec["part"],
            "category": sec["category"],
            "range": f"{sec['cases'][0]['no']}-{sec['cases'][-1]['no']}",
            "count": len(sec["cases"]),
        })

    data = {
        "title": "莲斋医意立斋案疏（精简版）医案数据库",
        "book": "《莲斋医意立斋案疏》",
        "author_case": "明·薛己（立斋）医案",
        "author_shu": "清·叶崧 案疏",
        "total_cases": len(all_cases),
        "categories": cat_summary,
        "cases": all_cases,
    }
    import os
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    print(f"OK: {len(all_cases)} cases, {len(sections)} sections")
    for s in cat_summary:
        print(f"  [{s['part']}] {s['category']}  案{s['range']}  共{s['count']}案")


if __name__ == "__main__":
    main()
