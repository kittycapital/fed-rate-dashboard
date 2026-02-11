#!/usr/bin/env python3
"""
Fed Rate Dashboard v3.4
========================
핵심 개선: Polymarket 3월 이벤트 찾기
  - slug "fed-decision-in-march" → 2025년 (종료) 반환 문제
  - 실제 2026년 슬러그: "fed-decision-in-march-885"
  
전략:
  1. /events 검색 (title + closed=false)
  2. /markets 검색 (question 포함 "March 2026")  
  3. /events 검색 (tag=fed-rates)
  4. slug 직접 + 접미사 패턴
"""

import json, requests, re, os
from datetime import datetime

TIMEOUT = 15
HDR = {"User-Agent": "FedRateDashboard/3.4", "Accept": "application/json"}
NOW = datetime.utcnow()
YEAR = NOW.year
BASE = "https://gamma-api.polymarket.com"

MONTHS_EN = ["january","february","march","april","may","june",
             "july","august","september","october","november","december"]
MO_KO = {m: f"{i+1}월" for i, m in enumerate(MONTHS_EN)}
MO_NUM_KO = {i+1: f"{i+1}월" for i in range(12)}
FOMC_MONTHS = {1:"january",3:"march",4:"april",6:"june",
               7:"july",9:"september",10:"october",12:"december"}

# ═══════════════════════ 번역 ═══════════════════════
def tr_title(t):
    t = re.sub(r"(?i)will no rate cuts? happen in (\d{4})\??", lambda m: f"{m[1]}년 금리 인하 0회 여부", t)
    t = re.sub(r"(?i)will (\d+) or more rate cuts? happen in (\d{4})\??", lambda m: f"{m[2]}년 {m[1]}회 이상 금리 인하 여부", t)
    t = re.sub(r"(?i)will fewer than (\d+) rate cuts? happen in (\d{4})\??", lambda m: f"{m[2]}년 {m[1]}회 미만 금리 인하 여부", t)
    t = re.sub(r"(?i)will at least (\d+) rate cuts? happen in (\d{4})\??", lambda m: f"{m[2]}년 최소 {m[1]}회 금리 인하 여부", t)
    t = re.sub(r"(?i)will (\d+) rate cuts? happen in (\d{4})\??", lambda m: f"{m[2]}년 {m[1]}회 금리 인하 여부", t)
    t = re.sub(r"(?i)how many (?:fed )?rate cuts? (?:in )?(\d{4})\??", lambda m: f"{m[1]}년 Fed 금리 인하 횟수", t)
    t = re.sub(r"(?i)number of (?:fed )?rate cuts?.*?(\d{4})", lambda m: f"{m[1]}년 금리 인하 횟수", t)
    for en, ko in MO_KO.items():
        t = re.sub(rf"(?i)Fed [Dd]ecision in {en}\??", f"{ko} FOMC 금리 결정", t)
    t = re.sub(r"(?i)what will the fed (?:funds )?rate be at the end of (\d{4})\??", lambda m: f"{m[1]}년 말 Fed 기준금리 전망", t)
    return t

def tr_outcome(o):
    o = o.strip()
    static = {"Yes":"예","No":"아니오","No change":"동결",
              "25 bps decrease":"25bp 인하","25 bps cut":"25bp 인하",
              "50 bps decrease":"50bp 인하","50 bps cut":"50bp 인하",
              "75 bps decrease":"75bp 인하","100 bps decrease":"100bp 인하",
              "25 bps increase":"25bp 인상","50 bps increase":"50bp 인상",
              "Increase":"인상","Decrease":"인하"}
    if o in static: return static[o]
    r = re.match(r"(\d+)\s*bps?\s*(decrease|cut)", o, re.I)
    if r: return f"{r[1]}bp 인하"
    r = re.match(r"(\d+)\s*bps?\s*(increase|hike)", o, re.I)
    if r: return f"{r[1]}bp 인상"
    r = re.match(r"(\d+\.\d+)\s*[-–]\s*(\d+\.\d+)", o)
    if r: return f"{r[1]}~{r[2]}%"
    return o

# ═══════════════ FOMC 캘린더 ═══════════════
FOMC_DATES = {
    2025: [(1,28,29),(3,18,19),(5,6,7),(6,17,18),(7,29,30),(9,16,17),(10,28,29),(12,9,10)],
    2026: [(1,27,28),(3,17,18),(4,28,29),(6,16,17),(7,28,29),(9,15,16),(10,27,28),(12,8,9)],
    2027: [(1,26,27),(3,16,17),(4,27,28),(6,15,16),(7,27,28),(9,21,22),(10,26,27),(12,14,15)],
}

def build_fomc_calendar():
    print("[0] FOMC 캘린더 ...")
    cal, today = [], NOW.strftime("%Y-%m-%d")
    for mo, d1, d2 in FOMC_DATES.get(YEAR, []):
        ds, de = f"{YEAR}-{mo:02d}-{d1:02d}", f"{YEAR}-{mo:02d}-{d2:02d}"
        cal.append({"date":ds,"end_date":de,"month":mo,"year":YEAR,
                     "label":MO_NUM_KO[mo],"is_past":de<today})
    print(f"  ✅ {len(cal)}개 미팅")
    for c in cal:
        print(f"    {c['label']:4s} {c['date']}~{c['end_date'][-2:]} ({'완료' if c['is_past'] else '예정'})")
    return cal

# ═══════════════ SOFR ═══════════════
def fetch_sofr():
    print("[1] NY Fed SOFR ...")
    try:
        r = requests.get("https://markets.newyorkfed.org/api/rates/secured/sofr/last/90.json",
                         headers=HDR, timeout=TIMEOUT)
        r.raise_for_status()
        d = [{"date":x["effectiveDate"],"rate":float(x["percentRate"])}
             for x in r.json().get("refRates",[]) if x.get("percentRate")]
        d.sort(key=lambda x:x["date"])
        print(f"  ✅ {len(d)}일"); return d
    except Exception as e:
        print(f"  ❌ {e}"); return []

# ═══════════════ FRED ═══════════════
def fetch_fred_target_rate():
    api_key = os.environ.get("FRED_API_KEY", "")
    if not api_key:
        print("[2] FRED ⏭️ (API키 없음)"); return None
    print("[2] FRED 목표금리 ...")
    result = {}
    for series, label in [("DFEDTARU","upper"), ("DFEDTARL","lower")]:
        try:
            r = requests.get(
                f"https://api.stlouisfed.org/fred/series/observations"
                f"?series_id={series}&api_key={api_key}&file_type=json"
                f"&sort_order=desc&limit=5", timeout=TIMEOUT)
            r.raise_for_status()
            for o in r.json().get("observations", []):
                if o.get("value",".") != ".":
                    result[label] = float(o["value"])
                    result[f"{label}_date"] = o["date"]
                    break
        except Exception as e:
            print(f"  ⚠️ {series}: {e}")
    if "upper" in result and "lower" in result:
        print(f"  ✅ {result['lower']:.2f}~{result['upper']:.2f}%")
    return result if result else None

# ═══════════════ Polymarket ═══════════════
def api_get(url, params=None):
    try:
        r = requests.get(url, params=params, headers=HDR, timeout=TIMEOUT)
        if r.status_code == 200: return r.json()
        return None
    except: return None

def get_event_year(ev):
    end = ev.get("endDate","")
    if not end: return YEAR
    try: return datetime.fromisoformat(end.replace("Z","")).year
    except: return YEAR

def parse_markets(ev):
    ms = []
    for m in ev.get("markets", []):
        try: oc = json.loads(m.get("outcomes","[]"))
        except: oc = []
        try: pr = json.loads(m.get("outcomePrices","[]"))
        except: pr = []
        ms.append({
            "question_en": m.get("question",""),
            "question_ko": tr_title(m.get("question","")),
            "groupItemTitle_en": m.get("groupItemTitle",""),
            "outcomes_en": oc,
            "outcomes_ko": [tr_outcome(o) for o in oc],
            "prices": [float(p) for p in pr] if pr else [],
            "volume": float(m.get("volume",0) or 0),
        })
    return ms

def fetch_polymarket():
    print("[3] Polymarket ...")
    seen = set()
    results = []

    def add(ev, source=""):
        if not ev: return False
        slug = ev.get("slug","")
        if slug in seen or not slug: return False
        seen.add(slug)
        if get_event_year(ev) < YEAR: return False
        results.append({
            "slug": slug, "title": ev.get("title",""),
            "title_ko": tr_title(ev.get("title","")),
            "endDate": ev.get("endDate",""),
            "closed": ev.get("closed", False),
            "markets": parse_markets(ev),
        })
        mc = len([m for m in results[-1]["markets"] if m["prices"]])
        print(f"    ✅ {slug} (markets={mc}) [{source}]")
        return True

    # ═══ 전략1: 월별 타겟 검색 — "Fed decision in {month}" ═══
    print("  🔍 [1] 월별 타겟 검색")
    for mo_num, mo_en in FOMC_MONTHS.items():
        for q in [f"Fed decision in {mo_en}", f"fed decision {mo_en}"]:
            d = api_get(f"{BASE}/events", {"title": q, "closed": "false", "limit": "20"})
            if isinstance(d, list):
                for ev in d:
                    if get_event_year(ev) >= YEAR:
                        add(ev, f"title:{mo_en}")

    # ═══ 전략2: /markets 엔드포인트로 개별 마켓 → 이벤트 역추적 ═══
    # (events 검색에서 못 찾은 달만)
    found_months = set()
    for r in results:
        tl = r["title"].lower()
        for en in MONTHS_EN:
            if en in tl and "decision" in tl:
                found_months.add(MONTHS_EN.index(en)+1)
    missing = set(FOMC_MONTHS.keys()) - found_months
    
    if missing:
        print(f"  🔍 [2] 누락 달 → markets 검색: {[MO_NUM_KO[m] for m in missing]}")
        for mo in missing:
            mo_en = FOMC_MONTHS[mo]
            # /markets?closed=false 에서 question에 월+2026 포함 검색
            for q in [f"Fed decision in {mo_en.capitalize()}", f"rate {mo_en} {YEAR}"]:
                d = api_get(f"{BASE}/markets", {"closed": "false", "limit": "50"})
                if isinstance(d, list):
                    for mkt in d:
                        question = mkt.get("question","").lower()
                        if mo_en in question and ("fed" in question or "rate" in question):
                            # 이벤트 슬러그 추출
                            event_slug = mkt.get("eventSlug","")
                            if event_slug and event_slug not in seen:
                                ev_data = api_get(f"{BASE}/events/slug/{event_slug}")
                                if ev_data:
                                    ev = ev_data if isinstance(ev_data, dict) else (ev_data[0] if isinstance(ev_data, list) else None)
                                    add(ev, f"market→event:{event_slug}")

    # ═══ 전략3: 태그 검색 ═══
    print("  🔍 [3] 태그 검색")
    for tag in ["fed-rates", "federal-reserve", "fed", "fomc"]:
        d = api_get(f"{BASE}/events", {"tag": tag, "closed": "false", "active": "true", "limit": "100"})
        if isinstance(d, list):
            for ev in d:
                t = ev.get("title","").lower()
                if "fed" in t and ("decision" in t or "rate" in t or "cut" in t):
                    add(ev, f"tag:{tag}")

    # ═══ 전략4: 일반 텍스트 검색 (다양한 쿼리) ═══
    print("  🔍 [4] 텍스트 검색")
    for q in ["how many fed rate cuts", "fed funds rate end", "Fed Decision"]:
        d = api_get(f"{BASE}/events", {"title": q, "closed": "false", "limit": "20"})
        if isinstance(d, list):
            for ev in d:
                add(ev, f"search:{q}")
    
    # offset 기반 페이징도 시도
    for offset in [0, 20, 40]:
        d = api_get(f"{BASE}/events", {"title": "Fed", "closed": "false", "limit": "20", "offset": str(offset)})
        if isinstance(d, list):
            for ev in d:
                t = ev.get("title","").lower()
                if "fed" in t and "decision" in t:
                    add(ev, f"page:{offset}")

    # ═══ 전략5: slug 직접 조회 ═══
    print("  🔍 [5] 슬러그 직접")
    slug_bases = [f"fed-decision-in-{mo}" for mo in MONTHS_EN]
    slug_bases += [f"how-many-fed-rate-cuts-in-{YEAR}",
                   f"what-will-the-fed-rate-be-at-the-end-of-{YEAR}"]
    for s in slug_bases:
        if s in seen: continue
        d = api_get(f"{BASE}/events/slug/{s}")
        if d:
            ev = d if isinstance(d, dict) and d.get("slug") else (d[0] if isinstance(d, list) and d else None)
            add(ev, "slug")

    # ═══ 전략6: 아직 누락된 달 → 슬러그 접미사 브루트포스 ═══
    found_months2 = set()
    for r in results:
        tl = r["title"].lower()
        for en in MONTHS_EN:
            if en in tl and "decision" in tl:
                found_months2.add(MONTHS_EN.index(en)+1)
    still_missing = set(FOMC_MONTHS.keys()) - found_months2
    
    if still_missing:
        print(f"  🔍 [6] 접미사 브루트포스: {[MO_NUM_KO[m] for m in still_missing]}")
        for mo in still_missing:
            mo_en = FOMC_MONTHS[mo]
            base = f"fed-decision-in-{mo_en}"
            found = False
            # 넓은 범위, 작은 스텝
            for suffix in list(range(1, 20)) + list(range(100, 1100, 5)):
                slug = f"{base}-{suffix}"
                d = api_get(f"{BASE}/events/slug/{slug}")
                if d:
                    ev = d if isinstance(d, dict) and d.get("slug") else (d[0] if isinstance(d, list) and d else None)
                    if ev and get_event_year(ev) >= YEAR:
                        add(ev, f"bruteforce:{suffix}")
                        found = True
                        break
            if not found:
                print(f"    ❌ {mo_en}: 접미사 못 찾음")

    results.sort(key=lambda x: x.get("endDate",""))
    
    # 최종 리포트
    final_months = set()
    for r in results:
        tl = r["title"].lower()
        for en in MONTHS_EN:
            if en in tl and "decision" in tl:
                final_months.add(MONTHS_EN.index(en)+1)
    
    print(f"\n  🎯 최종: {len(results)}개 이벤트")
    for r in results:
        print(f"    • {r['slug']}")
    
    covered = final_months & set(FOMC_MONTHS.keys())
    uncovered = set(FOMC_MONTHS.keys()) - final_months
    print(f"  📊 FOMC 매핑: {len(covered)}/{len(FOMC_MONTHS)} ({', '.join(MO_NUM_KO[m] for m in sorted(covered))})")
    if uncovered:
        print(f"  ⚠️ 미매핑: {', '.join(MO_NUM_KO[m] for m in sorted(uncovered))}")
    
    return results

# ═══════════════ Main ═══════════════
def main():
    print("="*55)
    print(f"🏦 Fed Rate Dashboard v3.4 | {NOW.strftime('%Y-%m-%d %H:%M UTC')}")
    print("="*55)

    output = {
        "meta": {"updated_at": NOW.isoformat()+"Z", "year": YEAR, "version": "3.4"},
        "fomc_calendar": build_fomc_calendar(),
        "sofr": fetch_sofr(),
        "fed_funds_target": fetch_fred_target_rate(),
        "polymarket": fetch_polymarket(),
    }

    os.makedirs("data", exist_ok=True)
    with open("data/rate_data.json", "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    tgt = output["fed_funds_target"]
    tgt_str = f"{tgt['lower']:.2f}~{tgt['upper']:.2f}%" if tgt and "upper" in tgt else "N/A"
    print(f"\n✅ 저장 완료")
    print(f"   캘린더 {len(output['fomc_calendar'])}개 | SOFR {len(output['sofr'])}일 | 목표금리 {tgt_str}")
    print(f"   Polymarket {len(output['polymarket'])}개 이벤트")

if __name__ == "__main__":
    main()
