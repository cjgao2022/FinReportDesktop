from main import cninfo_resolve_stock, cninfo_fetch_reports, sina_resolve_stock, sina_fetch_reports

# --- 核心复现场景：300476 年报 2025 巨潮 ---
print("=== 300476 年报 2025 巨潮资讯（修复前会空，修复后应有结果）===")
ci = cninfo_resolve_stock("300476")
print("解析:", ci)
items = cninfo_fetch_reports(ci["stock_id"], ci["org_id"], ci.get("column","szse"), ci["plate"], "年报", 2025)
for item in items[:3]:
    print(f"  {item['date']}  reportYear={item['report_year']}  {item['title']}")

# --- 主板 000001 不退化 ---
print()
print("=== 000001 年报 2024 巨潮资讯（主板不退化）===")
ci2 = cninfo_resolve_stock("000001")
print("解析:", ci2)
items2 = cninfo_fetch_reports(ci2["stock_id"], ci2["org_id"], ci2.get("column","szse"), ci2["plate"], "年报", 2024)
for item in items2[:2]:
    print(f"  {item['date']}  reportYear={item['report_year']}  {item['title']}")

# --- 招商银行 上海股 ---
print()
print("=== 招商银行 年报 2023 ===")
ci3 = cninfo_resolve_stock("招商银行")
print("解析:", ci3)
items3 = cninfo_fetch_reports(ci3["stock_id"], ci3["org_id"], ci3.get("column","szse"), ci3["plate"], "年报", 2023)
for item in items3[:2]:
    print(f"  {item['date']}  reportYear={item['report_year']}  {item['title']}")

# --- 新浪财经：不变 ---
print()
print("=== 新浪 300476 年报 2025 ===")
si = sina_resolve_stock("胜宏科技")
print("解析:", si)
items4 = sina_fetch_reports(si["stock_id"], "年报", 2025)
for item in items4[:2]:
    print(f"  {item['date']}  reportYear={item['report_year']}  {item['title']}")
