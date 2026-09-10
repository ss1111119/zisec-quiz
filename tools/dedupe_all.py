# -*- coding: utf-8 -*-
"""全庫交叉去重：掃描 banks/*.md，以「法條條項款」與「具體事實」為單位分群。

與 tools/dedupe.py 的差別：
  dedupe.py     新批 vs 已考過考點清單，單向比對，靠文字相似度。
  dedupe_all.py 全庫交叉比對，靠結構化訊號（條項款、數字＋對象、關鍵詞組）。

用法: python tools/dedupe_all.py [--min 2]
輸出: 依訊號分群，列出出現 >= min 次的考點叢集。
"""
import re, sys, io, os, json, collections

BANKS = "banks"

LAWS = [
    ("施行細則", "施行細則"),
    ("資通安全管理法施行細則", "施行細則"),
    ("通報應變及演練辦法", "通報辦法"),
    ("資通安全事件通報應變及演練辦法", "通報辦法"),
    ("稽核辦法", "稽核辦法"),
    ("資通安全維護計畫實施情形稽核辦法", "稽核辦法"),
    ("分級辦法", "分級辦法"),
    ("資通安全責任等級分級辦法", "分級辦法"),
    ("資通安全情資分享辦法", "情資分享辦法"),
    ("情資分享辦法", "情資分享辦法"),
    ("審查辦法", "審查辦法"),
    ("危害國家資通安全產品審查辦法", "審查辦法"),
    ("作業辦法", "作業辦法"),
    ("公務機關所屬人員辦理資通安全事項作業辦法", "作業辦法"),
    ("資通安全管理法", "資安法"),
]

CN = {"一":1,"二":2,"三":3,"四":4,"五":5,"六":6,"七":7,"八":8,"九":9,"十":10,
      "十一":11,"十二":12,"十三":13,"十四":14,"十五":15,"十六":16,"十七":17,
      "十八":18,"十九":19,"二十":20,"二十一":21,"二十二":22,"二十三":23,
      "二十四":24,"二十五":25,"二十九":29,"三十":30,"三十一":31}


def num(s):
    s = s.strip()
    if s.isdigit():
        return int(s)
    return CN.get(s, s)


def parse_bank(path):
    t = io.open(path, encoding="utf-8").read()
    t = re.split(r"出題後檢查表", t)[0]
    out = []
    for blk in re.split(r"\n---\n", t):
        m = re.match(r"\s*第 (\d+) 題", blk)
        if not m:
            continue
        no = int(m.group(1))
        unit = (re.search(r"【單元：第 (\d+) 單元】", blk) or [None, "?"])[1] \
            if re.search(r"【單元：第 (\d+) 單元】", blk) else "?"
        unit = re.search(r"【單元：第 (\d+) 單元】", blk)
        unit = unit.group(1) if unit else "?"
        typ = re.search(r"【題型：(\S+?)】", blk)
        typ = typ.group(1) if typ else "?"
        pt = re.search(r"【核心考點：([^】]+)】", blk)
        pt = pt.group(1).strip() if pt else ""
        ans = re.search(r"答案\s*[：:]\s*([^\n]*)", blk)
        ans = "".join(re.findall(r"[A-H]", ans.group(1))) if ans else ""
        out.append(dict(no=no, unit=unit, typ=typ, point=pt, ans=ans, body=blk))
    return out


def law_refs(text):
    """抽出 (法規, 條, 項, 款) 之引用。"""
    refs = set()
    # 注意：長名稱須排在短名稱之前，且「資通安全管理法」後方須排除「施行細則」，
    # 否則「資通安全管理法施行細則第 7 條」會被誤判為「資安法第 7 條」
    # （「施行細則」四字剛好落在 0~6 字的容錯範圍內）。
    pat = re.compile(
        r"(資通安全管理法施行細則|施行細則"
        r"|資通安全事件通報應變及演練辦法|通報應變及演練辦法"
        r"|資通安全維護計畫實施情形稽核辦法|稽核辦法"
        r"|資通安全責任等級分級辦法|分級辦法"
        r"|資通安全情資分享辦法|情資分享辦法"
        r"|危害國家資通安全產品審查辦法|審查辦法"
        r"|公務機關所屬人員辦理資通安全事項作業辦法|作業辦法"
        r"|資通安全管理法(?!施行細則)|本法)"
        r"[^。\n]{0,6}?第\s*([一二三四五六七八九十\d]+)\s*條"
        r"(?:第\s*([一二三四五六七八九十\d]+)\s*項)?"
        r"(?:第\s*([一二三四五六七八九十\d]+)\s*款)?")
    for m in pat.finditer(text):
        law = m.group(1)
        for a, b in LAWS:
            if law == a:
                law = b
                break
        if law == "本法":
            law = "資安法"
        refs.add((law, num(m.group(2)), num(m.group(3)) if m.group(3) else None,
                  num(m.group(4)) if m.group(4) else None))
    return refs


# 具體事實：數字 + 適用對象／項目
FACTS = [
    (r"日誌.{0,20}(六個月|6 個月)", "日誌留存6個月"),
    (r"(五次|5 次).{0,20}(十五分鐘|15 分鐘)", "帳戶鎖定5次15分"),
    (r"前三次", "密碼不可與前3次相同"),
    (r"(一千萬|1,000 萬|1000 萬)", "第三方檢測門檻1000萬"),
    (r"十二小時以上|12 小時以上", "專職人員每年12小時"),
    (r"每人每年接受三小時|每年 3 小時以上之.{0,6}通識", "一般使用者每年3小時通識"),
    (r"每 ?2 ?年.{0,10}(三小時|3 小時)|每二年接受三小時", "資訊人員每2年3小時"),
    (r"配置四人|四人以上", "A級專職4人"),
    (r"配置二人|二人以上", "B級專職2人"),
    (r"配置一人|一人以上", "C級專職1人"),
    (r"(七十二小時|72 小時)", "損害控制72小時"),
    (r"(三十六小時|36 小時)", "重大損害控制36小時"),
    (r"知悉.{0,12}(一小時內|1 小時內)", "通報1小時"),
    (r"(八小時內|8 小時內)", "審核8小時"),
    (r"社交工程演練.{0,12}(每半年|半年)", "社交工程每半年"),
    (r"通報及應變演練.{0,12}每年|每年辦理一次資通安全事件通報", "通報應變演練每年"),
    (r"(三十萬|30 萬).{0,12}(一千萬|1,000 萬)", "罰則30萬-1000萬"),
    (r"(十萬|10 萬).{0,12}(五百萬|500 萬)", "罰則10萬-500萬"),
    (r"(十萬|10 萬).{0,12}(一百萬|100 萬)", "罰則10萬-100萬"),
    (r"每三年", "責任等級每3年"),
    (r"滲透測試.{0,20}(每二年|每 2 年)", "B級滲透每2年"),
    (r"弱點掃描.{0,20}每年辦理二次|每年辦理二次", "A級弱掃每年2次"),
    (r"二年內.{0,20}導入|導入.{0,20}二年內", "ISMS導入2年內"),
    (r"三年內.{0,20}驗證|驗證.{0,20}三年內", "ISMS驗證3年內"),
    (r"十五日內.{0,12}(一次為限)|十五日", "申辯15日一次為限"),
    (r"(七日|七天).{0,20}延長.{0,10}(七日|一次)", "調度7日+7日"),
    (r"源碼掃描", "源碼掃描屬開發階段高級"),
    (r"多因子鑑別|多重認證", "多因子鑑別屬高級"),
    (r"異地備份", "異地備份屬高級"),
    (r"輸入.{0,6}合法性檢查.{0,12}伺服器端", "輸入驗證伺服器端屬普級"),
    (r"設計階段.{0,20}無要求|普.{0,6}無要求.{0,20}設計階段", "設計階段普級無要求"),
    (r"時戳.{0,20}(UTC|世界協調時間)", "時戳UTC三級共通"),
    (r"雜湊.{0,20}完整性確保機制", "雜湊完整性屬中級"),
]


def facts_of(text):
    got = set()
    for pat, name in FACTS:
        if re.search(pat, text):
            got.add(name)
    return got


def main():
    minn = 2
    if "--min" in sys.argv:
        minn = int(sys.argv[sys.argv.index("--min") + 1])

    files = sorted([f for f in os.listdir(BANKS) if f.endswith(".md")],
                   key=lambda x: int(re.match(r"v(\d+)", x).group(1)))
    qs = []
    for f in files:
        v = re.match(r"(v\d+)", f).group(1)
        for q in parse_bank(os.path.join(BANKS, f)):
            q["bank"] = v
            q["id"] = f"{v}-{q['no']}"
            q["refs"] = law_refs(q["body"])
            q["facts"] = facts_of(q["body"])
            qs.append(q)

    print("題庫 %d 份 / 題目 %d 題\n" % (len(files), len(qs)))

    # 依條項款分群
    by_ref = collections.defaultdict(list)
    for q in qs:
        for r in q["refs"]:
            by_ref[r].append(q["id"])
    print("=" * 68)
    print("一、同一法條「條項款」重覆出題（門檻 >= %d）" % minn)
    print("=" * 68)
    rows = [(k, v) for k, v in by_ref.items() if len(set(v)) >= minn]
    rows.sort(key=lambda x: -len(set(x[1])))
    for (law, c, p, k), ids in rows:
        loc = f"{law} 第{c}條"
        if p: loc += f"第{p}項"
        if k: loc += f"第{k}款"
        print(f"  [{len(set(ids))}] {loc:28s} {'、'.join(sorted(set(ids)))}")

    # 依具體事實分群
    by_fact = collections.defaultdict(list)
    for q in qs:
        for f in q["facts"]:
            by_fact[f].append(q["id"])
    print()
    print("=" * 68)
    print("二、同一「具體事實」重覆出題（門檻 >= %d）" % minn)
    print("=" * 68)
    rows = [(k, v) for k, v in by_fact.items() if len(set(v)) >= minn]
    rows.sort(key=lambda x: -len(set(x[1])))
    for name, ids in rows:
        print(f"  [{len(set(ids))}] {name:26s} {'、'.join(sorted(set(ids)))}")

    print()
    print("=" * 68)
    print("三、統計")
    print("=" * 68)
    print("  有法條引用之題目：%d" % sum(1 for q in qs if q["refs"]))
    print("  命中具體事實之題目：%d" % sum(1 for q in qs if q["facts"]))
    print("  完全未命中任何訊號（多為概念題）：%d"
          % sum(1 for q in qs if not q["refs"] and not q["facts"]))


if __name__ == "__main__":
    main()
