"""Configure Cloudflare Web Analytics, Weekly Email Digest & Support Payment Links."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

CFG_PATH = Path("public/data/site_config.json")


def main() -> None:
    parser = argparse.ArgumentParser(description="Update public/data/site_config.json for analytics, digest & payment links")
    parser.add_argument("--analytics-token", help="Cloudflare Web Analytics beacon token (free)")
    parser.add_argument("--digest-url", help="Weekly RSS-to-Email signup URL (e.g. Buttondown or Follow.it)")
    parser.add_argument("--coffee-url", help="1-click payment link for $5 Coffee (Stripe / Ko-fi)")
    parser.add_argument("--supporter-url", help="1-click payment link for $15 Supporter (Stripe / Ko-fi)")
    parser.add_argument("--patron-url", help="1-click payment link for Business Patron")
    args = parser.parse_args()

    cfg = json.loads(CFG_PATH.read_text(encoding="utf-8")) if CFG_PATH.exists() else {"support_links": {}}
    if args.analytics_token is not None:
        cfg["cloudflare_analytics_token"] = args.analytics_token.strip()
    if args.digest_url is not None:
        cfg["weekly_digest_url"] = args.digest_url.strip()
    if args.coffee_url:
        cfg.setdefault("support_links", {})["coffee_5"] = args.coffee_url.strip()
    if args.supporter_url:
        cfg.setdefault("support_links", {})["supporter_15"] = args.supporter_url.strip()
    if args.patron_url:
        cfg.setdefault("support_links", {})["patron"] = args.patron_url.strip()

    CFG_PATH.parent.mkdir(parents=True, exist_ok=True)
    CFG_PATH.write_text(json.dumps(cfg, indent=2) + "\n", encoding="utf-8")
    print("[SITE-CONFIG] Updated", CFG_PATH)
    print(json.dumps(cfg, indent=2))


if __name__ == "__main__":
    main()
