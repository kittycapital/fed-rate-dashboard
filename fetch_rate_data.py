#!/usr/bin/env python3
"""
Fed Rate Dashboard v3.0
========================
FOMC 캘린더 뼈대 + Polymarket(메인) + Kalshi(인하 횟수) + NY Fed SOFR
무료 API만 사용. 하드코딩 연도 최소화.
"""

import json, requests, re, os
from datetime import datetime, timedelta

TIMEOUT = 15
HDR = {"User-Agent": "FedRateDashboard/3.0", "Accept": "application/json"}
NOW = datetime.utcnow()
YEAR = NOW.year

MONTHS_EN = ["january","february","march","april","may","june",
             "july","august","september","october","november","december"]
MO_KO = {m: f"{i+1}월" for i, m in enumerate(MONTHS_EN)}
MO_NUM_KO = {i+1: f"{i+1}월" for i in range(12)}

# ═══════════════════════ 번역 ═══════════════════════

def tr_title(t):
    # 전체 문장 먼저
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
    t = re.sub(r"(?i)fed funds rate (?:at )?(?:the )?end of (\d{4})", lambda m: f"{m[1]}년 말 기준금리", t)
    t = re.sub(r"(?i)will the fed (?:raise|hike) rates?.*?(\d{4})\??", lambda m: f"{m[1]}년 Fed 금리 인상 여부", t)
    t = re.sub(r"(?i)will the fed cut rates?.*?(\d{4})\??", lambda m: f"{m[1]}년 Fed 금리 인하 여부", t)
    return t

def tr_outcome(o):
    o = o.strip()
    m = {"Yes":"예","No":"아니오","No change":"동결",
         "25 bps decrease":"25bp 인하","25 bps cut":"25bp 인하",
         "50 bps decrease":"50bp 인하","50 bps cut":"50bp 인하",
         "75 bps decrease":"75bp 인하","100 bps decrease":"100bp 인하",
         "25 bps increase":"25bp 인상","50 bps increase":"50bp 인상",
         "Increase":"인상","Decrease":"인하"}
    if o in m: return m[o]
    r = re.match(r"(\d+)\s*bps?\s*(decrease|cut)", o, re.I)
    if r: return f"{r[1]}bp 인하"
    r = re.match(r"(\d+)\s*bps?\s*(increase|hike)", o, re.I)
    if r: return f"{r[1]}bp 인상"
    r = re.match(r"(\d+\.\d+)\s*[-–]\s*(\d+\.\d+)", o)
    if r: return f"{r[1]}~{r[2]}%"
    r = re.match(r"(\d+)\s*cuts?", o, re.I)
    if r: return f"{r[1]}회 인하"
    r = re.match(r"(\d+)\s*or more", o, re.I)
    if r: return f"{r[1]}회 이상"
    return o

FED_KW = ["fed ","fomc","federal reserve","fed funds","rate cut","rate hike",
           "interest rate","rate decision","fed decision","basis point","bps"]
def is_fed(t): return any(k in t.lower() for k in FED_KW)

# ═══════════════════════ FOMC 캘린더 ═══════════════════════

FOMC_DATES = {
    2025: [(1,28,29),(3,18,19),(5,6,7),(6,17,18),(7,29,30),(9,16,17),(10,28,29),(12,9,10)],
    2026: [(1,27,28),(3,17,18),(5,5,6),(6,16,17),(7,28,29),(9,15,16),(10,27,28),(12,8,9)],
    2027: [(1,26,27),(3,16,17),(5,4,5),(6,15,16),(7,27,28),(9,21,22),(10,26,27),(12,14,15)],
}

def build_fomc_calendar():
    """올해+다음해 FOMC 캘린더 생성"""
    print("[0] FOMC 캘린더 ...")
    cal = []
    today = NOW.strftime("%Y-%m-%d")
    for yr in [YEAR, YEAR+1]:
        dates = FOMC_DATES.get(yr, [])
        if not dates:
            # 패턴: FOMC는 대략 1,3,5,6,7,9,10,12월
            dates = [(1,28,29),(3,18,19),(5,6,7),(6,17,18),(7,29,30),(9,16,17),(10,28,29),(12,9,10)]
        for mo, d1, d2 in dates:
            date_str = f"{yr}-{mo:02d}-{d1:02d}"
            end_str = f"{yr}-{mo:02d}-{d2:02d}"
            cal.append({
                "date": date_str, "end_date": end_str,
                "month": mo, "year": yr,
                "label": MO_NUM_KO[mo],
                "is_past": end_str < today,
            })
    print(f"  ✅ {len(cal)}개 미팅")
    return cal

# ═══════════════════════ SOFR ═══════════════════════

def fetch_sofr():
    print("[1] NY Fed SOFR ...")
    try:
        r = requests.get("https://markets.newyorkfed.org/api/rates/secured/sofr/last/60.json",
                         headers=HDR, timeout=TIMEOUT)
        r.raise_for_status()
        d = [{"date":x["effectiveDate"],"rate":float(x["percentRate"])}
             for x in r.json().get("refRates",[]) if x.get("percentRate")]
        d.sort(key=lambda x:x["date"])
        print(f"  ✅ {len(d)}일")
        return d
    except Exception as e:
        print(f"  ❌ {e}"); return []

def fetch_fred():
    key = os.environ.get("FRED_API_KEY","")
    if not key: print("[2] FRED ⏭️"); return []
    print("[2] FRED ...")
    try:
        r = requests.get(f"https://api.stlouisfed.org/fred/series/observations"
                         f"?series_id=SOFR&api_key={key}&file_type=json"
                         f"&observation_start={(NOW-timedelta(365)).strftime('%Y-%m-%d')}&sort_order=asc",
                         timeout=TIMEOUT)
        r.raise_for_status()
        d = [{"date":o["date"],"rate":float(o["value"])}
             for o in r.json().get("observations",[]) if o.get("value",".")!="."]
        print(f"  ✅ {len(d)}일"); return d
    except Exception as e:
        print(f"  ❌ {e}"); return []

# ═══════════════════════ Polymarket ═══════════════════════

def fetch_polymarket():
    print("[3] Polymarket ...")
    BASE = "https://gamma-api.polymarket.com"
    seen = set()
    fomc_decisions = []
    other_markets = []

    def api(params):
        try:
            r = requests.get(f"{BASE}/events", params=params, headers=HDR, timeout=TIMEOUT)
            if r.status_code == 200:
                d = r.json()
                return d if isinstance(d, list) else [d] if isinstance(d, dict) and d.get("slug") else []
        except: pass
        return []

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

    def add_event(ev):
        slug = ev.get("slug","")
        if slug in seen or not slug: return
        seen.add(slug)
        title = ev.get("title","")
        if not is_fed(title): return

        end = ev.get("endDate","")
        # 연도 필터: 너무 오래된 이벤트 제외
        if end:
            try:
                ey = datetime.fromisoformat(end.replace("Z","")).year
                if ey < YEAR - 1: return
            except: pass

        obj = {
            "slug": slug, "title": title, "title_ko": tr_title(title),
            "endDate": end, "closed": ev.get("closed", False),
            "markets": parse_markets(ev),
        }
        tl = title.lower()
        is_fomc = ("fed decision" in tl) and any(m in tl for m in MONTHS_EN)
        if is_fomc:
            fomc_decisions.append(obj)
        else:
            other_markets.append(obj)

    # A) 슬러그 패턴 — 핵심
    print("  📌 슬러그 패턴")
    for mo in MONTHS_EN:
        for ev in api({"slug": f"fed-decision-in-{mo}"}):
            add_event(ev)

    for slug in [
        f"how-many-fed-rate-cuts-in-{YEAR}", f"how-many-fed-rate-cuts-in-{YEAR+1}",
        f"what-will-the-fed-rate-be-at-the-end-of-{YEAR}",
        f"what-will-the-fed-rate-be-at-the-end-of-{YEAR+1}",
        "how-many-fed-rate-cuts", "what-will-the-fed-rate-be",
        "will-the-fed-raise-rates", "federal-funds-rate",
    ]:
        for ev in api({"slug": slug}):
            add_event(ev)

    # B) 태그
    print("  📌 태그")
    for tag in ["fed-rates","fed","federal-reserve","interest-rates","fomc"]:
        for ev in api({"tag": tag, "active": "true", "closed": "false", "limit": "50"}):
            add_event(ev)

    # C) 텍스트
    print("  📌 텍스트")
    for q in ["fed rate", "fomc", "federal reserve", f"rate cut {YEAR}"]:
        for ev in api({"title": q, "active": "true", "closed": "false", "limit": "20"}):
            add_event(ev)

    fomc_decisions.sort(key=lambda x: x.get("endDate",""))
    other_markets.sort(key=lambda x: x.get("endDate",""))
    print(f"  ✅ FOMC {len(fomc_decisions)}개, 기타 {len(other_markets)}개")
    return {"fomc_decisions": fomc_decisions, "other_markets": other_markets}

# ═══════════════════════ Kalshi ═══════════════════════

def fetch_kalshi():
    print("[4] Kalshi ...")
    BASE = "https://api.elections.kalshi.com/trade-api/v2"
    results = {}

    for ticker in ["KXFEDDECISION", "KXRATECUTCOUNT", "KXFED"]:
        try:
            r = requests.get(f"{BASE}/markets",
                             params={"series_ticker": ticker, "status": "open", "limit": "40"},
                             headers=HDR, timeout=TIMEOUT)
            if r.status_code != 200: continue
            mkts = r.json().get("markets", [])
            if not mkts: continue
            results[ticker] = [{
                "ticker": m.get("ticker",""),
                "title": m.get("title",""),
                "title_ko": tr_title(m.get("title","")),
                "subtitle": m.get("subtitle",""),
                "subtitle_ko": tr_title(m.get("subtitle","")) if m.get("subtitle") else "",
                "yes_bid": m.get("yes_bid"),
                "yes_ask": m.get("yes_ask"),
                "last_price": m.get("last_price"),
                "volume": m.get("volume"),
                "open_interest": m.get("open_interest"),
                "close_time": m.get("close_time",""),
            } for m in mkts]
            print(f"  📊 {ticker}: {len(mkts)}개")
        except Exception as e:
            print(f"  ⚠️ {ticker}: {e}")

    print(f"  ✅ {len(results)}개 시리즈")
    return results

# ═══════════════════════ Main ═══════════════════════

def main():
    print("="*55)
    print(f"🏦 Fed Rate Dashboard v3.0 | {NOW.strftime('%Y-%m-%d %H:%M UTC')}")
    print("="*55)

    output = {
        "meta": {"updated_at": NOW.isoformat()+"Z", "year": YEAR, "version": "3.0"},
        "fomc_calendar": build_fomc_calendar(),
        "sofr": fetch_sofr(),
        "fred_sofr": fetch_fred(),
        "polymarket": fetch_polymarket(),
        "kalshi": fetch_kalshi(),
    }

    os.makedirs("data", exist_ok=True)
    with open("data/rate_data.json", "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    pm = output["polymarket"]
    k = output["kalshi"]
    print(f"\n✅ 저장: data/rate_data.json")
    print(f"   캘린더 {len(output['fomc_calendar'])}개 | SOFR {len(output['sofr'])}일")
    print(f"   Poly FOMC {len(pm['fomc_decisions'])}개 + 기타 {len(pm['other_markets'])}개")
    print(f"   Kalshi {', '.join(f'{t}({len(v)})' for t,v in k.items())}")

if __name__ == "__main__":
    main()
