"""
One-off utility to inspect distinct node `type` values (with counts) across
the existing KG databases, to help design the merge type-equivalence config.

Usage:
    python utils/inspect_node_types.py
    python utils/inspect_node_types.py --limit 200
"""

import argparse
import sqlite3
from pathlib import Path

DBS = {
    "DataDistillery": "data/DataDistilleryKG/CFDE-DD-KG.sqlite",
    "REVEAL": "data/REVEALKG/CFDE_REVEAL_KG.sqlite",
    "Biomarker": "data/BiomarkerKG/CFDE_Biomarker_KG.sqlite",
}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=100, help="Max distinct types to show per DB")
    args = parser.parse_args()

    for name, path in DBS.items():
        print(f"=== {name} ({path}) ===")
        if not Path(path).exists():
            print(f"  [missing] {path}")
            print()
            continue

        con = sqlite3.connect(path)
        try:
            rows = con.execute(
                "SELECT type, COUNT(*) c FROM nodes GROUP BY type ORDER BY c DESC LIMIT ?",
                (args.limit,),
            ).fetchall()
            for node_type, count in rows:
                print(f"  {node_type!r}: {count}")
        finally:
            con.close()
        print()


if __name__ == "__main__":
    main()
