#!/usr/bin/env python3
"""
从周报 Markdown 表格中抽取真实数据，灌入 metric_facts 宽表。
覆盖 W20-W30（11 周）全部真实经营数据。
"""
import sqlite3
import re
from pathlib import Path

DB_PATH = Path(__file__).parent / "bce.db"
SAMPLES_DIR = Path(__file__).parent.parent / "samples"

CATEGORIES = ["蔬菜", "肉类", "蛋类", "米类", "面类", "调料类", "油类", "水产", "豆制品", "冻品"]
MERCHANT_TYPES = ["酸辣粉", "兰州拉面", "沙县小吃", "黄焖鸡", "麻辣烫"]


def parse_number(s: str):
    """从字符串解析数字，返回 float 或 None"""
    if s is None:
        return None
    s = str(s).strip().replace(",", "").replace("，", "").replace("—", "").replace("—", "")
    # 移除万位单位（如 "6.0万"）
    if s.endswith("万"):
        try:
            return float(s[:-1])
        except ValueError:
            pass
    m = re.search(r'-?\d+\.?\d*', s)
    if m:
        try:
            return float(m.group())
        except ValueError:
            return None
    return None


def extract_report_meta(content: str):
    """提取报告日期和周号"""
    m_date = re.search(r'\*\*日期\*\*[：:]\s*(\d{4}-\d{2}-\d{2})', content)
    if not m_date:
        m_date = re.search(r'\*\*日期[：:]\s*(\d{4}-\d{2}-\d{2})\*\*', content)
    m_week = re.search(r'第(\d+)周', content)
    if not m_date or not m_week:
        return None, None
    week_num = int(m_week.group(1))
    return m_date.group(1), f"2026-W{week_num:02d}"


def find_section(content: str, *heading_keywords, heading_level=None):
    """找到包含所有关键词的标题后的第一个表格。

    heading_level: 期望的标题级别（如 '##' 或 '###'），为 None 时自动检测。
    """
    lines = content.split("\n")
    in_section = False
    target_level = None  # 记录首次匹配目标的级别（## 或 ###）
    table_lines = []

    for line in lines:
        stripped = line.strip()
        # 检测标题
        m = re.match(r'^(#{1,3})\s+(.*)', stripped)
        if m:
            level = m.group(1)
            heading_text = m.group(2)
            heading_len = len(level)  # 2 for ##, 3 for ###

            if all(kw in heading_text for kw in heading_keywords):
                # 首次匹配（或同关键词再次匹配，以首次为准）
                if not in_section:
                    in_section = True
                    target_level = heading_len
                    table_lines = []
                    continue
                elif in_section and heading_len <= target_level:
                    # 同级或更高级同关键词，重置
                    table_lines = []
                    continue
                # 否则（更低级别匹配），继续搜索表格
                continue
            elif in_section:
                # 其他标题
                if heading_len <= (target_level or 2):
                    # 同级或更高级 → 退出当前 section
                    break
                # 更低级标题 → 跳过继续找表格
                continue

        if in_section and target_level is not None:
            if stripped.startswith("|"):
                table_lines.append(stripped)
            elif table_lines and stripped and not stripped.startswith("|"):
                break  # 表格结束

    return table_lines


def parse_markdown_table(table_lines: list[str]) -> list[list[str]]:
    """解析 Markdown 表格为 rows（跳过表头分隔行）"""
    rows = []
    for i, line in enumerate(table_lines):
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        # 跳过分隔行
        if all(re.match(r'^-+$', c) for c in cells):
            continue
        rows.append(cells)
    return rows


def extract_section1_overall(content: str) -> dict[str, float]:
    """从「一、核心指标看板」提取总体指标"""
    table = find_section(content, "一", "指标看板")
    if not table:
        return {}
    rows = parse_markdown_table(table)
    # rows[0] = ["指标", "本周均值", "上周均值", "环比", "4周均值", ...]
    metrics = {}
    for row in rows[1:]:  # skip header
        if len(row) < 2:
            continue
        name = row[0].strip()
        value = parse_number(row[1])
        if value is None:
            continue

        name_map = {
            "日均 GMV（万元）": ("GMV", "万元"),
            "日均 GMV": ("GMV", "万元"),
            "日均订单量（单）": ("订单量", "单"),
            "日均订单量": ("订单量", "单"),
            "客单价（元）": ("客单价", "元"),
            "客单价": ("客单价", "元"),
            "复购率": ("复购率", "%"),
            "品类宽度": ("品类宽度", "个"),
            "SKU 宽度": ("SKU宽度", "个"),
            "SKU宽度": ("SKU宽度", "个"),
            "毛利率": ("毛利率", "%"),
            "净利率": ("净利率", "%"),
        }
        for key, (metric_name, unit) in name_map.items():
            if key in name:
                metrics[metric_name] = (value, unit)
                break

    return metrics


def extract_section2_category_gmv(content: str) -> dict[str, dict[str, tuple]]:
    """从「二.1 品类 GMV 贡献」提取各品类指标"""
    table = find_section(content, "二", "品类")
    if not table:
        # 尝试更宽泛的匹配
        table = find_section(content, "品类", "GMV")
    if not table:
        return {}

    rows = parse_markdown_table(table)
    # Header: ["品类", "日均 GMV（万元）", "占比", "环比", "毛利率", "客单价", "复购率", ...]
    # 找到各列的位置
    header = rows[0] if rows else []
    col_map = {}
    for i, h in enumerate(header):
        if "品类" in h and i == 0:
            pass  # skip first column (category name)
        elif ("GMV" in h or "日均" in h) and "GMV" not in col_map:
            col_map["GMV"] = i
        elif "毛利率" in h:
            col_map["毛利率"] = i
        elif "客单价" in h:
            col_map["客单价"] = i
        elif "复购率" in h:
            col_map["复购率"] = i
        elif "品类宽度" in h:
            col_map["品类宽度"] = i

    result = {}
    for row in rows[1:]:
        cat = row[0].strip()
        if cat not in CATEGORIES:
            continue
        metrics = {}
        if "GMV" in col_map and len(row) > col_map["GMV"]:
            v = parse_number(row[col_map["GMV"]])
            if v is not None:
                metrics["GMV"] = (v, "万元")
        if "毛利率" in col_map and len(row) > col_map["毛利率"]:
            v = parse_number(row[col_map["毛利率"]])
            if v is not None:
                metrics["毛利率"] = (v, "%")
        if "客单价" in col_map and len(row) > col_map["客单价"]:
            v = parse_number(row[col_map["客单价"]])
            if v is not None:
                metrics["客单价"] = (v, "元")
        if "复购率" in col_map and len(row) > col_map["复购率"]:
            v = parse_number(row[col_map["复购率"]])
            if v is not None:
                metrics["复购率"] = (v, "%")
        if "品类宽度" in col_map and len(row) > col_map["品类宽度"]:
            v = parse_number(row[col_map["品类宽度"]])
            if v is not None:
                metrics["品类宽度"] = (v, "个")
        result[cat] = metrics

    return result


def extract_section3_merchants(content: str) -> dict[str, dict[str, tuple]]:
    """从「三.1 各商户类型核心指标」提取各商户类型指标"""
    table = find_section(content, "商户", "核心")
    if not table:
        table = find_section(content, "商户分类")
    if not table:
        return {}

    rows = parse_markdown_table(table)
    if not rows:
        return {}
    header = rows[0]
    col_map = {}
    gmv_col_set = False  # 只取第一个 GMV 列（日均 GMV），不要月均 GMV
    for i, h in enumerate(header):
        if "商户数" in h:
            col_map["商户数"] = i
        elif "日均 GMV" in h and not gmv_col_set:
            col_map["GMV"] = i
            gmv_col_set = True
        elif "客单价" in h:
            col_map["客单价"] = i
        elif "复购率" in h:
            col_map["复购率"] = i
        elif "品类宽度" in h:
            col_map["品类宽度"] = i
        elif "SKU" in h and "宽度" in h:
            col_map["SKU宽度"] = i

    result = {}
    for row in rows[1:]:
        name = row[0].strip()
        # 标准化商户名（移除"店"字）
        merchant_name = name.replace("店", "").strip()
        if merchant_name not in MERCHANT_TYPES:
            continue
        metrics = {}
        if "商户数" in col_map and len(row) > col_map["商户数"]:
            v = parse_number(row[col_map["商户数"]])
            if v is not None:
                metrics["商户数"] = (v, "家")
        if "GMV" in col_map and len(row) > col_map["GMV"]:
            v = parse_number(row[col_map["GMV"]])
            if v is not None:
                metrics["GMV"] = (v, "万元")
        if "客单价" in col_map and len(row) > col_map["客单价"]:
            v = parse_number(row[col_map["客单价"]])
            if v is not None:
                metrics["客单价"] = (v, "元")
        if "复购率" in col_map and len(row) > col_map["复购率"]:
            v = parse_number(row[col_map["复购率"]])
            if v is not None:
                metrics["复购率"] = (v, "%")
        if "品类宽度" in col_map and len(row) > col_map["品类宽度"]:
            v = parse_number(row[col_map["品类宽度"]])
            if v is not None:
                metrics["品类宽度"] = (v, "个")
        result[merchant_name] = metrics

    return result


def extract_section4_pnl_overall(content: str) -> dict[str, float]:
    """从「四、损益表」提取总体费用率（占GMV）"""
    table = find_section(content, "损益表")
    if not table:
        return {}

    rows = parse_markdown_table(table)
    pnl = {}
    for row in rows[1:]:  # skip header
        if len(row) < 2:
            continue
        name = row[0].strip()
        value = parse_number(row[1])
        if value is None:
            continue

        # 映射到指标名和单位
        if "商品成本" in name:
            pnl["商品成本"] = (value, "万元")
        elif "运输成本" in name and "率" not in name:
            pnl["运输成本"] = (value, "万元")
        elif "仓储成本" in name and "率" not in name:
            pnl["仓储成本"] = (value, "万元")
        elif "销售费用" in name:
            pnl["销售费用"] = (value, "万元")
        elif "损耗成本" in name and "率" not in name:
            pnl["损耗成本"] = (value, "万元")
        elif "管理费用" in name:
            pnl["管理费用"] = (value, "万元")
        elif "毛利润" in name and "=" in name:
            pnl["毛利润"] = (value, "万元")
        elif "净利润" in name and "=" in name:
            pnl["净利润金额"] = (value, "万元")

    # 如果有第3列（占GMV），也提取
    for row in rows[1:]:
        if len(row) >= 3:
            name = row[0].strip()
            pct = parse_number(row[2])
            if pct is None:
                continue
            if "商品成本" in name:
                pnl["商品成本率"] = (pct, "%")
            elif "运输成本" in name:
                pnl["运输成本率"] = (pct, "%")
            elif "仓储成本" in name:
                pnl["仓储成本率"] = (pct, "%")
            elif "销售费用" in name:
                pnl["销售费用率"] = (pct, "%")
            elif "损耗成本" in name:
                pnl["损耗成本率"] = (pct, "%")
            elif "管理费用" in name:
                pnl["管理费用率"] = (pct, "%")
            elif "毛利润" in name and "=" in name:
                pnl["毛利率_from_pnl"] = (pct, "%")
            elif "净利润" in name and "=" in name:
                pnl["净利率_from_pnl"] = (pct, "%")

    return pnl


def extract_section4_pnl_category(content: str) -> dict[str, dict[str, tuple]]:
    """从「四.2 各品类损益穿透」提取各品类费用率"""
    table = find_section(content, "损益穿透")
    if not table:
        table = find_section(content, "品类损益")
    if not table:
        return {}

    rows = parse_markdown_table(table)
    if not rows:
        return {}
    header = rows[0]
    col_map = {}
    for i, h in enumerate(header):
        if "品类" in h and i == 0:
            col_map["品类"] = i
        elif "毛利率" in h:
            col_map["毛利率"] = i
        elif "运输成本率" in h:
            col_map["运输成本率"] = i
        elif "仓储成本率" in h:
            col_map["仓储成本率"] = i
        elif "损耗率" in h:
            col_map["损耗率"] = i
        elif "净利率" in h:
            col_map["净利率"] = i

    result = {}
    for row in rows[1:]:
        cat = row[0].strip()
        if cat not in CATEGORIES:
            continue
        metrics = {}
        for metric_name, col_idx in col_map.items():
            if metric_name == "品类":
                continue
            if len(row) > col_idx:
                v = parse_number(row[col_idx])
                if v is not None:
                    metrics[metric_name] = (v, "%")
        result[cat] = metrics

    return result


def main():
    conn = sqlite3.connect(str(DB_PATH))

    # 清空旧数据
    conn.execute("DELETE FROM metric_facts")

    md_files = sorted(SAMPLES_DIR.glob("weekly_sales_2026_w*.md"))
    print(f"Found {len(md_files)} weekly reports")

    # 先收集所有数据，用于计算环比
    all_weeks_data = []

    for md_path in md_files:
        content = md_path.read_text(encoding="utf-8")
        report_date, week_label = extract_report_meta(content)
        if not report_date:
            print(f"  SKIP {md_path.name}: no date found")
            continue

        print(f"  Processing {md_path.name} → {week_label} ({report_date})")

        week_data = {
            "report_date": report_date,
            "week_label": week_label,
            "source_doc": md_path.name,
            "overall": extract_section1_overall(content),
            "categories": extract_section2_category_gmv(content),
            "merchants": extract_section3_merchants(content),
            "pnl_overall": extract_section4_pnl_overall(content),
            "pnl_category": extract_section4_pnl_category(content),
        }
        all_weeks_data.append(week_data)

    # 按 report_date 排序
    all_weeks_data.sort(key=lambda x: x["report_date"])

    # 构建数据行
    all_rows = []

    for i, week in enumerate(all_weeks_data):
        report_date = week["report_date"]
        week_label = week["week_label"]
        source_doc = week["source_doc"]

        # ── 总体指标 ──
        overall = week["overall"]
        pnl_overall = week["pnl_overall"]

        # 合并 section1 和 section4 的总体数据
        # section1 有: GMV, 订单量, 客单价, 复购率, 品类宽度, SKU宽度, 毛利率, 净利率
        # section4 有: 商品成本率, 运输成本率, 仓储成本率, 销售费用率, 损耗成本率, 管理费用率

        # 先添加 section1 的指标
        for metric_name, (value, unit) in overall.items():
            # 计算环比
            wow = None
            if i > 0:
                prev_overall = all_weeks_data[i - 1]["overall"]
                if metric_name in prev_overall:
                    prev_val = prev_overall[metric_name][0]
                    if prev_val != 0:
                        wow = round((value - prev_val) / abs(prev_val) * 100, 1)

            all_rows.append((
                report_date, week_label, "总体", None,
                metric_name, value, unit, wow,
                None, source_doc, 1
            ))

        # 添加 section4 的费用率指标（占GMV）
        rate_metrics = {
            "商品成本率": pnl_overall.get("商品成本率"),
            "运输成本率": pnl_overall.get("运输成本率"),
            "仓储成本率": pnl_overall.get("仓储成本率"),
            "销售费用率": pnl_overall.get("销售费用率"),
            "损耗成本率": pnl_overall.get("损耗成本率"),
            "管理费用率": pnl_overall.get("管理费用率"),
        }
        for metric_name, val_unit in rate_metrics.items():
            if val_unit is None:
                continue
            value, unit = val_unit
            # 计算环比
            wow = None
            if i > 0:
                prev_pnl = all_weeks_data[i - 1]["pnl_overall"]
                prev_val_unit = prev_pnl.get(metric_name)
                if prev_val_unit is not None:
                    prev_val = prev_val_unit[0]
                    if prev_val != 0:
                        wow = round((value - prev_val) / abs(prev_val) * 100, 1)

            all_rows.append((
                report_date, week_label, "总体", None,
                metric_name, value, unit, wow,
                None, source_doc, 1
            ))

        # ── 品类指标 ──
        categories = week["categories"]
        pnl_category = week["pnl_category"]

        for cat in CATEGORIES:
            cat_metrics = categories.get(cat, {})
            cat_pnl = pnl_category.get(cat, {})

            # 合并品类 GMV/毛利率/客单价/复购率/品类宽度 + 品类损益率
            merged = dict(cat_metrics)
            for k, v in cat_pnl.items():
                if k not in merged:  # 不覆盖已有的
                    merged[k] = v

            for metric_name, (value, unit) in merged.items():
                wow = None
                if i > 0:
                    prev_cats = all_weeks_data[i - 1]["categories"]
                    prev_pnl_cats = all_weeks_data[i - 1]["pnl_category"]
                    prev_val = None
                    if cat in prev_cats and metric_name in prev_cats[cat]:
                        prev_val = prev_cats[cat][metric_name][0]
                    elif cat in prev_pnl_cats and metric_name in prev_pnl_cats[cat]:
                        prev_val = prev_pnl_cats[cat][metric_name][0]
                    if prev_val is not None and prev_val != 0:
                        wow = round((value - prev_val) / abs(prev_val) * 100, 1)

                all_rows.append((
                    report_date, week_label, cat, None,
                    metric_name, value, unit, wow,
                    None, source_doc, 1
                ))

        # ── 商户类型指标 ──
        merchants = week["merchants"]
        for mt in MERCHANT_TYPES:
            mt_metrics = merchants.get(mt, {})
            for metric_name, (value, unit) in mt_metrics.items():
                wow = None
                if i > 0:
                    prev_merchants = all_weeks_data[i - 1]["merchants"]
                    if mt in prev_merchants and metric_name in prev_merchants[mt]:
                        prev_val = prev_merchants[mt][metric_name][0]
                        if prev_val != 0:
                            wow = round((value - prev_val) / abs(prev_val) * 100, 1)

                all_rows.append((
                    report_date, week_label, "总体", mt,
                    metric_name, value, unit, wow,
                    None, source_doc, 1
                ))

    # 批量插入
    conn.executemany(
        """INSERT INTO metric_facts
           (report_date, week_label, category, merchant_type,
            metric_name, metric_value, metric_unit, wow_change_pct,
            yoy_change_pct, source_doc_id, sensitivity_level)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        all_rows,
    )
    conn.commit()

    count = conn.execute("SELECT COUNT(*) FROM metric_facts").fetchone()[0]
    weeks = conn.execute("SELECT COUNT(DISTINCT week_label) FROM metric_facts").fetchone()[0]
    conn.close()

    print(f"\n✅ Done! Inserted {count} rows across {weeks} weeks.")
    print(f"   Source: real data from weekly report markdown tables.")


if __name__ == "__main__":
    main()
