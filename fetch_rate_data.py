#!/usr/bin/env python3
"""
Fed Rate Dashboard - 자동 연도 대응 데이터 수집기 v2.1
======================================================
무료 API만 사용. 하드코딩된 연도 없이 동적 탐색.
한글 번역 포함.
"""

import json
import requests
import re
import os
from datetime import datetime, timedelta

TIMEOUT = 15
HEADERS = {"User-Agent": "FedRateDashboard/2.1", "Accept": "application/json"}
NOW = datetime.utcnow()
THIS_YEAR = NOW.year

MONTHS = [
    "january", "february", "march", "april", "may", "june",
    "july", "august", "september", "october", "november", "december",
]
MONTH_KO = {
    "january": "1월", "february": "2월", "march": "3월", "april": "4월",
    "may": "5월", "june": "6월", "july": "7월", "august": "8월",
    "september": "9월", "october": "10월", "november": "11월", "december": "12월",
}


# ─────────────────────────────────────────────
# 한글 번역
# ─────────────────────────────────────────────
def translate_title(title):
    t = title
    for eng, ko in MONTH_KO.items():
        t = re.sub(rf"(?i)Fed [Dd]ecision in {eng}\??", f"{ko} FOMC 금리 결정", t)
    t = re.sub(r"(?i)what will the fed (funds )?rate be at the end of (\d{4})\??",
               lambda m: f"{m.group(2)}년 말 Fed 기준금리 전망", t)
    t = re.sub(r"(?i)how many fed rate cuts in (\d{4})\??",
               lambda m: f"{m.group(1)}년 Fed 금리 인하 횟수", t)
    t = re.sub(r"(?i)will the fed (raise|hike) rates.*?(\d{4})\??",
               lambda m: f"{m.group(2)}년 Fed 금리 인상 여부", t)
    t = re.sub(r"(?i)will the fed cut rates.*?(\d{4})\??",
               lambda m: f"{m.group(2)}년 Fed 금리 인하 여부", t)
    t = re.sub(r"(?i)fed rate (cut|hike|increase|decrease)",
               lambda m: "금리 " + ("인하" if m.group(1) in ("cut","decrease") else "인상"), t)
    t = re.sub(r"(?i)us inflation rate", "미국 인플레이션율", t)
    return t


def translate_outcome(outcome):
    o = outcome.strip()
    mappings = {
        "Yes": "예", "No": "아니오",
        "No change": "동결",
        "25 bps decrease": "25bp 인하", "25 bps cut": "25bp 인하",
        "50 bps decrease": "50bp 인하", "50 bps cut": "50bp 인하",
        "75 bps decrease": "75bp 인하", "100 bps decrease": "100bp 인하",
        "25 bps increase": "25bp 인상", "50 bps increase": "50bp 인상",
        "Increase": "인상", "Decrease": "인하",
    }
    if o in mappings:
        return mappings[o]
    m = re.match(r"(\d+)\s*bps?\s*(decrease|cut)", o, re.I)
    if m: return f"{m.group(1)}bp 인하"
    m = re.match(r"(\d+)\s*bps?\s*(increase|hike)", o, re.I)
    if m: return f"{m.group(1)}bp 인상"
    m = re.match(r"(\d+\.\d+)\s*[-–]\s*(\d+\.\d+)", o)
    if m: return f"{m.group(1)}~{m.group(2)}%"
    m = re.match(r"(\d+)\s*cuts?", o, re.I)
    if m: return f"{m.group(1)}회 인하"
    m = re.match(r"(\d+)\s*or more", o, re.I)
    if m: return f"{m.group(1)}회 이상"
    return o


# ─────────────────────────────────────────────
# Fed 관련 필터
# ─────────────────────────────────────────────
FED_KEYWORDS = [
    "fed ", "fomc", "federal reserve", "fed funds", "rate cut", "rate hike",
    "interest rate", "monetary policy", "basis point", "bps",
    "rate decision", "fed decision",
]

def is_fed_related(title):
    tl = title.lower()
    return any(kw in tl for kw in FED_KEYWORDS)


# ─────────────────────────────────────────────
# 1. NY Fed - SOFR
# ─────────────────────────────────────────────
def fetch_sofr():
    print("[1/4] NY Fed SOFR ...")
    url = "https://markets.newyorkfed.org/api/rates/secured/sofr/last/60.json"
    try:
        r = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
        r.raise_for_status()
        items = r.json().get("refRates", [])
        data = [
            {"date": x["effectiveDate"], "rate": float(x["percentRate"])}
            for x in items if x.get("percentRate")
        ]
        data.sort(key=lambda x: x["date"])
        print(f"  ✅ {len(data)}일치 수집")
        return data
    except Exception as e:
        print(f"  ❌ 실패: {e}")
        return []


# ─────────────────────────────────────────────
# 2. FRED - SOFR 장기 히스토리
# ─────────────────────────────────────────────
def fetch_fred_sofr():
    api_key = os.environ.get("FRED_API_KEY", "")
    if not api_key:
        print("[2/4] FRED ⏭️  (FRED_API_KEY 미설정)")
        return []
    print("[2/4] FRED SOFR ...")
    start = (NOW - timedelta(days=365)).strftime("%Y-%m-%d")
    url = (
        f"https://api.stlouisfed.org/fred/series/observations"
        f"?series_id=SOFR&api_key={api_key}&file_type=json"
        f"&observation_start={start}&sort_order=asc"
    )
    try:
        r = requests.get(url, timeout=TIMEOUT)
        r.raise_for_status()
        obs = r.json().get("observations", [])
        data = [
            {"date": o["date"], "rate": float(o["value"])}
            for o in obs if o.get("value", ".") != "."
        ]
        print(f"  ✅ {len(data)}일치 수집")
        return data
    except Exception as e:
        print(f"  ❌ 실패: {e}")
        return []


# ─────────────────────────────────────────────
# 3. Polymarket - 다중 전략 탐색
# ─────────────────────────────────────────────
def fetch_polymarket():
    print("[3/4] Polymarket ...")
    BASE = "https://gamma-api.polymarket.com"
    seen_slugs = set()
    results = {"fomc_decisions": [], "other_markets": []}

    def try_fetch_events(params, label=""):
        """이벤트 목록 가져오기"""
        found = []
        try:
            r = requests.get(f"{BASE}/events", params=params,
                             headers=HEADERS, timeout=TIMEOUT)
            if r.status_code == 200:
                data = r.json()
                if isinstance(data, list):
                    found = data
                elif isinstance(data, dict) and data.get("slug"):
                    found = [data]
        except:
            pass
        return found

    def parse_event(ev):
        slug = ev.get("slug", "")
        if slug in seen_slugs or not slug:
            return
        seen_slugs.add(slug)

        title = ev.get("title", "")
        if not is_fed_related(title):
            return

        title_ko = translate_title(title)
        markets_raw = ev.get("markets", [])
        parsed_markets = []

        for m in markets_raw:
            try: outcomes = json.loads(m.get("outcomes", "[]"))
            except: outcomes = []
            try: prices = json.loads(m.get("outcomePrices", "[]"))
            except: prices = []

            parsed_markets.append({
                "question": translate_title(m.get("question", "")),
                "groupItemTitle": translate_title(m.get("groupItemTitle", "")),
                "outcomes": [translate_outcome(o) for o in outcomes],
                "outcomes_en": outcomes,
                "prices": [float(p) for p in prices] if prices else [],
                "volume": float(m.get("volume", 0) or 0),
                "liquidity": float(m.get("liquidity", 0) or 0),
            })

        event_obj = {
            "slug": slug,
            "title": title,
            "title_ko": title_ko,
            "endDate": ev.get("endDate", ""),
            "markets": parsed_markets,
        }

        tl = title.lower()
        is_fomc = ("fed decision" in tl or "fomc" in tl) and \
                  any(mo in tl for mo in MONTHS)

        if is_fomc:
            results["fomc_decisions"].append(event_obj)
        else:
            results["other_markets"].append(event_obj)

    # ── 전략 A: 슬러그 패턴 직접 조회 ──
    print("  📌 전략A: 슬러그 패턴")
    for month in MONTHS:
        for ev in try_fetch_events({"slug": f"fed-decision-in-{month}"}):
            parse_event(ev)

    extra_slugs = [
        "how-many-fed-rate-cuts",
        f"how-many-fed-rate-cuts-in-{THIS_YEAR}",
        f"how-many-fed-rate-cuts-in-{THIS_YEAR+1}",
        "what-will-the-fed-rate-be",
        f"what-will-the-fed-rate-be-at-the-end-of-{THIS_YEAR}",
        f"what-will-the-fed-rate-be-at-the-end-of-{THIS_YEAR+1}",
        "will-the-fed-raise-rates",
        "fed-rate-cut",
        "federal-funds-rate",
    ]
    for slug in extra_slugs:
        for ev in try_fetch_events({"slug": slug}):
            parse_event(ev)

    print(f"    → FOMC {len(results['fomc_decisions'])}개, 기타 {len(results['other_markets'])}개")

    # ── 전략 B: 태그 검색 ──
    print("  📌 전략B: 태그 검색")
    for tag in ["fed-rates", "fed", "federal-reserve", "interest-rates", "fomc"]:
        for ev in try_fetch_events({"tag": tag, "active": "true", "closed": "false", "limit": "50"}):
            parse_event(ev)

    # ── 전략 C: 텍스트 검색 ──
    print("  📌 전략C: 텍스트 검색")
    for q in ["fed rate", "fomc", "federal reserve", f"rate cut {THIS_YEAR}", f"rate cut {THIS_YEAR+1}"]:
        for ev in try_fetch_events({"title": q, "active": "true", "closed": "false", "limit": "20"}):
            parse_event(ev)

    results["fomc_decisions"].sort(key=lambda x: x.get("endDate", ""))
    results["other_markets"].sort(key=lambda x: x.get("endDate", ""))

    print(f"  ✅ 최종: FOMC {len(results['fomc_decisions'])}개, 기타 {len(results['other_markets'])}개")
    return results


# ─────────────────────────────────────────────
# 4. Kalshi - Fed 시리즈만
# ─────────────────────────────────────────────
def fetch_kalshi():
    print("[4/4] Kalshi ...")
    BASE = "https://api.elections.kalshi.com/trade-api/v2"
    results = []

    for ticker in ["KXFEDDECISION", "KXFED", "KXRATECUTCOUNT", "KXLARGECUT"]:
        try:
            r = requests.get(
                f"{BASE}/markets",
                params={"series_ticker": ticker, "status": "open", "limit": "40"},
                headers=HEADERS, timeout=TIMEOUT,
            )
            if r.status_code != 200:
                continue
            markets_raw = r.json().get("markets", [])
            if not markets_raw:
                continue

            series_obj = {"series_ticker": ticker, "markets": []}
            for m in markets_raw:
                series_obj["markets"].append({
                    "ticker": m.get("ticker", ""),
                    "title": m.get("title", ""),
                    "title_ko": translate_title(m.get("title", "")),
                    "subtitle": m.get("subtitle", ""),
                    "subtitle_ko": translate_title(m.get("subtitle", "")) if m.get("subtitle") else "",
                    "yes_bid": m.get("yes_bid"),
                    "yes_ask": m.get("yes_ask"),
                    "last_price": m.get("last_price"),
                    "volume": m.get("volume"),
                    "open_interest": m.get("open_interest"),
                    "close_time": m.get("close_time", ""),
                    "expiration_time": m.get("expiration_time", ""),
                })
            results.append(series_obj)
            print(f"  📊 {ticker}: {len(markets_raw)}개 마켓")
        except Exception as e:
            print(f"  ⚠️ {ticker}: {e}")

    print(f"  ✅ 총 {len(results)}개 시리즈 수집")
    return results


def main():
    print("=" * 55)
    print("🏦 Fed Rate Dashboard - Data Fetcher v2.1")
    print(f"📅 {NOW.strftime('%Y-%m-%d %H:%M UTC')}")
    print("=" * 55)

    output = {
        "meta": {
            "updated_at": NOW.isoformat() + "Z",
            "year": THIS_YEAR,
            "version": "2.1",
        },
        "sofr": fetch_sofr(),
        "fred_sofr": fetch_fred_sofr(),
        "polymarket": fetch_polymarket(),
        "kalshi": fetch_kalshi(),
    }

    os.makedirs("data", exist_ok=True)
    with open("data/rate_data.json", "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print()
    print("✅ 저장 완료: data/rate_data.json")
    pm = output["polymarket"]
    print(f"   SOFR: {len(output['sofr'])}일")
    print(f"   Polymarket: FOMC {len(pm['fomc_decisions'])}개 + 기타 {len(pm['other_markets'])}개")
    print(f"   Kalshi: {len(output['kalshi'])}개 시리즈")


if __name__ == "__main__":
    main()
