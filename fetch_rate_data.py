#!/usr/bin/env python3
"""
Fed Rate Dashboard - 데이터 수집기 v2.3
========================================
핵심 변경: FOMC 캘린더를 뼈대로 사용 → Polymarket 확률을 매칭
- FOMC 일정은 연준 웹사이트에서 가져오거나, 공식 발표 기반으로 생성
- Polymarket/Kalshi 데이터를 캘린더에 매핑
- 과거 이벤트 필터링 강화 (올해 + 다음해만)
"""

import json
import requests
import re
import os
from datetime import datetime, timedelta

TIMEOUT = 15
HEADERS = {"User-Agent": "FedRateDashboard/2.3", "Accept": "application/json"}
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
MONTH_NUM_KO = {1:"1월",2:"2월",3:"3월",4:"4월",5:"5월",6:"6월",
                7:"7월",8:"8월",9:"9월",10:"10월",11:"11월",12:"12월"}


# ─────────────────────────────────────────────
# FOMC 캘린더 (연준 공식 발표 기반)
# ─────────────────────────────────────────────
def fetch_fomc_calendar():
    """
    연준 웹사이트에서 FOMC 일정을 가져옵니다.
    실패 시 알려진 패턴으로 생성합니다.
    
    반환: [{"date": "2026-03-18", "month": 3, "year": 2026, "label": "3월"}, ...]
    """
    print("[0/4] FOMC 캘린더 ...")
    
    calendar = []
    
    # 방법 1: 연준 캘린더 페이지에서 파싱 시도
    try:
        url = "https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm"
        r = requests.get(url, headers={
            "User-Agent": "Mozilla/5.0 (compatible; FedRateDashboard/2.3)",
            "Accept": "text/html",
        }, timeout=TIMEOUT)
        if r.status_code == 200:
            html = r.text
            # FOMC 날짜 패턴: "March 18-19" 또는 "January 28-29*"
            # 연도별 섹션에서 추출
            import re as regex
            
            # 연도 섹션 찾기
            for year in [THIS_YEAR, THIS_YEAR + 1]:
                year_str = str(year)
                # 해당 연도 섹션의 날짜들 추출
                # 패턴: "Month DD-DD" (FOMC는 보통 2일)
                month_names = {
                    "January":1,"February":2,"March":3,"April":4,"May":5,"June":6,
                    "July":7,"August":8,"September":9,"October":10,"November":11,"December":12
                }
                for mname, mnum in month_names.items():
                    # "March 18-19" 패턴
                    pattern = rf'{mname}\s+(\d{{1,2}})\s*[-–]\s*(\d{{1,2}})'
                    matches = regex.findall(pattern, html)
                    for start_day, end_day in matches:
                        # 연도 결정: html 구조에서 가장 가까운 연도
                        date_str = f"{year}-{mnum:02d}-{int(start_day):02d}"
                        # 중복 방지
                        if not any(c["date"] == date_str for c in calendar):
                            calendar.append({
                                "date": date_str,
                                "month": mnum,
                                "year": year,
                                "label": f"{MONTH_NUM_KO[mnum]}",
                                "end_day": int(end_day),
                            })
    except Exception as e:
        print(f"  ⚠️ 연준 캘린더 파싱 실패: {e}")
    
    # 방법 2: 알려진 FOMC 일정 (공식 발표 기반)
    # FOMC는 매년 8회 회의. 연초에 전체 일정을 발표함.
    # 2025-2026 일정은 이미 발표됨.
    known_dates = {
        2025: [
            (1, 28, 29), (3, 18, 19), (5, 6, 7), (6, 17, 18),
            (7, 29, 30), (9, 16, 17), (10, 28, 29), (12, 9, 10),
        ],
        2026: [
            (1, 27, 28), (3, 17, 18), (5, 5, 6), (6, 16, 17),
            (7, 28, 29), (9, 15, 16), (10, 27, 28), (12, 8, 9),
        ],
    }
    
    # 캘린더가 비어있거나 부족하면 알려진 일정으로 보충
    for year in [THIS_YEAR, THIS_YEAR + 1]:
        if year in known_dates:
            for month, start, end in known_dates[year]:
                date_str = f"{year}-{month:02d}-{start:02d}"
                if not any(c["date"] == date_str for c in calendar):
                    calendar.append({
                        "date": date_str,
                        "month": month,
                        "year": year,
                        "label": MONTH_NUM_KO[month],
                        "end_day": end,
                    })
    
    # 정렬
    calendar.sort(key=lambda x: x["date"])
    
    # 과거 완료 / 미래 상태 표시
    today = NOW.strftime("%Y-%m-%d")
    for item in calendar:
        end_date = f"{item['year']}-{item['month']:02d}-{item['end_day']:02d}"
        item["is_past"] = end_date < today
    
    print(f"  ✅ {len(calendar)}개 FOMC 미팅 (올해+다음해)")
    return calendar


# ─────────────────────────────────────────────
# 한글 번역
# ─────────────────────────────────────────────
def translate_title(title):
    t = title
    # 전체 문장 패턴 먼저
    t = re.sub(r"(?i)will no rate cuts? happen in (\d{4})\??",
               lambda m: f"{m.group(1)}년 금리 인하 0회 여부", t)
    t = re.sub(r"(?i)will (\d+) or more rate cuts? happen in (\d{4})\??",
               lambda m: f"{m.group(2)}년 {m.group(1)}회 이상 금리 인하 여부", t)
    t = re.sub(r"(?i)will fewer than (\d+) rate cuts? happen in (\d{4})\??",
               lambda m: f"{m.group(2)}년 {m.group(1)}회 미만 금리 인하 여부", t)
    t = re.sub(r"(?i)will at least (\d+) rate cuts? happen in (\d{4})\??",
               lambda m: f"{m.group(2)}년 최소 {m.group(1)}회 금리 인하 여부", t)
    t = re.sub(r"(?i)will (\d+) rate cuts? happen in (\d{4})\??",
               lambda m: f"{m.group(2)}년 {m.group(1)}회 금리 인하 여부", t)
    t = re.sub(r"(?i)how many (fed )?rate cuts? (in |)(\d{4})\??",
               lambda m: f"{m.group(3)}년 Fed 금리 인하 횟수", t)
    t = re.sub(r"(?i)number of (fed )?rate cuts?.*?(\d{4})",
               lambda m: f"{m.group(2)}년 금리 인하 횟수", t)
    for eng, ko in MONTH_KO.items():
        t = re.sub(rf"(?i)Fed [Dd]ecision in {eng}\??", f"{ko} FOMC 금리 결정", t)
    t = re.sub(r"(?i)what will the fed (funds )?rate be at the end of (\d{4})\??",
               lambda m: f"{m.group(2)}년 말 Fed 기준금리 전망", t)
    t = re.sub(r"(?i)fed funds rate (?:at )?(?:the )?end of (\d{4})",
               lambda m: f"{m.group(1)}년 말 기준금리", t)
    t = re.sub(r"(?i)will the fed (?:raise|hike) rates?.*?(\d{4})\??",
               lambda m: f"{m.group(2)}년 Fed 금리 인상 여부", t)
    t = re.sub(r"(?i)will the fed cut rates?.*?(\d{4})\??",
               lambda m: f"{m.group(2)}년 Fed 금리 인하 여부", t)
    t = re.sub(r"(?i)will there be a recession.*?(\d{4})\??",
               lambda m: f"{m.group(1)}년 경기 침체 여부", t)
    return t


def translate_outcome(outcome):
    o = outcome.strip()
    mappings = {
        "Yes":"예","No":"아니오","No change":"동결",
        "25 bps decrease":"25bp 인하","25 bps cut":"25bp 인하",
        "50 bps decrease":"50bp 인하","50 bps cut":"50bp 인하",
        "75 bps decrease":"75bp 인하","100 bps decrease":"100bp 인하",
        "25 bps increase":"25bp 인상","50 bps increase":"50bp 인상",
        "Increase":"인상","Decrease":"인하",
    }
    if o in mappings: return mappings[o]
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


FED_KEYWORDS = [
    "fed ", "fomc", "federal reserve", "fed funds", "rate cut", "rate hike",
    "interest rate", "monetary policy", "basis point", "bps",
    "rate decision", "fed decision",
]
def is_fed_related(title):
    return any(kw in title.lower() for kw in FED_KEYWORDS)


# ─────────────────────────────────────────────
# 1. NY Fed - SOFR
# ─────────────────────────────────────────────
def fetch_sofr():
    print("[1/4] NY Fed SOFR ...")
    try:
        r = requests.get("https://markets.newyorkfed.org/api/rates/secured/sofr/last/60.json",
                         headers=HEADERS, timeout=TIMEOUT)
        r.raise_for_status()
        data = [{"date":x["effectiveDate"],"rate":float(x["percentRate"])}
                for x in r.json().get("refRates",[]) if x.get("percentRate")]
        data.sort(key=lambda x:x["date"])
        print(f"  ✅ {len(data)}일치")
        return data
    except Exception as e:
        print(f"  ❌ {e}")
        return []


# ─────────────────────────────────────────────
# 2. FRED
# ─────────────────────────────────────────────
def fetch_fred_sofr():
    api_key = os.environ.get("FRED_API_KEY","")
    if not api_key:
        print("[2/4] FRED ⏭️")
        return []
    print("[2/4] FRED SOFR ...")
    start = (NOW-timedelta(days=365)).strftime("%Y-%m-%d")
    try:
        r = requests.get(f"https://api.stlouisfed.org/fred/series/observations"
                         f"?series_id=SOFR&api_key={api_key}&file_type=json&observation_start={start}&sort_order=asc",
                         timeout=TIMEOUT)
        r.raise_for_status()
        data = [{"date":o["date"],"rate":float(o["value"])}
                for o in r.json().get("observations",[]) if o.get("value",".")!="."]
        print(f"  ✅ {len(data)}일치")
        return data
    except Exception as e:
        print(f"  ❌ {e}")
        return []


# ─────────────────────────────────────────────
# 3. Polymarket
# ─────────────────────────────────────────────
def fetch_polymarket():
    print("[3/4] Polymarket ...")
    BASE = "https://gamma-api.polymarket.com"
    seen = set()
    results = {"fomc_decisions":[], "other_markets":[]}

    def try_fetch(params):
        try:
            r = requests.get(f"{BASE}/events", params=params, headers=HEADERS, timeout=TIMEOUT)
            if r.status_code==200:
                d=r.json()
                return d if isinstance(d,list) else [d] if isinstance(d,dict) and d.get("slug") else []
        except: pass
        return []

    def parse_event(ev):
        slug=ev.get("slug","")
        if slug in seen or not slug: return
        seen.add(slug)
        title=ev.get("title","")
        if not is_fed_related(title): return
        
        end_date = ev.get("endDate","")
        # ★ 연도 필터: 올해-1 ~ 다음해까지만
        if end_date:
            try:
                ed = datetime.fromisoformat(end_date.replace("Z",""))
                if ed.year < THIS_YEAR - 1 or ed.year > THIS_YEAR + 1:
                    return
            except: pass

        markets_raw = ev.get("markets",[])
        parsed = []
        for m in markets_raw:
            try: outcomes=json.loads(m.get("outcomes","[]"))
            except: outcomes=[]
            try: prices=json.loads(m.get("outcomePrices","[]"))
            except: prices=[]
            parsed.append({
                "question":translate_title(m.get("question","")),
                "question_en":m.get("question",""),
                "groupItemTitle":translate_title(m.get("groupItemTitle","")),
                "groupItemTitle_en":m.get("groupItemTitle",""),
                "outcomes":[translate_outcome(o) for o in outcomes],
                "outcomes_en":outcomes,
                "prices":[float(p) for p in prices] if prices else [],
                "volume":float(m.get("volume",0) or 0),
                "liquidity":float(m.get("liquidity",0) or 0),
            })

        obj = {
            "slug":slug, "title":title, "title_ko":translate_title(title),
            "endDate":end_date, "closed":ev.get("closed",False),
            "markets":parsed,
        }

        tl=title.lower()
        is_fomc=("fed decision" in tl or "fomc" in tl) and any(mo in tl for mo in MONTHS)
        if is_fomc: results["fomc_decisions"].append(obj)
        else: results["other_markets"].append(obj)

    # A: 슬러그 패턴
    print("  📌 전략A: 슬러그")
    for month in MONTHS:
        for ev in try_fetch({"slug":f"fed-decision-in-{month}"}): parse_event(ev)

    for slug in [f"how-many-fed-rate-cuts-in-{THIS_YEAR}",
                 f"how-many-fed-rate-cuts-in-{THIS_YEAR+1}",
                 f"what-will-the-fed-rate-be-at-the-end-of-{THIS_YEAR}",
                 f"what-will-the-fed-rate-be-at-the-end-of-{THIS_YEAR+1}",
                 "how-many-fed-rate-cuts","what-will-the-fed-rate-be","will-the-fed-raise-rates"]:
        for ev in try_fetch({"slug":slug}): parse_event(ev)

    # B: 태그
    print("  📌 전략B: 태그")
    for tag in ["fed-rates","fed","federal-reserve","interest-rates","fomc"]:
        for ev in try_fetch({"tag":tag,"active":"true","closed":"false","limit":"50"}): parse_event(ev)

    # C: 텍스트
    print("  📌 전략C: 텍스트")
    for q in ["fed rate","fomc","federal reserve",f"rate cut {THIS_YEAR}"]:
        for ev in try_fetch({"title":q,"active":"true","closed":"false","limit":"20"}): parse_event(ev)

    results["fomc_decisions"].sort(key=lambda x:x.get("endDate",""))
    results["other_markets"].sort(key=lambda x:x.get("endDate",""))
    print(f"  ✅ FOMC {len(results['fomc_decisions'])}개, 기타 {len(results['other_markets'])}개")
    return results


# ─────────────────────────────────────────────
# 4. Kalshi
# ─────────────────────────────────────────────
def fetch_kalshi():
    print("[4/4] Kalshi ...")
    BASE = "https://api.elections.kalshi.com/trade-api/v2"
    results = []
    for ticker in ["KXFEDDECISION","KXFED","KXRATECUTCOUNT","KXLARGECUT"]:
        try:
            r = requests.get(f"{BASE}/markets",
                             params={"series_ticker":ticker,"status":"open","limit":"40"},
                             headers=HEADERS, timeout=TIMEOUT)
            if r.status_code!=200: continue
            markets = r.json().get("markets",[])
            if not markets: continue
            series = {"series_ticker":ticker,"markets":[]}
            for m in markets:
                series["markets"].append({
                    "ticker":m.get("ticker",""),
                    "title":m.get("title",""),
                    "title_ko":translate_title(m.get("title","")),
                    "subtitle":m.get("subtitle",""),
                    "subtitle_ko":translate_title(m.get("subtitle","")) if m.get("subtitle") else "",
                    "yes_bid":m.get("yes_bid"), "yes_ask":m.get("yes_ask"),
                    "last_price":m.get("last_price"), "volume":m.get("volume"),
                    "open_interest":m.get("open_interest"),
                    "close_time":m.get("close_time",""),
                    "expiration_time":m.get("expiration_time",""),
                })
            results.append(series)
            print(f"  📊 {ticker}: {len(markets)}개")
        except Exception as e:
            print(f"  ⚠️ {ticker}: {e}")
    print(f"  ✅ {len(results)}개 시리즈")
    return results


def main():
    print("="*55)
    print(f"🏦 Fed Rate Dashboard v2.3 | {NOW.strftime('%Y-%m-%d %H:%M UTC')}")
    print("="*55)

    fomc_calendar = fetch_fomc_calendar()

    output = {
        "meta":{"updated_at":NOW.isoformat()+"Z","year":THIS_YEAR,"version":"2.3"},
        "fomc_calendar": fomc_calendar,
        "sofr": fetch_sofr(),
        "fred_sofr": fetch_fred_sofr(),
        "polymarket": fetch_polymarket(),
        "kalshi": fetch_kalshi(),
    }

    os.makedirs("data", exist_ok=True)
    with open("data/rate_data.json","w",encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    pm = output["polymarket"]
    print(f"\n✅ 저장: data/rate_data.json")
    print(f"   캘린더: {len(fomc_calendar)}개 FOMC")
    print(f"   SOFR: {len(output['sofr'])}일")
    print(f"   Polymarket: FOMC {len(pm['fomc_decisions'])}개 + 기타 {len(pm['other_markets'])}개")
    print(f"   Kalshi: {len(output['kalshi'])}개 시리즈")


if __name__ == "__main__":
    main()
