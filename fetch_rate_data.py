#!/usr/bin/env python3
"""
Fed Rate Dashboard v3.5
========================
v3.5 핵심 수정:
  - closed=false 필터만 사용하던 문제 → open+closed 모두 검색
    (7월처럼 이미 종료된 FOMC 이벤트도 데이터 수집)
  - 브루트포스 step 5 → coarse probe(step 10) + refine(step 1)
    (181, 762 같은 접미사 누락 방지)
  
전략:
  1. /events 검색 (title, closed=false + closed=true)
  2. /markets 검색 (question 포함 "{Month} {YEAR}")  
  3. /events 검색 (tag, closed=false + closed=true)
  4. 텍스트 검색 (closed=false + closed=true)
  5. slug 직접 조회
  6. 접미사 스캔 (coarse probe + refine)
"""

import json, requests, re, os
from datetime import datetime

TIMEOUT = 15
HDR = {"User-Agent": "FedRateDashboard/3.5", "Accept": "application/json"}
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

# 확인된 이벤트 슬러그 (접미사가 불규칙해 검색이 놓칠 수 있는 것들)
# 새 달의 슬러그를 알게 되면 여기에 추가하면 즉시 1회 호출로 수집됨
KNOWN_SLUGS = {
    2026: [
        "fed-decision-in-january",
        "fed-decision-in-march-885",
        "fed-decision-in-april",
        "fed-decision-in-june-825",
        "fed-decision-in-july-181",
        "fed-decision-in-september-762",
        "fed-decision-in-october",
        "how-many-fed-rate-cuts-in-2026",
        "what-will-the-fed-rate-be-at-the-end-of-2026",
    ],
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
            # closed 이벤트도 포함 (과거 FOMC 결과 반영)
            for closed_val in ["false", "true"]:
                d = api_get(f"{BASE}/events", {"title": q, "closed": closed_val, "limit": "20"})
                if isinstance(d, list):
                    for ev in d:
                        if get_event_year(ev) >= YEAR:
                            add(ev, f"title:{mo_en}")

    # ═══ 전략2: FOMC 태그 슬러그로 전체 이벤트 페이징 ═══
    # /events?tag_slug=fomc 로 모든 Fed decision 이벤트를 한 번에 수집
    # (제목 검색이 놓친 달을 태그 카탈로그가 채워줌 — closed 무관)
    print("  🔍 [2] FOMC 태그 카탈로그")
    for tag_slug in ["fomc", "fed-rates"]:
        for closed_val in ["false", "true"]:
            for offset in range(0, 200, 50):
                d = api_get(f"{BASE}/events", {
                    "tag_slug": tag_slug, "closed": closed_val,
                    "limit": "50", "offset": str(offset)})
                if isinstance(d, list) and d:
                    for ev in d:
                        t = ev.get("title","").lower()
                        if "fed" in t and ("decision" in t or "rate" in t or "cut" in t):
                            add(ev, f"tag_slug:{tag_slug}")
                else:
                    break  # 빈 페이지면 다음 offset 불필요

    # ═══ 전략3: 태그 검색 ═══
    print("  🔍 [3] 태그 검색")
    for tag in ["fed-rates", "federal-reserve", "fed", "fomc"]:
        for closed_val in ["false", "true"]:
            params = {"tag": tag, "closed": closed_val, "limit": "100"}
            if closed_val == "false":
                params["active"] = "true"
            d = api_get(f"{BASE}/events", params)
            if isinstance(d, list):
                for ev in d:
                    t = ev.get("title","").lower()
                    if "fed" in t and ("decision" in t or "rate" in t or "cut" in t):
                        add(ev, f"tag:{tag}")

    # ═══ 전략4: 일반 텍스트 검색 (다양한 쿼리) ═══
    print("  🔍 [4] 텍스트 검색")
    for q in ["how many fed rate cuts", "fed funds rate end", "Fed Decision"]:
        for closed_val in ["false", "true"]:
            d = api_get(f"{BASE}/events", {"title": q, "closed": closed_val, "limit": "20"})
            if isinstance(d, list):
                for ev in d:
                    add(ev, f"search:{q}")
    
    # offset 기반 페이징도 시도
    for closed_val in ["false", "true"]:
        for offset in [0, 20, 40]:
            d = api_get(f"{BASE}/events", {"title": "Fed", "closed": closed_val, "limit": "20", "offset": str(offset)})
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
    # 알려진 접미사 슬러그 힌트 (앞 전략이 다 실패해도 여기서 잡힘)
    # 새 이벤트 발견 시 이 목록에 추가해두면 항상 1회 호출로 즉시 수집됨
    slug_bases += list(KNOWN_SLUGS.get(YEAR, []))
    for s in slug_bases:
        if s in seen: continue
        d = api_get(f"{BASE}/events/slug/{s}")
        if d:
            ev = d if isinstance(d, dict) and d.get("slug") else (d[0] if isinstance(d, list) and d else None)
            add(ev, "slug")

    # ═══ 전략6: 누락된 달 → /markets 검색 후 eventSlug 역추적 ═══
    # 슬러그 접미사(181, 762 등)를 추측하지 않고, 마켓 question으로 찾아
    # 그 마켓이 속한 이벤트를 slug로 정확히 조회. 접미사에 무관하게 동작.
    found_months2 = set()
    for r in results:
        tl = r["title"].lower()
        for en in MONTHS_EN:
            if en in tl and "decision" in tl:
                found_months2.add(MONTHS_EN.index(en)+1)
    still_missing = set(FOMC_MONTHS.keys()) - found_months2
    
    if still_missing:
        print(f"  🔍 [6] markets 역추적: {[MO_NUM_KO[m] for m in still_missing]}")
        for mo in still_missing:
            mo_en = FOMC_MONTHS[mo]
            mo_cap = mo_en.capitalize()
            found = False
            # question에 "{Month} {YEAR}" 가 포함된 마켓 검색 (open+closed)
            for closed_val in ["false", "true"]:
                for offset in range(0, 500, 100):
                    d = api_get(f"{BASE}/markets", {
                        "closed": closed_val, "limit": "100", "offset": str(offset)})
                    if not (isinstance(d, list) and d):
                        break
                    for mkt in d:
                        q = mkt.get("question","").lower()
                        # "july 2026" 또는 "in july" + fed/rate 조합
                        if mo_en in q and str(YEAR) in q and ("fed" in q or "rate" in q):
                            eslug = mkt.get("eventSlug","") or mkt.get("slug","")
                            if eslug and eslug not in seen:
                                ev_data = api_get(f"{BASE}/events/slug/{eslug}")
                                if ev_data:
                                    ev = ev_data if isinstance(ev_data, dict) and ev_data.get("slug") else (ev_data[0] if isinstance(ev_data, list) and ev_data else None)
                                    if ev and get_event_year(ev) >= YEAR:
                                        add(ev, f"market→event:{eslug}")
                                        found = True
                    if found: break
                if found: break
            if not found:
                print(f"    ⚠️ {mo_en}: 자동 탐색 실패 (수동 슬러그 필요할 수 있음)")

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

# ═══════════════ 데이터 보존 병합 ═══════════════
def load_previous():
    """이전 JSON 로드 (API 실패 시 폴백용)"""
    try:
        with open("data/rate_data.json", "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def merge_preserve(new_pm, old_data):
    """
    새로 수집한 polymarket과 이전 데이터를 병합.
    - 새로 잡힌 이벤트는 최신값 사용
    - 이번에 못 잡은 과거 이벤트(FOMC 결정)는 이전 값 유지
    → 일시적 API 실패가 대시보드를 비우지 않도록 방어
    """
    if not old_data:
        return new_pm
    old_pm = old_data.get("polymarket", [])
    new_by_slug = {e["slug"]: e for e in new_pm}
    merged = list(new_pm)
    for old_e in old_pm:
        slug = old_e.get("slug","")
        if slug in new_by_slug:
            continue  # 새 값이 우선
        # 못 잡은 이벤트 중 실제 가격 데이터가 있던 것만 보존
        has_prices = any(m.get("prices") for m in old_e.get("markets", []))
        # 지난 연도 이벤트는 버림
        try:
            eyr = datetime.fromisoformat(old_e.get("endDate","").replace("Z","")).year
        except Exception:
            eyr = YEAR
        if has_prices and eyr >= YEAR:
            merged.append(old_e)
            print(f"    🔒 이전 데이터 보존: {slug}")
    merged.sort(key=lambda x: x.get("endDate",""))
    return merged

# ═══════════════ Main ═══════════════
def main():
    print("="*55)
    print(f"🏦 Fed Rate Dashboard v3.5 | {NOW.strftime('%Y-%m-%d %H:%M UTC')}")
    print("="*55)

    old_data = load_previous()
    new_pm = fetch_polymarket()
    merged_pm = merge_preserve(new_pm, old_data)

    output = {
        "meta": {"updated_at": NOW.isoformat()+"Z", "year": YEAR, "version": "3.5"},
        "fomc_calendar": build_fomc_calendar(),
        "sofr": fetch_sofr(),
        "fed_funds_target": fetch_fred_target_rate(),
        "polymarket": merged_pm,
    }

    # SOFR/목표금리도 이번에 비었으면 이전 값 유지
    if not output["sofr"] and old_data and old_data.get("sofr"):
        output["sofr"] = old_data["sofr"]
        print("    🔒 SOFR 이전 데이터 보존")
    if not output["fed_funds_target"] and old_data and old_data.get("fed_funds_target"):
        output["fed_funds_target"] = old_data["fed_funds_target"]
        print("    🔒 목표금리 이전 데이터 보존")

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
