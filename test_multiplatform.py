import time
import xml.etree.ElementTree as ET
import requests

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
    "Accept": "application/json, application/xml, text/html;q=0.9,*/*;q=0.8",
}


def test_legistar(client: str, label: str) -> dict:
    url = f"https://webapi.legistar.com/v1/{client}/events?$top=5&$orderby=EventDate desc"
    r = requests.get(url, headers=HEADERS, timeout=15)
    r.raise_for_status()
    items = r.json()
    return {
        "platform": "Legistar REST API",
        "city": label,
        "status": "PASS",
        "records": len(items),
        "sample": items[0].get("EventBodyName", "") if items else "None",
        "mode": "Structured Roll-Call JSON (No GPU)",
    }


def test_civicclerk(tenant: str, label: str) -> dict:
    url = f"https://{tenant}.api.civicclerk.com/v1/Events?$top=5&$orderby=startDateTime desc"
    r = requests.get(url, headers=HEADERS, timeout=15)
    r.raise_for_status()
    items = r.json().get("value", [])
    return {
        "platform": "CivicClerk OData API",
        "city": label,
        "status": "PASS",
        "records": len(items),
        "sample": items[0].get("eventName", "") if items else "None",
        "mode": "PDF Minutes/Agenda -> Ollama Worker",
    }


def test_primegov(subdomain: str, label: str) -> dict:
    # PrimeGov v2 PublicPortal requires ?year=YYYY query parameter
    url = f"https://{subdomain}.primegov.com/api/v2/PublicPortal/ListArchivedMeetings?year=2026"
    r = requests.get(url, headers=HEADERS, timeout=15)
    r.raise_for_status()
    items = r.json()
    return {
        "platform": "PrimeGov Portal API",
        "city": label,
        "status": "PASS",
        "records": len(items),
        "sample": items[0].get("title", "") if items else "None",
        "mode": "PDF Minutes/HTML -> Ollama Worker",
    }


def test_civicplus_rss(rss_url: str, label: str) -> dict:
    r = requests.get(rss_url, headers=HEADERS, timeout=15)
    r.raise_for_status()
    root = ET.fromstring(r.text)
    items = root.findall(".//item")
    first_title = items[0].findtext("title", default="") if items else "None"
    return {
        "platform": "CivicPlus AgendaCenter RSS",
        "city": label,
        "status": "PASS",
        "records": len(items),
        "sample": first_title.strip(),
        "mode": "RSS XML + PDF -> Ollama Worker",
    }


def run_benchmark() -> None:
    tests = [
        # Tier 1: Large Metro Cities
        (test_legistar, ("denver", "Denver, CO (Large Metro)")),
        (test_legistar, ("coloradosprings", "Colorado Springs, CO (Large Metro)")),
        (test_primegov, ("sanjoseca", "San Jose, CA (Large Metro - PrimeGov)")),
        # Tier 2: Mid-Sized / University Cities
        (test_civicclerk, ("fortcollinsco", "Fort Collins, CO (Mid-Size)")),
        (test_civicclerk, ("greeleyco", "Greeley, CO (Mid-Size)")),
        (test_primegov, ("bouldercolorado", "Boulder, CO (Mid-Size - PrimeGov)")),
        # Tier 3: Smaller / Regional Towns
        (test_civicclerk, ("windsorgov", "Windsor, CO (Town - CivicClerk)")),
        (test_civicplus_rss, ("https://www.lovgov.org/RSSFeed.aspx?ModID=65&CID=All-agenda.xml", "Loveland, CO (WAF Check)")),
    ]

    print("=" * 84)
    print("  CivicPulse Multi-Platform & Diverse-Municipality Benchmark")
    print("=" * 84)

    passed = 0
    for fn, args in tests:
        try:
            res = fn(*args)
            passed += 1
            print(f"[PASS] {res['platform']:28s} | {res['city']:34s} | {res['records']:3d} items")
            print(f"       Sample: {res['sample'][:72]}")
        except Exception as exc:
            print(f"[FAIL] {fn.__name__:28s} | {args[-1]:34s} | {exc}")
        time.sleep(0.5)

    print("=" * 84)
    print(f"Result: {passed}/{len(tests)} endpoints verified.")


if __name__ == "__main__":
    run_benchmark()
