"""生成 metric_facts 宽表 10 周示例数据（W21-W30）"""
import random
import sqlite3
from pathlib import Path
from datetime import date, timedelta

DB_PATH = Path(__file__).parent / "bce.db"

random.seed(42)

# 维度
CATEGORIES = ["总体", "蔬菜", "肉类", "蛋类", "米类", "面类", "调料类", "油类", "水产", "豆制品", "冻品"]
MERCHANT_TYPES = [None, "酸辣粉", "兰州拉面", "沙县小吃", "黄焖鸡", "麻辣烫"]

# 指标定义：(name, unit, base_value, sensitivity_level)
METRICS = [
    ("GMV", "万元", 1800, 1),
    ("订单量", "单", 12000, 1),
    ("客单价", "元", 150, 1),
    ("复购率", "%", 37, 1),
    ("品类宽度", "个", 850, 1),
    ("毛利率", "%", 22, 2),
    ("净利率", "%", 8, 3),
    ("商品成本率", "%", 62, 4),
    ("运输成本率", "%", 8, 4),
    ("仓储成本率", "%", 5, 4),
    ("损耗率", "%", 3, 4),
]

# 品类系数（模拟不同品类的规模差异）
CATEGORY_SCALE = {
    "总体": 1.0, "蔬菜": 0.22, "肉类": 0.25, "蛋类": 0.08, "米类": 0.10,
    "面类": 0.09, "调料类": 0.06, "油类": 0.07, "水产": 0.08, "豆制品": 0.03, "冻品": 0.05,
}


def generate_week_data(week_num: int, base_date: date):
    """生成一周的数据"""
    rows = []
    week_label = f"2026-W{week_num:02d}"
    report_date = base_date.isoformat()
    # 周环比增长趋势（每周微增 + 随机波动）
    trend_factor = 1 + (week_num - 21) * 0.008 + random.uniform(-0.02, 0.02)

    for category in CATEGORIES:
        scale = CATEGORY_SCALE[category]
        for metric_name, unit, base_value, sensitivity in METRICS:
            # 总体指标不按品类缩放（除了 GMV/订单量）
            if category != "总体" and metric_name in ("GMV", "订单量"):
                value = base_value * scale * trend_factor
            elif category != "总体" and metric_name in ("客单价", "复购率", "品类宽度"):
                # 这些指标品类间差异小，加随机偏移
                value = base_value * (1 + random.uniform(-0.15, 0.15))
            elif category == "总体":
                value = base_value * trend_factor
            else:
                # 率类指标
                value = base_value * (1 + random.uniform(-0.1, 0.1))

            # 百分比指标限制范围
            if unit == "%":
                value = max(1.0, min(95.0, value))

            value = round(value, 1)
            wow = round(random.uniform(-5, 5), 1)

            rows.append((report_date, week_label, category, None, metric_name, value, unit, wow, None, None, sensitivity))

    # 商户类型维度（只有 GMV 和订单量）
    for mt in MERCHANT_TYPES[1:]:  # skip None
        for metric_name, unit, base_value, sensitivity in METRICS[:2]:
            value = round(base_value * random.uniform(0.03, 0.08) * trend_factor, 1)
            wow = round(random.uniform(-8, 8), 1)
            rows.append((report_date, week_label, "总体", mt, metric_name, value, unit, wow, None, None, sensitivity))

    return rows


def main():
    conn = sqlite3.connect(str(DB_PATH))
    # 确保表存在
    conn.execute("""
        CREATE TABLE IF NOT EXISTS metric_facts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            report_date TEXT NOT NULL,
            week_label TEXT NOT NULL,
            category TEXT NOT NULL DEFAULT '总体',
            merchant_type TEXT,
            metric_name TEXT NOT NULL,
            metric_value REAL NOT NULL,
            metric_unit TEXT,
            wow_change_pct REAL,
            yoy_change_pct REAL,
            source_doc_id TEXT,
            sensitivity_level INTEGER DEFAULT 1,
            created_at TEXT DEFAULT (datetime('now'))
        )
    """)
    # 清空旧数据
    conn.execute("DELETE FROM metric_facts")

    all_rows = []
    start_date = date(2026, 5, 19)  # W21 起始
    for i in range(10):
        week_num = 21 + i
        week_date = start_date + timedelta(weeks=i)
        all_rows.extend(generate_week_data(week_num, week_date))

    conn.executemany(
        """INSERT INTO metric_facts
           (report_date, week_label, category, merchant_type, metric_name, metric_value, metric_unit, wow_change_pct, yoy_change_pct, source_doc_id, sensitivity_level)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        all_rows,
    )
    conn.commit()
    count = conn.execute("SELECT COUNT(*) FROM metric_facts").fetchone()[0]
    conn.close()
    print(f"Inserted {count} rows into metric_facts (10 weeks × {len(CATEGORIES)} categories × {len(METRICS)} metrics + merchant dims)")


if __name__ == "__main__":
    main()
