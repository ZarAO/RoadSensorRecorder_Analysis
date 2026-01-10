"""
Road Quality Analyzer - Thin wrapper for road_quality_analyzer package


Використання:
  python main.py --input <csv_file> --out <output_dir>
  
Або напряму:
  python -m road_quality_analyzer analyze --input <csv_file> --out <output_dir>
"""

import sys
import argparse
import subprocess
from pathlib import Path
from datetime import datetime


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
        data_dir = Path("data")
        csv_files = list(data_dir.glob("sensor_data_*.csv"))
        if not csv_files:
            print("ERROR: Немає CSV файлів у папці data/")
            print("Використовуйте: python main.py --input <path_to_csv>")
            sys.exit(1)
        
        input_file = max(csv_files, key=lambda p: p.stat().st_mtime)
        print(f"\n[Auto-detected] Input: {input_file}")
    else:
        print(f"\n[User-specified] Input: {input_file}")
    
    # Auto-generate output directory if not provided
    if output_dir is None:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_dir = Path("results") / f"results_{timestamp}"
        print(f"[Auto-generated] Output: {output_dir}")
    else:
        print(f"[User-specified] Output: {output_dir}")
    
    # Run analyzer
    cmd = [
        sys.executable, "-m", "road_quality_analyzer", "analyze",
        "--input", str(input_file),
        "--out", str(output_dir)
    ]
    
    print("\n" + "=" * 70)
    print("Running analysis...")
    print("=" * 70 + "\n")
    
    result = subprocess.run(cmd)
    
    if result.returncode == 0:
        print("\n" + "=" * 70)
        print(f"✓ SUCCESS: Results saved to {output_dir}")
        print("=" * 70)
    else:
        print("\n" + "=" * 70)
        print("✗ ERROR: Analysis failed")
        print("=" * 70)
        sys.exit(1)


def main():
    """
    Entry point - thin wrapper for road_quality_analyzer
    """
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

For legacy code:
  See archive/legacy_snapshot/
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
