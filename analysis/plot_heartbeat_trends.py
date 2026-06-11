import sys
from pathlib import Path

# Allow this script to be run directly from the project root or the
# analysis/ directory while still importing from src/.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import matplotlib.pyplot as plt

from src.common.heartbeat_csv import DEFAULT_CSV_PATH, load_heartbeat_history

OUTPUT_DIR = Path("analysis/plots")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

df = load_heartbeat_history(csv_path=DEFAULT_CSV_PATH)

for host in sorted(df["host"].dropna().unique()):
    host_df = df[df["host"] == host].copy()

    if len(host_df) < 2:
        print(f"Skipping {host}: only {len(host_df)} row(s), not enough for a line graph.")
        continue

    plt.figure(figsize=(12, 6))
    plt.plot(host_df["heartbeat_timestamp"], host_df["host_cpu_percent"], label="Host CPU %")
    plt.plot(host_df["heartbeat_timestamp"], host_df["host_ram_percent"], label="Host RAM %")
    gpu_mask = host_df["host_gpu_percent"].notna()
    vram_mask = host_df["host_vram_percent"].notna()
    plt.plot(
        host_df.loc[gpu_mask, "heartbeat_timestamp"],
        host_df.loc[gpu_mask, "host_gpu_percent"],
        label="Host GPU %",
    )
    plt.plot(
        host_df.loc[vram_mask, "heartbeat_timestamp"],
        host_df.loc[vram_mask, "host_vram_percent"],
        label="Host VRAM %",
    )

    plt.title(f"Host CPU/RAM/GPU/VRAM usage over time — {host}")
    plt.xlabel("Time")
    plt.ylabel("Percent")
    plt.legend()
    plt.xticks(rotation=45)
    plt.tight_layout()

    output_path = OUTPUT_DIR / f"{host}_host_cpu_ram_gpu_vram_trend.png"
    plt.savefig(output_path)
    plt.close()

    print(f"Saved {output_path}")