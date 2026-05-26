import pandas as pd

excel_path = "PA_Business_Rules.xlsx"

xls = pd.ExcelFile(excel_path)

print("SHEETS:")
print(xls.sheet_names)

for sheet in xls.sheet_names:
    print("\n" + "=" * 80)
    print(f"SHEET: {sheet}")
    print("=" * 80)

    df = pd.read_excel(excel_path, sheet_name=sheet)

    print(df.head(10))