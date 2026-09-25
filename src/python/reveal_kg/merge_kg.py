"""
Merge multiple knowledge graph SQLite databases (built with the shared
kg_schema.sql) into a single output database.

Source databases and their priority order are defined in a JSON config file
(see merge_config.json). The first source listed wins any label/type
conflict when nodes from different sources merge; see kg_merger.KGMerger
and node_normalizer.NodeNormalizer for the merge rules.

Usage:
    python merge_kg.py -c merge_config.json -O -X -v -l merge.log
"""

import json
import logging
import sys
from argparse import ArgumentParser
from pathlib import Path

from kg_database import DatabaseManager
from kg_merger import KGMerger, SourceSpec
from node_normalizer import NodeNormalizer

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


class _ExcludeWarningFilter(logging.Filter):
    """Keep WARNING-level records off the console; they still go to the log file."""

    def filter(self, record: logging.LogRecord) -> bool:
        return record.levelno != logging.WARNING


def main():
    parser = ArgumentParser(description=__doc__)
    parser.add_argument(
        "-c", "--config", type=str, default="merge_config.json",
        dest="config", help="Merge config JSON file (default: merge_config.json)",
    )
    parser.add_argument(
        "-o", "--output", type=str, default=None,
        dest="output", help="Output SQLite database file (overrides config)",
    )
    parser.add_argument(
        "-b", "--debug-db", type=str, default=None,
        dest="debug_db", help="Debug SQLite database file for node-merge mapping/mismatch details (overrides config)",
    )
    parser.add_argument(
        "-O", "--force-clean-db", action="store_true", dest="force_clean_db",
        help="Remove old output database and start fresh",
    )
    parser.add_argument(
        "-X", "--index", action="store_true", dest="build_index",
        help="Create query performance indexes after merging",
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="Enable verbose logging")
    parser.add_argument("-l", "--log", type=str, dest="log", help="Log file path (optional)")
    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    # Warnings are only useful in full in the log file; keep the console to summary/info/errors.
    for handler in logging.getLogger().handlers:
        handler.addFilter(_ExcludeWarningFilter())

    if args.log:
        file_handler = logging.FileHandler(args.log)
        file_handler.setLevel(logging.DEBUG if args.verbose else logging.INFO)
        file_handler.setFormatter(logging.Formatter("%(asctime)s - %(levelname)s - %(message)s"))
        logging.getLogger().addHandler(file_handler)

    config_path = Path(args.config)
    if not config_path.exists():
        logger.error(f"Merge config file not found: {config_path}")
        sys.exit(1)

    with open(config_path, "r", encoding="utf-8") as f:
        config = json.load(f) or {}

    sources = [SourceSpec(name=s["name"], path=s["path"]) for s in config.get("sources", [])]
    if len(sources) < 2:
        logger.error("Merge config must list at least two sources")
        sys.exit(1)

    missing = [s.path for s in sources if not Path(s.path).exists()]
    if missing:
        logger.error(f"Source database(s) not found: {missing}")
        sys.exit(1)

    output_path = args.output or config.get("output", {}).get("path", "data/MergedKG/merged_kg.sqlite")
    debug_db_path = args.debug_db or config.get("debug_output", {}).get("path", "data/MergedKG/merge_debug.sqlite")
    type_equivalence_path = config.get("type_equivalence_file", "type_equivalence.json")
    identifier_prefix_mapping = config.get("identifier_prefix_mapping", {})

    logger.info(f"Sources (priority order): {[s.name for s in sources]}")
    logger.info(f"Output database: {output_path}")
    logger.info(f"Debug database: {debug_db_path}")

    try:
        normalizer = NodeNormalizer(type_equivalence_path)

        db = DatabaseManager(output_path, force_clean_db=args.force_clean_db)
        db.initialize()

        try:
            merger = KGMerger(
                db, normalizer, sources, debug_db_path=debug_db_path,
                identifier_prefix_mapping=identifier_prefix_mapping,
            )
            merger.run()

            if args.build_index:
                db.create_indexes()
        finally:
            db.disconnect()

        logger.info("Merge completed successfully!")
    except Exception as e:
        logger.error(f"Error during merge: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
