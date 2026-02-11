#!/usr/bin/env python3
"""
Fed Rate Dashboard v3.2
========================
- Polymarket: /events/slug/ 경로 방식으로 수정 (핵심 버그 수정!)
- FRED: Fed Funds 목표금리 (DFEDTARU/DFEDTARL) 실시간 조회
- Kalshi 제거
- 2026년 FOMC 전체 일정 표시
"""

import json, requests, re, os
from datetime import datetime, timedelta

TIMEOUT = 15
HDR = {"User-Agent": "FedRateDashboard/3.2", "Accept": "application/json"}
NOW = datetime.utcnow()
YEAR = NOW.year

MONTHS_EN = ["january","february","march","april","may","june",
             "july","august","september","october","november","december"]
MO_KO = {m: f"{i+1}월" for i, m in enumerate(MONTHS_EN)}
MO_NUM_KO = {i+1: f"{i+1}월" for i in range(12)}

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
    t = re.sub(r"(?i)fed funds rate (?:at )?(?:the )?end of (\d{4})", lambda m: f"{m[1]}년 말 기준금리", t)
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
    return o

# ═══════════════════════ FOMC 캘린더 ═══════════════════════

FOMC_DATES = {
    2025: [(1,28,29),(3,18,19),(5,6,7),(6,17,18),(7,29,30),(9,16,17),(10,28,29),(12,9,10)],
    2026: [(1,27,28),(3,17,18),(5,5,6),(6,16,17),(7,28,29),(9,15,16),(10,27,28),(12,8,9)],
    2027: [(1,26,27),(3,16,17),(5,4,5),(6,15,16),(7,27,28),(9,21,22),(10,26,27),(12,14,15)],
}

def build_fomc_calendar():
    """올해 FOMC 전체 일정"""
    print("[0] FOMC 캘린더 ...")
    cal = []
    today = NOW.strftime("%Y-%m-%d")
    dates = FOMC_DATES.get(YEAR, [])
    for mo, d1, d2 in dates:
        date_str = f"{YEAR}-{mo:02d}-{d1:02d}"
        end_str = f"{YEAR}-{mo:02d}-{d2:02d}"
        cal.append({
            "date": date_str, "end_date": end_str,
            "month": mo, "year": YEAR,
            "label": MO_NUM_KO[mo],
            "is_past": end_str < today,
        })
    print(f"  ✅ {YEAR}년 {len(cal)}개 미팅")
    return cal

# ═══════════════════════ SOFR ═══════════════════════

def fetch_sofr():
    print("[1] NY Fed SOFR ...")
    try:
        r = requests.get("https://markets.newyorkfed.org/api/rates/secured/sofr/last/90.json",
                         headers=HDR, timeout=TIMEOUT)
        r.raise_for_status()
        d = [{"date":x["effectiveDate"],"rate":float(x["percentRate"])}
             for x in r.json().get("refRates",[]) if x.get("percentRate")]
        d.sort(key=lambda x:x["date"])
        print(f"  ✅ {len(d)}일")
        return d
    except Exception as e:
        print(f"  ❌ {e}"); return []

# ═══════════════════════ FRED ═══════════════════════

def fetch_fred_target_rate():
    """FRED에서 현재 Fed Funds 목표금리 조회 (DFEDTARU/DFEDTARL)"""
    api_key = os.environ.get("FRED_API_KEY", "")
    if not api_key:
        print("[2] FRED 목표금리 ⏭️ (API키 없음)")
        return None

    print("[2] FRED 목표금리 ...")
    result = {}
    for series, label in [("DFEDTARU","upper"), ("DFEDTARL","lower")]:
        try:
            r = requests.get(
                f"https://api.stlouisfed.org/fred/series/observations"
                f"?series_id={series}&api_key={api_key}&file_type=json"
                f"&sort_order=desc&limit=5",
                timeout=TIMEOUT
            )
            r.raise_for_status()
            obs = r.json().get("observations", [])
            for o in obs:
                if o.get("value", ".") != ".":
                    result[label] = float(o["value"])
                    result[f"{label}_date"] = o["date"]
                    break
        except Exception as e:
            print(f"  ⚠️ {series}: {e}")

    if "upper" in result and "lower" in result:
        print(f"  ✅ {result['lower']:.2f}~{result['upper']:.2f}%")
        return result
    print("  ⚠️ 일부 데이터 누락")
    return result if result else None

# ═══════════════════════ Polymarket ═══════════════════════

def fetch_polymarket():
    """
    Polymarket API - 공식 문서 기준:
    ★ /events/slug/{slug} — 개별 이벤트 조회 (핵심!)
    ★ /events?tag=... — 태그로 검색
    """
    print("[3] Polymarket ...")
    BASE = "https://gamma-api.polymarket.com"
    seen = set()
    fomc_decisions = []

    def fetch_by_slug(slug):
        """★ 공식 API: /events/slug/{slug}"""
        try:
            url = f"{BASE}/events/slug/{slug}"
            r = requests.get(url, headers=HDR, timeout=TIMEOUT)
            if r.status_code == 200:
                d = r.json()
                if isinstance(d, dict) and d.get("slug"):
                    return d
                if isinstance(d, list) and d:
                    return d[0]
            print(f"    ⚠️ slug={slug}: HTTP {r.status_code}")
        except Exception as e:
            print(f"    ⚠️ slug={slug}: {e}")
        return None

    def fetch_events(params):
        """이벤트 목록 조회"""
        try:
            r = requests.get(f"{BASE}/events", params=params, headers=HDR, timeout=TIMEOUT)
            if r.status_code == 200:
                d = r.json()
                return d if isinstance(d, list) else []
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
        if not ev: return
        slug = ev.get("slug","")
        if slug in seen or not slug: return
        seen.add(slug)
        title = ev.get("title","")
        end = ev.get("endDate","")

        # 너무 오래된 이벤트 제외
        if end:
            try:
                ey = datetime.fromisoformat(end.replace("Z","")).year
                if ey < YEAR: return  # 과거 연도 제외
            except: pass

        obj = {
            "slug": slug, "title": title, "title_ko": tr_title(title),
            "endDate": end, "closed": ev.get("closed", False),
            "markets": parse_markets(ev),
        }
        fomc_decisions.append(obj)

    # ★ 전략A: 슬러그 경로로 직접 조회 (핵심!)
    print("  📌 슬러그 직접 조회 (/events/slug/)")
    for mo in MONTHS_EN:
        slug = f"fed-decision-in-{mo}"
        ev = fetch_by_slug(slug)
        if ev:
            add_event(ev)
            print(f"    ✅ {slug}")

    # 추가 슬러그들
    extra_slugs = [
        f"how-many-fed-rate-cuts-in-{YEAR}",
        f"how-many-fed-rate-cuts-in-{YEAR+1}",
        f"what-will-the-fed-rate-be-at-the-end-of-{YEAR}",
    ]
    for slug in extra_slugs:
        ev = fetch_by_slug(slug)
        if ev:
            add_event(ev)
            print(f"    ✅ {slug}")

    # ★ 전략B: 태그로 검색 (보충)
    print("  📌 태그 검색")
    for tag in ["fed-rates", "federal-reserve", "interest-rates"]:
        for ev in fetch_events({"tag": tag, "active": "true", "closed": "false", "limit": "50"}):
            title = ev.get("title","").lower()
            if "fed" in title and ("decision" in title or "rate" in title):
                add_event(ev)

    fomc_decisions.sort(key=lambda x: x.get("endDate",""))
    print(f"  ✅ 총 {len(fomc_decisions)}개 이벤트")
    return fomc_decisions

# ═══════════════════════ Main ═══════════════════════

def main():
    print("="*55)
    print(f"🏦 Fed Rate Dashboard v3.2 | {NOW.strftime('%Y-%m-%d %H:%M UTC')}")
    print("="*55)

    output = {
        "meta": {"updated_at": NOW.isoformat()+"Z", "year": YEAR, "version": "3.2"},
        "fomc_calendar": build_fomc_calendar(),
        "sofr": fetch_sofr(),
        "fed_funds_target": fetch_fred_target_rate(),
        "polymarket": fetch_polymarket(),
    }

    os.makedirs("data", exist_ok=True)
    with open("data/rate_data.json", "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    pm = output["polymarket"]
    tgt = output["fed_funds_target"]
    tgt_str = f"{tgt['lower']:.2f}~{tgt['upper']:.2f}%" if tgt and "upper" in tgt else "N/A"
    print(f"\n✅ 저장: data/rate_data.json")
    print(f"   캘린더 {len(output['fomc_calendar'])}개 | SOFR {len(output['sofr'])}일")
    print(f"   목표금리: {tgt_str}")
    print(f"   Polymarket: {len(pm)}개 이벤트")

if __name__ == "__main__":
    main()
