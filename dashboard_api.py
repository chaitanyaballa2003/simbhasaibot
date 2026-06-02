from pathlib import Path

import pandas as pd
from flask import Flask, jsonify


BASE_DIR = Path(__file__).resolve().parent
SALES_FILE = BASE_DIR / "sales.csv"
PURCHASE_FILE = BASE_DIR / "purchases.csv"
STOCK_FILE = BASE_DIR / "inventory.csv"

app = Flask(__name__)


def read_csv(file_path: Path) -> pd.DataFrame:
    if not file_path.exists():
        return pd.DataFrame()

    try:
        return pd.read_csv(file_path)
    except pd.errors.EmptyDataError:
        return pd.DataFrame()


def numeric_total(df: pd.DataFrame, column: str) -> float:
    if df.empty or column not in df.columns:
        return 0.0
    return float(pd.to_numeric(df[column], errors="coerce").fillna(0).sum())


@app.route("/dashboard")
def dashboard():
    sales = read_csv(SALES_FILE)
    purchases = read_csv(PURCHASE_FILE)
    stock = read_csv(STOCK_FILE)

    sales_total = numeric_total(sales, "amount")
    purchases_total = numeric_total(purchases, "amount")

    inventory = []
    if not stock.empty and {"item", "quantity"}.issubset(stock.columns):
        inventory = stock.tail(20)[["item", "quantity"]].to_dict(orient="records")

    vendors = []
    if not purchases.empty and {"vendor", "amount"}.issubset(purchases.columns):
        grouped = purchases.copy()
        grouped["amount"] = pd.to_numeric(grouped["amount"], errors="coerce").fillna(0)
        vendors = (
            grouped.groupby("vendor", dropna=False)["amount"]
            .sum()
            .sort_values(ascending=False)
            .reset_index()
            .to_dict(orient="records")
        )

    return jsonify({
        "sales": sales_total,
        "purchases": purchases_total,
        "profit": sales_total - purchases_total,
        "inventory": inventory,
        "vendors": vendors,
    })


if __name__ == "__main__":
    app.run(debug=True)
