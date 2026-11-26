"""One-command operator setup for Cloudflare Web Analytics ($0/mo, cookie-free)
and instant Stripe Payment Links / Ko-fi URLs in config/patrons.json.

Examples:
  # Add Cloudflare Web Analytics beacon to public/index.html & public/embed.html
  python scripts/configure_growth.py --cf-token "YOUR_CLOUDFLARE_BEACON_TOKEN"

  # Configure instant Stripe Payment Links or Ko-fi URLs
  python scripts/configure_growth.py --link-5 "https://ko-fi.com/..." --link-business "https://buy.stripe.com/..."
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
CF_TAG_RE = re.compile(r"\s*<!-- Cloudflare Web Analytics -->.*?<!-- End Cloudflare Web Analytics -->\s*", re.DOTALL)


def inject_cloudflare_analytics(html_path: Path, token: str) -> bool:
    if not html_path.exists():
        return False
    src = html_path.read_text(encoding="utf-8")
    src = CF_TAG_RE.sub("\n", src)
    snippet = (
        "\n  <!-- Cloudflare Web Analytics -->\n"
        f'  <script defer src="https://static.cloudflareinsights.com/beacon.min.js" data-cf-beacon=\'{{"token": "{token}"}}\'></script>\n'
        "  <!-- End Cloudflare Web Analytics -->\n"
    )
    if "</body>" not in src:
        return False
    html_path.write_text(src.replace("</body>", snippet + "</body>", 1), encoding="utf-8")
    return True


def update_payment_links(cfg_path: Path, updates: dict) -> dict:
    if cfg_path.exists():
        data = json.loads(cfg_path.read_text(encoding="utf-8"))
    else:
        data = {
            "disclosure": (
                "CivicPulse is an independent civic technology project, not a registered 501(c)(3) "
                "nonprofit. Voluntary contributions and sponsorships are not tax-deductible."
            ),
            "checkout_links": {},
            "patrons": [],
        }
    links = data.setdefault("checkout_links", {})
    for k, v in updates.items():
        if v:
            links[k] = v.strip()
    cfg_path.parent.mkdir(parents=True, exist_ok=True)
    cfg_path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return data


def main() -> None:
    parser = argparse.ArgumentParser(description="Configure Cloudflare Web Analytics and Patron Checkout Links.")
    parser.add_argument("--cf-token", default="", help="Cloudflare Web Analytics beacon token")
    parser.add_argument("--link-5", default="", help="Payment link for $5 supporter")
    parser.add_argument("--link-15", default="", help="Payment link for $15 supporter")
    parser.add_argument("--link-50", default="", help="Payment link for $50 champion")
    parser.add_argument("--link-business", default="", help="Payment link for Business Patron")
    parser.add_argument("--link-sponsor", default="", help="Payment link for Priority City Sponsor")
    args = parser.parse_args()

    if args.cf_token:
        for rel in ("public/index.html", "public/embed.html"):
            if inject_cloudflare_analytics(REPO_ROOT / rel, args.cf_token.strip()):
                print(f"[ANALYTICS] Injected Cloudflare Web Analytics beacon into {rel}")

    updates = {
        "individual_5": args.link_5,
        "individual_15": args.link_15,
        "individual_50": args.link_50,
        "business_patron_monthly": args.link_business,
        "city_onboarding_sponsor": args.link_sponsor,
    }
    if any(updates.values()):
        cfg_p = REPO_ROOT / "config" / "patrons.json"
        data = update_payment_links(cfg_p, updates)
        pub_p = REPO_ROOT / "public" / "data" / "patrons.json"
        pub_p.parent.mkdir(parents=True, exist_ok=True)
        pub_p.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        print("[PATRONS] Updated config/patrons.json and public/data/patrons.json")


if __name__ == "__main__":
    main()
