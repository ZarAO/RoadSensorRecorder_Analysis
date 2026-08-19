"""
Road Quality Analyzer - Thin wrapper for road_quality_analyzer package


Usage:
  python main.py --input <csv_file> --out <output_dir>

Or directly:
  python -m road_quality_analyzer analyze --input <csv_file> --out <output_dir>
"""

import sys
import argparse
from pathlib import Path
from datetime import datetime

from road_quality_analyzer.cli import analyze

# Default data/ and results/ are tied to the project, not to the current directory
PROJECT_ROOT = Path(__file__).resolve().parent


def run_analysis(input_file: str = None, output_dir: str = None):
    """
    Run road_quality_analyzer pipeline

    Args:
        input_file: Path to sensor CSV (auto-detect latest if None)
        output_dir: Output directory (auto-generate if None)
    """
    print("=" * 70)
    print("Road Quality Analyzer")
    print("=" * 70)

    # Auto-detect latest CSV if not provided
    if input_file is None:
        data_dir = PROJECT_ROOT / "data"
        csv_files = list(data_dir.glob("sensor_data_*.csv"))
        if not csv_files:
            print(f"ERROR: Немає CSV файлів у папці {data_dir}")
            print("Використовуйте: python main.py --input <path_to_csv>")
            sys.exit(1)

        input_file = max(csv_files, key=lambda p: p.stat().st_mtime)
        print(f"\n[Auto-detected] Input: {input_file}")
    else:
        input_file = Path(input_file)
        if not input_file.exists():
            print(f"ERROR: Вхідний файл не знайдено: {input_file}")
            sys.exit(1)
        print(f"\n[User-specified] Input: {input_file}")

    # Auto-generate output directory if not provided
    if output_dir is None:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_dir = PROJECT_ROOT / "results" / f"results_{timestamp}"
        print(f"[Auto-generated] Output: {output_dir}")
    else:
        print(f"[User-specified] Output: {output_dir}")

    print("\n" + "=" * 70)
    print("Running analysis...")
    print("=" * 70 + "\n")

    analyze(str(input_file), str(output_dir))

    print("\n" + "=" * 70)
    print(f"✓ SUCCESS: Results saved to {output_dir}")
    print("=" * 70)


def main():
    """
    Entry point - thin wrapper for road_quality_analyzer
    """
    # Progress output contains Cyrillic and check marks: redirected stdout crashes without UTF-8
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')

    parser = argparse.ArgumentParser(
        description='Road Quality Analyzer - Smartphone IRI estimation',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python main.py --input data/sensor_data_20250729.csv
  python main.py --input data/sensor_data_20250729.csv --out results/my_run
  python main.py  # Auto-detect latest CSV

For full CLI options:
  python -m road_quality_analyzer analyze --help
        """
    )
    parser.add_argument(
        '--input',
        type=str,
        default=None,
        help='Input CSV file (auto-detect if not specified)'
    )
    parser.add_argument(
        '--out',
        type=str,
        default=None,
        help='Output directory (auto-generate if not specified)'
    )
    
    args = parser.parse_args()
    
    run_analysis(input_file=args.input, output_dir=args.out)


if __name__ == "__main__":
    main()
