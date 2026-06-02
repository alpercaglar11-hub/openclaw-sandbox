"""Bridge between OpenClaw and The Cascade Simulation."""
import asyncio
import json
import os
import subprocess
from pathlib import Path

CASCADE_PATH = Path.home() / "videolar/labs/the-cascade-simulation"

async def run_simulation(seed: int = 42) -> dict:
    cmd = ["python", "run_v2.py", "--engine-only"]
    env = os.environ.copy()
    env["CASCADE_SEED"] = str(seed)
    try:
        result = subprocess.run(
            cmd, cwd=CASCADE_PATH, capture_output=True,
            text=True, timeout=60, env=env,
        )
        summary_path = CASCADE_PATH / "recovery_summary.json"
        summary = {}
        if summary_path.exists():
            with open(summary_path) as f:
                summary = json.load(f)
        return {
            "status": "success" if result.returncode == 0 else "failed",
            "seed": seed, "summary": summary,
            "stdout": result.stdout[-500:] if result.stdout else "",
        }
    except subprocess.TimeoutExpired:
        return {"status": "timeout", "seed": seed}
    except Exception as e:
        return {"status": "error", "error": str(e)}

async def read_telemetry(last_n_ticks: int = 10) -> dict:
    try:
        import pandas as pd
        telemetry_path = CASCADE_PATH / "telemetry.csv"
        if not telemetry_path.exists():
            return {"error": "telemetry.csv not found, run simulation first"}
        df = pd.read_csv(telemetry_path)
        last = df.tail(last_n_ticks)
        return {
            "total_ticks": len(df),
            "last_stability": round(float(last["stability_score"].mean()), 3),
            "last_health": round(float(last["global_health_score"].mean()), 3),
            "peak_retry_volume": round(float(df["retry_volume"].max()), 2),
            "fragmented_nodes_peak": int(df["fragmented_nodes"].max()),
        }
    except Exception as e:
        return {"error": str(e)}

if __name__ == "__main__":
    async def test():
        print("Running simulation...")
        result = await run_simulation(seed=42)
        print(json.dumps(result, indent=2))
        print("\nReading telemetry...")
        telemetry = await read_telemetry()
        print(json.dumps(telemetry, indent=2))
    asyncio.run(test())
