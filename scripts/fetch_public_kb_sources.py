#!/usr/bin/env python3
"""下载真实公开语料到 knowledge_base，并清洗 HTML→Markdown（带来源标注）。

仅保存可校验的公开网页/PDF；失败或无效文件丢弃。不生成捏造正文。
"""

from __future__ import annotations

import hashlib
import re
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "knowledge_base" / "raw"
WEB = RAW / "curated" / "public_web"
EXT = RAW / "external"
MD_OUT = RAW / "curated" / "guidelines"
UA = "Mozilla/5.0 (compatible; FitPilotKBBot/1.0; +local research)"

SOURCES: list[tuple[str, Path]] = [
    # 中国营养学会官网公开页
    (
        "http://dg.cnsoc.org/article/04/J4-AsD_DR3OLQMnHG0-jZA.html",
        WEB / "cn_dietary_guidelines_2022_eight_principles.html",
    ),
    (
        "https://www.sport.gov.cn/n315/n331/n405/c819327/content.html",
        WEB / "cn_national_fitness_guide_interpretation.html",
    ),
    # WHO 中文事实清单 / 新闻
    (
        "https://www.who.int/zh/news/item/25-11-2020-every-move-counts-towards-better-health-says-who",
        WEB / "who_every_move_counts_zh.html",
    ),
    (
        "https://www.who.int/zh/news-room/fact-sheets/detail/physical-activity",
        WEB / "who_physical_activity_factsheet_zh.html",
    ),
    (
        "https://www.who.int/zh/news-room/fact-sheets/detail/healthy-diet",
        WEB / "who_healthy_diet_factsheet_zh.html",
    ),
    (
        "https://www.who.int/zh/news-room/fact-sheets/detail/salt-reduction",
        WEB / "who_salt_reduction_factsheet_zh.html",
    ),
    (
        "https://www.who.int/zh/news-room/feature-stories/detail/5-tips-for-a-healthy-diet-this-new-year",
        WEB / "who_5_tips_healthy_diet_zh.html",
    ),
    (
        "https://www.who.int/zh/news-room/fact-sheets/detail/hypertension",
        WEB / "who_hypertension_factsheet_zh.html",
    ),
    (
        "https://www.who.int/zh/news-room/fact-sheets/detail/obesity-and-overweight",
        WEB / "who_obesity_overweight_factsheet_zh.html",
    ),
    # CDC / health.gov / NHS（英文公开页，作补充）
    (
        "https://www.cdc.gov/physical-activity-basics/benefits/index.html",
        WEB / "cdc_pa_benefits_en.html",
    ),
    (
        "https://www.cdc.gov/physical-activity-basics/guidelines/adults.html",
        WEB / "cdc_pa_adults_en.html",
    ),
    (
        "https://health.gov/our-work/nutrition-physical-activity/physical-activity-guidelines/current-guidelines/top-10-things-know",
        WEB / "us_pa_top10_en.html",
    ),
    (
        "https://www.nhs.uk/live-well/eat-well/how-to-eat-a-balanced-diet/eating-a-balanced-diet/",
        WEB / "nhs_balanced_diet_en.html",
    ),
    # 政策 PDF（已验证可下）
    (
        "https://www.sport.gov.cn/gdnps/files/c26011303/26015056.pdf",
        EXT / "CN_higher_level_fitness_public_service_system_opinions.pdf",
    ),
    # ---- 第二轮：补水 / 儿童青少年活动 / 居家活动 / 减糖 ----
    (
        "https://www.cdc.gov/healthy-weight-growth/water-healthy-drinks/index.html",
        WEB / "cdc_water_healthy_drinks_en.html",
    ),
    (
        "https://www.nhs.uk/live-well/eat-well/food-guidelines-and-food-labels/water-drinks-nutrition/",
        WEB / "nhs_water_drinks_hydration_en.html",
    ),
    (
        "https://www.cdc.gov/nchs/data/databriefs/db242.pdf",
        EXT / "CDC_NCHS_water_intake_databrief_242.pdf",
    ),
    (
        "https://www.who.int/zh/news/item/24-04-2019-to-grow-up-healthy-children-need-to-sit-less-and-play-more",
        WEB / "who_children_sit_less_play_more_zh.html",
    ),
    (
        "https://www.who.int/zh/news-room/campaigns/connecting-the-world-to-combat-coronavirus/healthyathome/healthyathome---physical-activity",
        WEB / "who_healthy_at_home_physical_activity_zh.html",
    ),
    (
        "https://www.cdc.gov/nutrition/php/data-research/added-sugars.html",
        WEB / "cdc_added_sugars_en.html",
    ),
    (
        "https://www.nhs.uk/live-well/exercise/exercise-health-benefits/",
        WEB / "nhs_exercise_health_benefits_en.html",
    ),
    (
        "https://www.nhs.uk/live-well/exercise/how-to-improve-strength-flexibility/",
        WEB / "nhs_improve_strength_flexibility_en.html",
    ),
    (
        "https://www.who.int/zh/news-room/fact-sheets/detail/mental-health-strengthening-our-response",
        WEB / "who_mental_health_factsheet_zh.html",
    ),
    (
        "https://www.cdc.gov/healthy-weight-growth/losing-weight/index.html",
        WEB / "cdc_losing_weight_basics_en.html",
    ),
    (
        "https://www.nhs.uk/live-well/healthy-weight/managing-your-weight/tips-to-help-you-lose-weight/",
        WEB / "nhs_weight_loss_tips_en.html",
    ),
    # ---- 第三轮：中文膳食细则 / 全民健身 / 糖盐肥胖 / 安全边界补充 ----
    (
        "http://dg.cnsoc.org/article/04/glVJd6DRRCqm-hYzWlEVNQ.html",
        WEB / "cn_dietary_guidelines_2022_release.html",
    ),
    (
        "https://www.sport.gov.cn/n315/n20001395/c20026015/content.html",
        WEB / "cn_national_fitness_guide_promote_notice_alt.html",
    ),
    (
        "https://www.sport.gov.cn/n20001280/n20001265/n20067533/c24243859/content.html",
        WEB / "cn_fitness_science_tiwei_fusion.html",
    ),
    (
        "https://www.sport.gov.cn/n315/n10702/c27066370/content.html",
        WEB / "cn_scientific_fitness_guidance_reply.html",
    ),
    (
        "https://www.who.int/zh/news-room/fact-sheets/detail/sugars-and-dental-caries",
        WEB / "who_sugars_dental_caries_zh.html",
    ),
    (
        "https://www.who.int/zh/news-room/fact-sheets/detail/malnutrition",
        WEB / "who_malnutrition_factsheet_zh.html",
    ),
    (
        "https://www.cdc.gov/nutrition/data-statistics/know-your-limit-for-added-sugars.html",
        WEB / "cdc_know_limit_added_sugars_en.html",
    ),
    (
        "https://www.nhs.uk/live-well/eat-well/food-types/how-does-sugar-in-our-diet-affect-our-health/",
        WEB / "nhs_sugar_facts_en.html",
    ),
    (
        "https://www.nhs.uk/live-well/eat-well/food-types/salt-nutrition/",
        WEB / "nhs_salt_nutrition_en.html",
    ),
    (
        "https://www.nhs.uk/conditions/obesity/",
        WEB / "nhs_obesity_overview_en.html",
    ),
    (
        "https://www.who.int/zh/news-room/fact-sheets/detail/cardiovascular-diseases-(cvds)",
        WEB / "who_cvd_factsheet_zh.html",
    ),
    (
        "https://www.nhs.uk/live-well/exercise/physical-activity-guidelines-older-adults/",
        WEB / "nhs_exercise_older_adults_en.html",
    ),
]


def fetch(url: str, dest: Path, min_bytes: int = 2000) -> bool:
    dest.parent.mkdir(parents=True, exist_ok=True)
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=90) as resp:
            data = resp.read()
    except Exception as exc:  # noqa: BLE001
        print(f"FAIL {url} :: {exc}")
        return False
    if len(data) < min_bytes:
        print(f"SMALL {len(data)} {url}")
        return False
    # PDF magic
    if dest.suffix.lower() == ".pdf" and not data.startswith(b"%PDF"):
        print(f"NOT_PDF {url}")
        return False
    dest.write_bytes(data)
    print(f"OK {len(data)} -> {dest.relative_to(ROOT)}")
    return True


def html_to_markdown(html: str, *, source_url: str, title_hint: str) -> str:
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        text = re.sub(r"(?is)<script.*?>.*?</script>", " ", html)
        text = re.sub(r"(?is)<style.*?>.*?</style>", " ", text)
        text = re.sub(r"<[^>]+>", " ", text)
        text = re.sub(r"\s+", " ", text).strip()
        return f"# {title_hint}\n\n> 来源：{source_url}\n\n{text}\n"

    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "noscript", "nav", "footer", "header", "aside"]):
        tag.decompose()
    main = soup.find("main") or soup.find("article") or soup.body or soup
    title = title_hint
    if soup.title and soup.title.string:
        title = soup.title.string.strip()[:120]
    h1 = main.find("h1") if main else None
    if h1 and h1.get_text(strip=True):
        title = h1.get_text(strip=True)

    lines: list[str] = [f"# {title}", "", f"> 来源（原文保存）：{source_url}", ""]
    for el in main.find_all(["h1", "h2", "h3", "h4", "p", "li"]):
        t = el.get_text(" ", strip=True)
        if not t or len(t) < 2:
            continue
        # 过滤导航噪音
        if t in {"首页", "联系我们", "指南动态", "English", "更多..."}:
            continue
        name = el.name.lower()
        if name == "h1":
            continue
        if name in {"h2", "h3", "h4"}:
            level = {"h2": 2, "h3": 3, "h4": 4}[name]
            lines.append("#" * level + f" {t}")
            lines.append("")
        elif name == "li":
            lines.append(f"- {t}")
        else:
            lines.append(t)
            lines.append("")
    body = "\n".join(lines).strip() + "\n"
    # 过短视为失败（可能是壳页面）
    if len(re.sub(r"\s+", "", body)) < 400:
        return ""
    return body


def convert_html_dir() -> list[Path]:
    MD_OUT.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    hashes: set[str] = set()
    # 已有 curated md 的哈希，避免重复
    for p in (RAW / "curated").rglob("*.md"):
        hashes.add(hashlib.sha256(p.read_bytes()).hexdigest())
    for html_path in sorted(WEB.glob("*.html")):
        html = html_path.read_text(encoding="utf-8", errors="ignore")
        # 从文件名推断；来源写在同名 .source.url 或从首行注释
        source = ""
        for url, dest in SOURCES:
            if dest == html_path:
                source = url
                break
        md = html_to_markdown(html, source_url=source or html_path.name, title_hint=html_path.stem)
        if not md:
            print(f"SKIP_EMPTY_MD {html_path.name}")
            continue
        digest = hashlib.sha256(md.encode("utf-8")).hexdigest()
        if digest in hashes:
            print(f"DUP_MD {html_path.name}")
            continue
        hashes.add(digest)
        out = MD_OUT / f"{html_path.stem}.md"
        out.write_text(md, encoding="utf-8")
        written.append(out)
        print(f"MD {len(md)} -> {out.relative_to(ROOT)}")
    return written


def cleanup_bad() -> None:
    for p in EXT.glob("*.pdf"):
        data = p.read_bytes()[:8]
        if not data.startswith(b"%PDF"):
            print(f"DEL_BAD_PDF {p.name}")
            p.unlink(missing_ok=True)
    # 删除与已有 US PA 同体积重复
    a = EXT / "US_Physical_Activity_Guidelines_2nd.pdf"
    b = EXT / "US_PA_Guidelines_2nd_healthgov.pdf"
    if a.exists() and b.exists() and a.stat().st_size == b.stat().st_size:
        print(f"DEL_DUP {b.name}")
        b.unlink()


def main() -> int:
    WEB.mkdir(parents=True, exist_ok=True)
    EXT.mkdir(parents=True, exist_ok=True)
    cleanup_bad()
    ok = 0
    for url, dest in SOURCES:
        if dest.exists() and dest.stat().st_size >= 2000:
            if dest.suffix.lower() == ".pdf":
                if dest.read_bytes()[:4] == b"%PDF":
                    print(f"KEEP {dest.relative_to(ROOT)}")
                    ok += 1
                    continue
            else:
                print(f"KEEP {dest.relative_to(ROOT)}")
                ok += 1
                continue
        if fetch(url, dest):
            ok += 1
    written = convert_html_dir()
    print(f"done downloads_ok≈{ok} markdown={len(written)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
