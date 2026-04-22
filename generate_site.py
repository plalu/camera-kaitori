# -*- coding: utf-8 -*-
"""
data/prices.json を読み込み docs/index.html を生成する
使い方: python generate_site.py
"""

import io
import json
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

if sys.stdout.encoding != "utf-8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

JST = timezone(timedelta(hours=9))
BASE_DIR = Path(__file__).parent
DATA_FILE = BASE_DIR / "data" / "prices.json"
DOCS_DIR = BASE_DIR / "docs"
OUTPUT_FILE = DOCS_DIR / "index.html"

SITE_CONFIG = {
    "買取wiki":   {"color": "#0071e3", "url": "https://camerakaitori.tokyo/"},
    "家電市場":   {"color": "#e0722f", "url": "https://www.kaden-ichiba.com/item"},
    "買取１丁目": {"color": "#1d8a47", "url": "https://www.1-chome.com/electricAppliance?category=10000001"},
}


def fmt_dt(s: str) -> str:
    if not s:
        return "—"
    try:
        dt = datetime.fromisoformat(s)
        return dt.strftime("%Y/%m/%d %H:%M")
    except Exception:
        return s


def fmt_price(p) -> str:
    if p is None:
        return "—"
    return f"¥{int(p):,}"


def price_bar(price: int, max_price: int) -> str:
    if not price or not max_price:
        return ""
    pct = min(100, round(price / max_price * 100))
    return f'<div class="bar" style="width:{pct}%"></div>'


def generate(data: dict) -> str:
    updated = fmt_dt(data.get("updated_at", ""))
    products = data.get("products", {})

    product_cards = ""
    for jan, entry in products.items():
        prices = entry.get("prices", {})
        valid_prices = [(s, r["price"]) for s, r in prices.items() if r.get("price")]
        max_price = max((p for _, p in valid_prices), default=0)
        best_site = max(valid_prices, key=lambda x: x[1])[0] if valid_prices else None

        rows = ""
        for site_name, cfg in SITE_CONFIG.items():
            record = prices.get(site_name, {})
            price = record.get("price")
            url = record.get("url", cfg["url"])
            note = record.get("note", "")
            is_best = site_name == best_site

            price_cell = (
                f'<a href="{url}" target="_blank" rel="noopener" class="price-link{"  best" if is_best else ""}">'
                f'{fmt_price(price)}'
                f'{"  <span class=\"best-badge\">最高値</span>" if is_best else ""}'
                f'</a>'
                if price else
                f'<span class="no-price">{note or "—"}</span>'
            )
            bar_cell = price_bar(price, max_price) if price else ""

            rows += f"""
        <tr>
          <td class="site-name" style="border-left:3px solid {cfg['color']}">{site_name}</td>
          <td class="price-cell">{price_cell}</td>
          <td class="bar-cell">{bar_cell}</td>
        </tr>"""

        history = entry.get("history", [])
        trend_html = ""
        if len(history) >= 2:
            prev = history[-2]["prices"]
            curr = history[-1]["prices"]
            diffs = []
            for s in SITE_CONFIG:
                p, c = prev.get(s), curr.get(s)
                if p and c:
                    diffs.append(c - p)
            if diffs:
                avg = sum(diffs) // len(diffs)
                if avg > 0:
                    trend_html = f'<span class="trend up">▲ ¥{avg:,}</span>'
                elif avg < 0:
                    trend_html = f'<span class="trend down">▼ ¥{abs(avg):,}</span>'

        product_cards += f"""
  <div class="card">
    <div class="card-header">
      <div>
        <div class="product-name">{entry['name']}</div>
        <div class="product-meta">JAN: {jan} &nbsp;|&nbsp; {entry.get('brand', '')} {entry.get('model', '')}</div>
      </div>
      {trend_html}
    </div>
    <table class="price-table">
      <tbody>{rows}
      </tbody>
    </table>
  </div>"""

    return f"""<!DOCTYPE html>
<html lang="ja">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>カメラ買取価格比較</title>
  <style>
    *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{
      font-family: -apple-system, BlinkMacSystemFont, "Helvetica Neue", "Noto Sans JP", sans-serif;
      background: #f5f5f7;
      color: #1d1d1f;
      min-height: 100vh;
    }}
    header {{
      background: #1d1d1f;
      color: #fff;
      padding: 20px 24px;
      display: flex;
      align-items: center;
      justify-content: space-between;
      flex-wrap: wrap;
      gap: 8px;
    }}
    header h1 {{ font-size: 1.15rem; font-weight: 700; letter-spacing: -.01em; }}
    .updated {{ font-size: 0.75rem; color: #a1a1a6; }}
    main {{ max-width: 860px; margin: 0 auto; padding: 28px 16px; display: flex; flex-direction: column; gap: 20px; }}
    .card {{
      background: #fff;
      border-radius: 14px;
      box-shadow: 0 1px 4px rgba(0,0,0,.08);
      overflow: hidden;
    }}
    .card-header {{
      padding: 16px 20px 12px;
      display: flex;
      justify-content: space-between;
      align-items: flex-start;
      border-bottom: 1px solid #f0f0f0;
    }}
    .product-name {{ font-size: 1rem; font-weight: 700; }}
    .product-meta {{ font-size: 0.72rem; color: #6e6e73; margin-top: 4px; font-family: monospace; }}
    .trend {{ font-size: 0.75rem; font-weight: 600; padding: 3px 8px; border-radius: 6px; white-space: nowrap; }}
    .trend.up {{ background: #d1f0da; color: #1a7f37; }}
    .trend.down {{ background: #fbeae5; color: #b3321c; }}
    .price-table {{ width: 100%; border-collapse: collapse; }}
    .price-table td {{ padding: 10px 20px; vertical-align: middle; }}
    .price-table tr + tr {{ border-top: 1px solid #f5f5f7; }}
    .site-name {{ font-size: 0.82rem; font-weight: 600; width: 110px; color: #3a3a3c; }}
    .price-cell {{ width: 160px; }}
    .price-link {{
      font-size: 1rem;
      font-weight: 700;
      color: #1d1d1f;
      text-decoration: none;
      display: flex;
      align-items: center;
      gap: 6px;
    }}
    .price-link:hover {{ color: #0071e3; }}
    .price-link.best {{ color: #1a7f37; }}
    .best-badge {{
      font-size: 0.65rem;
      font-weight: 600;
      background: #d1f0da;
      color: #1a7f37;
      padding: 2px 6px;
      border-radius: 4px;
    }}
    .no-price {{ font-size: 0.85rem; color: #a1a1a6; }}
    .bar-cell {{ padding-left: 8px; }}
    .bar {{
      height: 6px;
      background: #0071e3;
      border-radius: 3px;
      opacity: 0.25;
      min-width: 4px;
    }}
    footer {{
      text-align: center;
      padding: 28px 16px;
      font-size: 0.75rem;
      color: #a1a1a6;
    }}
    footer a {{ color: #a1a1a6; }}
  </style>
</head>
<body>
  <header>
    <h1>カメラ買取価格比較</h1>
    <span class="updated">最終更新: {updated}</span>
  </header>
  <main>
    {product_cards}
  </main>
  <footer>
    参照サイト:
    <a href="https://camerakaitori.tokyo/" target="_blank">買取wiki</a> /
    <a href="https://www.kaden-ichiba.com/item" target="_blank">家電市場</a> /
    <a href="https://www.1-chome.com/" target="_blank">買取１丁目</a>
    &nbsp;|&nbsp; 自動更新: 6時間ごと
  </footer>
</body>
</html>"""


def main():
    if not DATA_FILE.exists():
        print("データファイルがありません。先に scraper.py を実行してください。", file=sys.stderr)
        sys.exit(1)

    with open(DATA_FILE, encoding="utf-8") as f:
        data = json.load(f)

    DOCS_DIR.mkdir(exist_ok=True)
    html = generate(data)
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"生成完了: {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
