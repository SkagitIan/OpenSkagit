import pandas as pd
import numpy as np
from sklearn.preprocessing import StandardScaler
from sklearn.cluster import KMeans
from sqlalchemy import create_engine

# --- 1. Load your regression dataset (SFR for example)
engine = create_engine("postgresql://django:grandson2025@159.65.103.78:5432/skagit?sslmode=require")
df = pd.read_sql("SELECT * FROM sale_regression_sfr", engine)

# --- 2. Basic cleanup
df = df.dropna(subset=["sale_price","living_area","latitude","longitude","assessed_value"])
df = df[df["sale_price"] > 50000]
df = df[df["living_area"] > 0]
df = df[df["assessed_value"] > 0]

# --- 3. Build your feature set safely
df["log_price"] = np.log(df["sale_price"].clip(lower=1))
df["log_area"] = np.log(df["living_area"].clip(lower=1))
df["ratio"] = (df["sale_price"] / df["assessed_value"]).replace([np.inf, -np.inf], np.nan)
df["effective_age"] = (df["year_built"] - df["eff_year_built"]).fillna(0).clip(lower=0)

# Drop any leftover invalid values
df = df.replace([np.inf, -np.inf], np.nan).dropna(subset=["log_price","log_area","ratio","latitude","longitude"])

features = ["latitude","longitude","log_price","log_area","effective_age","ratio"]
X = df[features].astype(float)


# --- 4. Normalize so no single variable dominates
scaler = StandardScaler()
X_scaled = scaler.fit_transform(X)

# --- 5. Cluster (KMeans to start)
# You can tune n_clusters (5–15 is typical)
kmeans = KMeans(n_clusters=10, random_state=42)
df["market_cluster"] = kmeans.fit_predict(X_scaled)

# --- 6. Review results
summary = df.groupby("market_cluster").agg(
    n_sales=("sale_price","size"),
    median_price=("sale_price","median"),
    mean_ratio=("ratio","mean"),
    mean_age=("effective_age","mean")
).reset_index()

print(summary)

# --- 7. Save to database or CSV
df.to_csv("sales_with_market_clusters.csv", index=False)
