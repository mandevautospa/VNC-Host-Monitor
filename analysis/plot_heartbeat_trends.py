from pathlib import Path
import pandas as pd
import matplotlib.pyplot as plt

CSV_PATH = Path("analysis/heartbeat_metrics.csv")
OUTPUT_DIR = Path("analysis/plots")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

df = pd.read_csv(CSV_PATH)

df["heartbeat_timestamp"] = pd.to_datetime(df["heartbeat_timestamp"], errors="coerce")

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
    if column in df.columns:
        df[column] = pd.to_numeric(df[column], errors="coerce")

df = df.dropna(subset=["heartbeat_timestamp"])
df = df.sort_values("heartbeat_timestamp")

for host in sorted(df["host"].dropna().unique()):
    host_df = df[df["host"] == host].copy()

    if len(host_df) < 2:
        print(f"Skipping {host}: only {len(host_df)} row(s), not enough for a line graph.")
        continue

    plt.figure(figsize=(12, 6))
    plt.plot(host_df["heartbeat_timestamp"], host_df["host_cpu_percent"], label="Host CPU %")
    plt.plot(host_df["heartbeat_timestamp"], host_df["host_ram_percent"], label="Host RAM %")

    plt.title(f"Host CPU and RAM usage over time — {host}")
    plt.xlabel("Time")
    plt.ylabel("Percent")
    plt.legend()
    plt.xticks(rotation=45)
    plt.tight_layout()

    output_path = OUTPUT_DIR / f"{host}_host_cpu_ram_trend.png"
    plt.savefig(output_path)
    plt.close()

    print(f"Saved {output_path}")