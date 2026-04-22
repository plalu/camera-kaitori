# -*- coding: utf-8 -*-
"""
カメラ買取価格モニター
対象: 買取wiki, 家電市場, 買取１丁目
使い方: python scraper.py
"""

import asyncio
import io
import json
import logging
import re
import sys
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

import requests
from bs4 import BeautifulSoup
from playwright.async_api import async_playwright

if sys.stdout.encoding != "utf-8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
if sys.stderr.encoding != "utf-8":
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

JST = timezone(timedelta(hours=9))
BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "data"
PRODUCTS_FILE = BASE_DIR / "products.json"
DATA_FILE = DATA_DIR / "prices.json"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "ja,en-US;q=0.9,en;q=0.8",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)

SITES = ["買取wiki", "家電市場", "買取１丁目"]


@dataclass
class Product:
    jan: str
    name: str
    model: str
    brand: str
    keywords: list
    exclude_keywords: list
    price_min: int
    price_max: int


@dataclass
class PriceRecord:
    site_name: str
    price: Optional[int]
    url: str
    fetched_at: str = field(
        default_factory=lambda: datetime.now(JST).strftime("%Y-%m-%dT%H:%M:%S+09:00")
    )
    note: str = ""


def load_products() -> list[Product]:
    with open(PRODUCTS_FILE, encoding="utf-8") as f:
        return [Product(**d) for d in json.load(f)]


def get_soup(url: str, timeout: int = 15) -> Optional[BeautifulSoup]:
    try:
        resp = requests.get(url, headers=HEADERS, timeout=timeout)
        resp.raise_for_status()
        resp.encoding = resp.apparent_encoding
        return BeautifulSoup(resp.text, "html.parser")
    except Exception as e:
        log.warning("GET %s failed: %s", url, e)
        return None


def parse_price(text: str, price_min: int, price_max: int) -> Optional[int]:
    t = text.replace(",", "").replace("，", "")
    candidates = []
    for m in re.finditer(r"[¥￥](\d{4,7})", t):
        candidates.append(int(m.group(1)))
    for m in re.finditer(r"(\d{4,7})円", t):
        candidates.append(int(m.group(1)))
    valid = [p for p in candidates if price_min <= p <= price_max]
    return max(valid) if valid else None


def match_product(text: str, product: Product) -> bool:
    for kw in product.keywords:
        if kw not in text:
            return False
    for ex in product.exclude_keywords:
        if ex in text:
            return False
    return True


# ──────────────────────────────────────────────
# サイト別スクレイパー
# ──────────────────────────────────────────────

def scrape_kaitori_wiki(product: Product) -> PriceRecord:
    """買取wiki (camerakaitori.tokyo) — JANコードで検索"""
    site = "買取wiki"
    search_url = f"https://camerakaitori.tokyo/search?q={product.jan}"
    soup = get_soup(search_url)
    if soup is None:
        return PriceRecord(site_name=site, price=None, url=search_url, note="取得失敗")

    # 検索結果ページ: li.sub-pro-name にJANが含まれる行を探す
    # 構造: ul > div.sub-pro > li.sub-pro-name, ul > li.sub-pro-jia
    items = soup.find_all("li", class_="sub-pro-name")
    for li in items:
        if product.jan in li.get_text():
            # li の親は div.sub-pro → さらに親の ul に sub-pro-jia がある
            ul = li.find_parent("ul")
            if ul:
                price_li = ul.find("li", class_="sub-pro-jia")
                if price_li:
                    span = price_li.find("span")
                    if span:
                        p = parse_price(span.get_text(), product.price_min, product.price_max)
                        if p:
                            a = li.find("a")
                            detail_url = ("https://camerakaitori.tokyo" + a["href"]) if a else search_url
                            return PriceRecord(site_name=site, price=p, url=detail_url)

    # フォールバック: キーワードで商品名マッチ
    for a in soup.find_all("a", href=re.compile(r"/purchase/")):
        if match_product(a.get_text(strip=True), product):
            ul = a.find_parent("ul")
            if ul:
                price_li = ul.find("li", class_="sub-pro-jia")
                if price_li:
                    span = price_li.find("span")
                    if span:
                        p = parse_price(span.get_text(), product.price_min, product.price_max)
                        if p:
                            return PriceRecord(
                                site_name=site, price=p,
                                url="https://camerakaitori.tokyo" + a["href"]
                            )

    return PriceRecord(site_name=site, price=None, url=search_url, note="商品が見つかりません")


def scrape_kaden_ichiba(product: Product) -> PriceRecord:
    """家電市場 — tr[id^='row-data-'] からJAN/キーワードでマッチ"""
    site = "家電市場"
    base_url = "https://www.kaden-ichiba.com/item/node/0049/%E3%83%87%E3%82%B8%E3%82%BF%E3%83%AB%E4%B8%80%E7%9C%BC%E3%82%AB%E3%83%A1%E3%83%A9"

    for page in range(1, 10):
        url = f"{base_url}?node=0049&page={page}" if page > 1 else base_url
        soup = get_soup(url)
        if soup is None:
            break

        # 実際の構造: tr[id^="row-data-"]
        rows = soup.select("tr[id^='row-data-']")
        if not rows:
            break

        for row in rows:
            cells = row.find_all("td")
            if len(cells) < 4:
                continue

            # cells[2]: 商品名＋JAN(span[id^="ean-area-"] > small)
            name_cell = cells[2]
            ean_span = name_cell.find("span", id=re.compile(r"^ean-area-"))
            jan_text = ean_span.find("small").get_text(strip=True) if ean_span and ean_span.find("small") else ""
            name_text = name_cell.get_text(strip=True)

            if product.jan not in jan_text and not match_product(name_text, product):
                continue

            # cells[3]=プライム, [4]=新品, [5]=中古 の順に試す
            for idx in [5, 4, 3]:
                if len(cells) > idx:
                    p = parse_price(cells[idx].get_text(strip=True), product.price_min, product.price_max)
                    if p:
                        return PriceRecord(site_name=site, price=p, url=url)

        if not soup.select_one("a[rel='next'], .page-item.active + .page-item a"):
            break

    return PriceRecord(site_name=site, price=None, url=base_url, note="商品が見つかりません")


async def scrape_ichidome_async(product: Product, browser) -> PriceRecord:
    """買取１丁目 — React SPA なので Playwright で取得"""
    site = "買取１丁目"
    url = "https://www.1-chome.com/electricAppliance?category=10000001"
    context = await browser.new_context(locale="ja-JP")
    page = await context.new_page()
    try:
        await page.goto(url, wait_until="networkidle", timeout=30000)
        await page.wait_for_timeout(3000)

        js_keywords = json.dumps(product.keywords)
        js_excludes = json.dumps(product.exclude_keywords)
        result = await page.evaluate(f"""
        () => {{
            const jan = "{product.jan}";
            const keywords = {js_keywords};
            const excludes = {js_excludes};
            const priceMin = {product.price_min};
            const priceMax = {product.price_max};

            const matchText = (t) => {{
                if (!keywords.every(k => t.includes(k))) return false;
                if (excludes.some(e => t.includes(e))) return false;
                return true;
            }};

            // 各商品カード div.commodity-item を検索
            const items = document.querySelectorAll('.commodity-item');
            for (const item of items) {{
                const text = item.textContent || "";
                if (!text.includes(jan) && !matchText(text)) continue;

                // span.text-right.text-sm から最高値（印なし）を取得
                const spans = item.querySelectorAll('span.text-right.text-sm');
                const prices = [...spans].map(s => {{
                    const m = s.textContent.match(/[¥￥]([\\d,]+)/);
                    return m ? parseInt(m[1].replace(/,/g, '')) : 0;
                }}).filter(p => p >= priceMin && p <= priceMax);

                if (prices.length > 0) return Math.max(...prices);
            }}
            return null;
        }}
        """)
        if result:
            return PriceRecord(site_name=site, price=int(result), url=url)
        return PriceRecord(site_name=site, price=None, url=url, note="商品が見つかりません")
    except Exception as e:
        return PriceRecord(site_name=site, price=None, url=url, note=f"エラー: {e}")
    finally:
        await context.close()


# ──────────────────────────────────────────────
# データ管理
# ──────────────────────────────────────────────

def load_data() -> dict:
    if DATA_FILE.exists():
        with open(DATA_FILE, encoding="utf-8") as f:
            return json.load(f)
    return {"updated_at": "", "products": {}}


def save_data(data: dict) -> None:
    DATA_DIR.mkdir(exist_ok=True)
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def now_jst() -> str:
    return datetime.now(JST).strftime("%Y-%m-%dT%H:%M:%S+09:00")


# ──────────────────────────────────────────────
# メイン
# ──────────────────────────────────────────────

async def main():
    products = load_products()
    data = load_data()
    timestamp = now_jst()

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)

        for product in products:
            log.info("=== %s (JAN: %s) ===", product.name, product.jan)
            if product.jan not in data["products"]:
                data["products"][product.jan] = {
                    "jan": product.jan,
                    "name": product.name,
                    "model": product.model,
                    "brand": product.brand,
                    "prices": {},
                    "history": [],
                }

            entry = data["products"][product.jan]
            snapshot = {"timestamp": timestamp, "prices": {}}

            # requests ベースのスクレイパー
            for scrape_fn in [scrape_kaitori_wiki, scrape_kaden_ichiba]:
                record = scrape_fn(product)
                entry["prices"][record.site_name] = asdict(record)
                snapshot["prices"][record.site_name] = record.price
                if record.price:
                    log.info("  %-12s: ¥%s", record.site_name, f"{record.price:,}")
                else:
                    log.info("  %-12s: — (%s)", record.site_name, record.note)

            # Playwright ベース（買取１丁目）
            record = await scrape_ichidome_async(product, browser)
            entry["prices"][record.site_name] = asdict(record)
            snapshot["prices"][record.site_name] = record.price
            if record.price:
                log.info("  %-12s: ¥%s", record.site_name, f"{record.price:,}")
            else:
                log.info("  %-12s: — (%s)", record.site_name, record.note)

            entry["history"].append(snapshot)
            entry["history"] = entry["history"][-30:]

        await browser.close()

    data["updated_at"] = timestamp
    save_data(data)
    log.info("保存完了: %s", DATA_FILE)


if __name__ == "__main__":
    asyncio.run(main())
