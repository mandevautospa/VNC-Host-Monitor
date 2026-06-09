import pandas as pd

CSV_PATH = "analysis/heartbeat_metrics.csv"

df = pd.read_csv(CSV_PATH)

numeric_columns = [
    "host_cpu_percent",
    "host_ram_percent",
    "disk_free_percent",
    "disk_free_gb",
    "p3d_cpu_percent",
    "p3d_memory_mb",
    "p3d_memory_percent",
]

for column in numeric_columns:
    df[column] = pd.to_numeric(df[column], errors="coerce")

print("\nRows per host:")
print(df["host"].value_counts())

print("\nPeak host CPU by host:")
print(df.groupby("host")["host_cpu_percent"].max().sort_values(ascending=False))

print("\nPeak host RAM by host:")
print(df.groupby("host")["host_ram_percent"].max().sort_values(ascending=False))

print("\nLowest disk free percent by host:")
print(df.groupby("host")["disk_free_percent"].min().sort_values())

print("\nPeak P3D memory MB by host:")
print(df.groupby("host")["p3d_memory_mb"].max().sort_values(ascending=False))

print("\nPeak P3D CPU percent by host:")
print(df.groupby("host")["p3d_cpu_percent"].max().sort_values(ascending=False))