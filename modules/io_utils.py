import pandas as pd
import os, glob
from datetime import datetime

def load_data(path: str | None = None, initial_dir: str = "data"):
    if path is None:
        data_dir = os.path.join(os.getcwd(), initial_dir)
        candidates = sorted(
            glob.glob(os.path.join(data_dir, "*.csv")),
            key=os.path.getmtime
        )
        if not candidates:
            raise FileNotFoundError(
                f"Не знайдено жодного CSV у '{data_dir}'. "
                f"Передай шлях: load_data(path='data/your_file.csv')."
            )
        path = candidates[-1]  # найновіший файл
    return pd.read_csv(path)

def create_results_directory(path="results"):
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    results_dir = os.path.join(path, f"results_{timestamp}")
    os.makedirs(results_dir, exist_ok=True)
    return results_dir