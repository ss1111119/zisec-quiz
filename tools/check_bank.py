# -*- coding: utf-8 -*-
"""
題庫檢查器：重現 index.html 的 parseQuiz 邏輯，驗證 banks/*.md 是否會被正確解析。
選項間距改版時每批做完必跑。

用法：
    python tools/check_bank.py                  # 檢查全部題庫
    python tools/check_bank.py v3-001-050.md    # 只檢查一份
    python tools/check_bank.py v3               # 前綴比對亦可

檢查項目：
    題數是否與 index.json 宣告相符、題號是否連續、有無幽靈題、
    單複選題數、答案是否都在選項內、選項代號是否重複或未依序、
    解析引用的代號是否存在、教材依據是否為空、是否殘留「應選 N 項」提示、
    正解字母分布與最長連續同答案、複選答案組合是否過度集中。

重要：截斷標記有兩個，index.html 第 222 行為
    text.split(/出題後檢查表|【本次出題統計】/)[0]
v2～v10 與 official 用「出題後檢查表」，v11 之後用「【本次出題統計】」，兩者都有效。
（曾因只實作其中一個而誤判 v2 有 26 個幽靈題，見 docs/交接筆記.md）
"""
import re
import sys
import json
import glob
import os
import io
import collections

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BANKS = os.path.join(ROOT, "banks")
CUT_RE = re.compile(r"出題後檢查表|【本次出題統計】")
Q_RE = re.compile(r"第\s*(\d+)\s*題")


def load_index():
    with open(os.path.join(BANKS, "index.json"), encoding="utf-8") as f:
        d = json.load(f)
    seq = d if isinstance(d, list) else d.get("banks", [])
    return {x["file"]: x for x in seq}


def check(path, declared):
    """回傳 (題數, 問題清單, 單選答案序列, 複選答案序列)"""
    errs = []
    raw = open(path, encoding="utf-8").read()

    m = CUT_RE.search(raw)
    body = raw[:m.start()] if m else raw
    if not m:
        errs.append("檔尾無截斷標記（出題後檢查表 / 【本次出題統計】）")

    parts = Q_RE.split(body)
    head = parts[0]
    if Q_RE.search(head):
        errs.append("檔頭出現「第 N 題」，會生出幽靈題")

    items = [(int(parts[i]), parts[i + 1]) for i in range(1, len(parts), 2)]
    nums = [n for n, _ in items]

    if declared is not None and len(items) != declared:
        errs.append("題數 %d 與 index.json 宣告之 %d 不符" % (len(items), declared))
    if nums != list(range(1, len(items) + 1)):
        errs.append("題號不連續：%s" % nums)

    singles, multis = [], []
    for n, chunk in items:
        am = re.search(r"^答案：(.+)$", chunk, re.M)
        if not am:
            errs.append("第%d題 無答案列" % n)
            continue
        ans = [a.strip() for a in am.group(1).replace("，", ",").split(",") if a.strip()]

        # parseQuiz 只在「答案：」之前的片段找選項（seg = body.slice(0, ansM.index)），
        # 不可掃整段，否則解析中行首的「(B) ...」會被誤認為選項。
        seg = chunk[:am.start()]
        opts = re.findall(r"^\((?P<L>[A-G])\)\s*(.+)$", seg, re.M)
        letters = [l for l, _ in opts]

        tm = re.search(r"【題型：(\S+?)】", chunk)
        t = tm.group(1) if tm else "?"

        if len(letters) < 4:
            errs.append("第%d題 選項僅 %d 個：%s" % (n, len(letters), letters))
        if len(set(letters)) != len(letters):
            errs.append("第%d題 選項代號重複：%s" % (n, letters))
        if letters != sorted(letters):
            errs.append("第%d題 選項代號未依序：%s" % (n, letters))
        for a in ans:
            if a not in letters:
                errs.append("第%d題 答案 %s 不在選項內 %s" % (n, a, letters))
        if t == "單選" and len(ans) != 1:
            errs.append("第%d題 標單選卻有 %d 個答案" % (n, len(ans)))
        if t == "複選" and len(ans) < 2:
            errs.append("第%d題 標複選卻只有 %d 個答案" % (n, len(ans)))

        # 四個選項全對＝送分，改版時要增列第五個選項
        if len(letters) == len(ans) and len(ans) >= 3:
            errs.append("第%d題 %d 個選項全為答案，形同送分" % (n, len(ans)))

        for tag, cnt in (("答案：", 1), ("解析：", 1), ("教材依據：", 1)):
            c = chunk.count(tag)
            if c != cnt:
                errs.append("第%d題 「%s」出現 %d 次" % (n, tag, c))

        bm = re.search(r"教材依據：\s*\n(.+)", chunk)
        if not bm or not bm.group(1).strip():
            errs.append("第%d題 教材依據為空或缺漏" % n)

        for ref in sorted(set(re.findall(r"\(([A-G])\)", chunk))):
            if ref not in letters:
                errs.append("第%d題 解析引用 (%s) 但選項無此代號 %s" % (n, ref, letters))

        if "應選" in chunk:
            errs.append("第%d題 仍殘留數量提示「應選」" % n)

        (multis if len(ans) > 1 else singles).append((n, "".join(ans)))

    # 正解分布
    dist = collections.Counter(a for _, a in singles)
    run, prev, longest, where = 0, None, 0, None
    for n, a in singles:
        run = run + 1 if a == prev else 1
        prev = a
        if run > longest:
            longest, where = run, n
    if longest >= 4:
        errs.append("單選連續 %d 題同為 (%s)，至第%d題" % (longest, prev, where))
    if singles:
        top, cnt = dist.most_common(1)[0]
        if cnt > len(singles) * 0.4:
            errs.append("單選答案偏 (%s)：%d/%d" % (top, cnt, len(singles)))

    mdist = collections.Counter(a for _, a in multis)
    if multis:
        top, cnt = mdist.most_common(1)[0]
        if cnt > len(multis) * 0.5:
            errs.append("複選答案組合偏 %s：%d/%d，應打散" % (top, cnt, len(multis)))

    return len(items), errs, dist, mdist


def main():
    idx = load_index()
    targets = sorted(glob.glob(os.path.join(BANKS, "*.md")))
    if len(sys.argv) > 1:
        key = sys.argv[1]
        targets = [p for p in targets if os.path.basename(p).startswith(key.replace(".md", ""))]
        if not targets:
            print("找不到符合 %r 的題庫" % key)
            return 1

    total_err = 0
    for path in targets:
        base = os.path.basename(path)
        declared = idx.get(base, {}).get("count")
        n, errs, dist, mdist = check(path, declared)
        head = "%-24s 解析 %3d 題" % (base, n)
        if declared is not None:
            head += "（宣告 %d）" % declared
        print(head)
        print("   單選分布 %s｜複選組合 %s"
              % (dict(sorted(dist.items())), dict(sorted(mdist.items()))))
        if errs:
            total_err += len(errs)
            for e in errs:
                print("   !! " + e)
        else:
            print("   -- 通過")
        print()

    print("=== 合計問題 %d 項 ===" % total_err)
    return 1 if total_err else 0


if __name__ == "__main__":
    sys.exit(main())
