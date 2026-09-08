# -*- coding: utf-8 -*-
"""比對新一批考點與《已考過考點清單》，列出疑似重複配對。
用法: python tools/dedupe.py tools/newbatch.txt
"""
import re, sys, itertools

STOP = set("之與及的在為者其得應該不無有以或並等各項第條款規定辦法機關資通安全")

def toks(s):
    s = re.sub(r"[（）()「」《》、，。,\s\-/]", "", s)
    return set(s[i:i+2] for i in range(len(s)-1)) - {t for t in
              (s[i:i+2] for i in range(len(s)-1)) if t[0] in STOP and t[1] in STOP}

def keyterms(s):
    """抓出高鑑別度詞：英文縮寫、數字、指定名詞"""
    t = set(re.findall(r"[A-Za-z][A-Za-z0-9.]{1,12}", s))
    t |= set(re.findall(r"[一二三四五六七八九十百千萬0-9]+(?:小時|日|年|次|級|項|款|條|元)", s))
    for kw in ["滲透測試","弱點掃描","健診","職責區隔","最小權限","業務僅知","監管鏈","雜湊",
               "數位簽章","數位信封","對稱","非對稱","金鑰","罰鍰","懲處","召集人","執行秘書",
               "適任性查核","調度支援","複委託","委外","雲端","責任劃分","訓練時數","證書",
               "組態","嚇阻","延遲","偵測","漏水","靜電","滅火","備份","RPO","RTO","MTPD","WRT",
               "風險避免","風險留存","風險分擔","殘餘風險","事件分級","通報","應變","復原","根除",
               "封鎖","準備","大陸廠牌","提報","審查會議","情資","稽核小組","迴避","改善報告",
               "資產","主要資產","支援資產","防護等級","普","中","高","閒置","日誌","時戳"]:
        if kw in s: t.add(kw)
    return t

def load_old(path):
    out=[]
    for ln in open(path,encoding="utf-8"):
        m=re.match(r"^-\s*(\S+)?\s*【第(\d+)單元】\s*\[(單選|複選)\]\s*(.+?)(（群.*)?$", ln.strip())
        if m: out.append((m.group(1) or "", m.group(2), m.group(3), m.group(4).strip()))
        else:
            m2=re.match(r"^-\s*(\d+)\s*\[([A-E])\]\s*(.+)$", ln.strip())
            if m2: out.append(("官方", "?", "單選", m2.group(3).strip()))
    return out

old = load_old("docs/已考過考點清單.md")
new = [l.split("|") for l in open(sys.argv[1],encoding="utf-8").read().strip().split("\n")]
print("黑名單考點 %d 筆 / 新批 %d 題\n" % (len(old), len(new)))

hits=0
for i,(grp,unit,typ,pt) in enumerate(new,1):
    tn, kn = toks(pt), keyterms(pt)
    scored=[]
    for oid,ou,ot,op in old:
        to, ko = toks(op), keyterms(op)
        j = len(tn&to)/max(1,len(tn|to))
        k = len(kn&ko)/max(1,len(kn|ko)) if (kn or ko) else 0
        s = j*0.5 + k*0.5 + (0.1 if ou==unit else 0)
        if s>0.18: scored.append((s,oid,op,sorted(kn&ko)))
    scored.sort(reverse=True)
    if scored:
        hits+=1
        print("[%d] 群%s 第%s單元 %s %s" % (i,grp,unit,typ,pt))
        for s,oid,op,shared in scored[:3]:
            print("     %.2f  ←  %s %s" % (s,oid,op))
            if shared: print("            共同關鍵詞: %s" % "、".join(shared[:8]))
        print()
print("=== 有疑似配對的新題: %d / %d ===" % (hits,len(new)))
