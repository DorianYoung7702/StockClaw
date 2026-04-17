import pandas as pd


def read_symbol_list_from_csv(csv_path: str, top_n: int = 2000) -> list[str]:
    df = pd.read_csv(csv_path)
    df["Volume"] = df["Volume"].replace("-", 0.0)
    df["Price"] = df["Price"].replace("-", 0.0)
    df["Volume"] = df["Volume"].astype(float)
    df["Price"] = df["Price"].astype(float)
    df["Weight"] = df["Volume"] * df["Price"]
    df.sort_values(by="Weight", ascending=False, inplace=True)
    return df['Symbol'].head(top_n).tolist()