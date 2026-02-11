#!/usr/bin/env python3
"""
Fed Rate Dashboard - 자동 연도 대응 데이터 수집기
==================================================
하드코딩된 연도/날짜 없이, API에서 활성 마켓을 자동 탐색합니다.
2026년이든 2027년이든 자동으로 해당 연도의 FOMC 데이터를 수집합니다.

무료 API만 사용:
  1. NY Fed Markets API  → SOFR 현재/과거 금리 (무료, 인증 불필요)
  2. Polymarket Gamma API → Fed 금리 예측 (무료, 인증 불필요)
  3. Kalshi Public API    → Fed 금리 예측 (무료, 인증 불필요)
  4. FRED API             → SOFR 장기 히스토리 (무료, API키 필요)

사용법:
  pip install requests
  python fetch_rate_data.py

GitHub Actions로 매일 자동 실행 → data/rate_data.json 생성
"""

import json
import requests
import os
from datetime import datetime, timedelta

TIMEOUT = 15
HEADERS = {"User-Agent": "FedRateDashboard/2.0", "Accept": "application/json"}
NOW = datetime.utcnow()
THIS_YEAR = NOW.year


# ─────────────────────────────────────────────
# 1. NY Fed - SOFR (무료, 인증 불필요)
# ─────────────────────────────────────────────
def fetch_sofr():
    """최근 60일 SOFR + 최신 값"""
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
# 2. FRED - SOFR 장기 히스토리 (무료, API키 필요)
# ─────────────────────────────────────────────
def fetch_fred_sofr():
    """최근 1년 SOFR (FRED API 키가 있을 때만)"""
    api_key = os.environ.get("FRED_API_KEY", "")
    if not api_key:
        print("[2/4] FRED ⏭️  (FRED_API_KEY 미설정 - 선택사항)")
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
# 3. Polymarket - 동적 Fed 마켓 탐색 (무료, 인증 불필요)
# ─────────────────────────────────────────────
def fetch_polymarket():
    """
    Polymarket에서 '현재 활성 상태'인 Fed 관련 마켓을 모두 수집합니다.
    하드코딩된 슬러그/연도 없이, 태그 검색 + 키워드 검색으로 자동 탐색합니다.
    """
    print("[3/4] Polymarket ...")
    BASE = "https://gamma-api.polymarket.com"
    results = {"fomc_decisions": [], "other_markets": []}

    # ── 3a. 태그 기반 검색: 활성 Fed 마켓 전부 가져오기 ──
    active_events = {}  # slug → event (중복 제거)

    for tag in ["fed-rates", "fed", "federal-reserve", "interest-rates"]:
        try:
            r = requests.get(
                f"{BASE}/events",
                params={"tag": tag, "active": "true", "closed": "false", "limit": "50"},
                headers=HEADERS, timeout=TIMEOUT,
            )
            if r.status_code == 200:
                for ev in r.json():
                    slug = ev.get("slug", "")
                    if slug and slug not in active_events:
                        active_events[slug] = ev
        except:
            pass

    # ── 3b. 키워드 검색으로 추가 탐색 ──
    for q in ["fed decision", "fed rate", "fomc", "rate cut", "rate hike"]:
        try:
            r = requests.get(
                f"{BASE}/events",
                params={"tag": q, "active": "true", "closed": "false", "limit": "20"},
                headers=HEADERS, timeout=TIMEOUT,
            )
            if r.status_code == 200:
                for ev in r.json():
                    slug = ev.get("slug", "")
                    if slug and slug not in active_events:
                        active_events[slug] = ev
        except:
            pass

    # ── 3c. 각 이벤트 파싱 ──
    for slug, ev in active_events.items():
        title = ev.get("title", "")
        title_lower = title.lower()
        markets_raw = ev.get("markets", [])

        parsed_markets = []
        for m in markets_raw:
            try:
                outcomes = json.loads(m.get("outcomes", "[]"))
                prices = json.loads(m.get("outcomePrices", "[]"))
            except:
                outcomes, prices = [], []

            parsed_markets.append({
                "question": m.get("question", ""),
                "groupItemTitle": m.get("groupItemTitle", ""),
                "outcomes": outcomes,
                "prices": [float(p) for p in prices] if prices else [],
                "volume": float(m.get("volume", 0) or 0),
                "liquidity": float(m.get("liquidity", 0) or 0),
            })

        event_obj = {
            "slug": slug,
            "title": title,
            "endDate": ev.get("endDate", ""),
            "markets": parsed_markets,
        }

        # FOMC 개별 미팅 결정인지 판단
        is_fomc = any(kw in title_lower for kw in [
            "fed decision in", "fed decision", "fomc",
            "interest rate", "rate decision",
        ]) and any(kw in title_lower for kw in [
            "january", "february", "march", "april", "may", "june",
            "july", "august", "september", "october", "november", "december",
        ])

        if is_fomc:
            results["fomc_decisions"].append(event_obj)
        else:
            results["other_markets"].append(event_obj)

    # 종료일 기준 정렬
    results["fomc_decisions"].sort(key=lambda x: x.get("endDate", ""))
    results["other_markets"].sort(key=lambda x: x.get("endDate", ""))

    total = len(results["fomc_decisions"]) + len(results["other_markets"])
    print(f"  ✅ FOMC 결정: {len(results['fomc_decisions'])}개, 기타: {len(results['other_markets'])}개")
    return results


# ─────────────────────────────────────────────
# 4. Kalshi - 동적 Fed 마켓 탐색 (무료, 인증 불필요)
# ─────────────────────────────────────────────
def fetch_kalshi():
    """
    Kalshi에서 Fed 관련 활성 마켓을 자동으로 탐색합니다.
    시리즈 티커를 검색해서 현재 열려있는 마켓만 수집합니다.
    """
    print("[4/4] Kalshi ...")
    BASE = "https://api.elections.kalshi.com/trade-api/v2"
    results = []

    # ── 4a. Fed 관련 시리즈 자동 탐색 ──
    # 먼저 알려진 Fed 시리즈 확인 + 동적 검색
    known_prefixes = [
        "KXFEDDECISION", "KXFED", "KXRATECUTCOUNT",
        "KXLARGECUT", "KXFEDCOMBO",
    ]

    discovered_tickers = set(known_prefixes)

    # 이벤트 검색으로 추가 시리즈 발견
    for query in ["fed", "fomc", "interest rate", "rate cut"]:
        try:
            r = requests.get(
                f"{BASE}/events",
                params={"status": "open", "limit": "50",
                        "series_ticker": "", "with_nested_markets": "true"},
                headers=HEADERS, timeout=TIMEOUT,
            )
            if r.status_code == 200:
                for ev in r.json().get("events", []):
                    st = ev.get("series_ticker", "")
                    title = (ev.get("title", "") + ev.get("sub_title", "")).lower()
                    if st and any(kw in title for kw in ["fed", "fomc", "rate cut", "rate hike", "funds rate"]):
                        discovered_tickers.add(st)
        except:
            pass

    # ── 4b. 각 시리즈에서 열린 마켓 수집 ──
    for ticker in discovered_tickers:
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

            series_obj = {
                "series_ticker": ticker,
                "markets": [],
            }

            for m in markets_raw:
                series_obj["markets"].append({
                    "ticker": m.get("ticker", ""),
                    "title": m.get("title", ""),
                    "subtitle": m.get("subtitle", ""),
                    "yes_bid": m.get("yes_bid"),
                    "yes_ask": m.get("yes_ask"),
                    "no_bid": m.get("no_bid"),
                    "no_ask": m.get("no_ask"),
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


# ─────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────
def main():
    print("=" * 55)
    print("🏦 Fed Rate Dashboard - Data Fetcher")
    print(f"📅 {NOW.strftime('%Y-%m-%d %H:%M UTC')}")
    print("=" * 55)

    output = {
        "meta": {
            "updated_at": NOW.isoformat() + "Z",
            "year": THIS_YEAR,
            "note": "All data from free public APIs. No hardcoded years.",
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
    print(f"   SOFR: {len(output['sofr'])}일")
    pm = output["polymarket"]
    print(f"   Polymarket: FOMC {len(pm['fomc_decisions'])}개 + 기타 {len(pm['other_markets'])}개")
    print(f"   Kalshi: {len(output['kalshi'])}개 시리즈")


if __name__ == "__main__":
    main()
