"""
CFDE REVEAL Knowledge Graph Data Distillery for Knowledge Commons.

This module provides CLI utilities to download and process CFDE data.
"""

import logging
import sys
from argparse import ArgumentParser
from pathlib import Path

from dd_download import DataDownloader
from dd_build_db import DatabaseBuilder

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


def main():
    """Main entry point."""
    parser = ArgumentParser(
        description="CFDE Data Distillery - Download, extract, and build knowledge graph database"
    )
    parser.add_argument(
        "-d",
        "--download",
        action="store_true",
        dest="download",
        help="Download files if not yet processed (extracted)",
    )
    parser.add_argument(
        "-D",
        "--force-download",
        action="store_true",
        dest="force_download",
        help="Force re-download and re-extract all files",
    )
    parser.add_argument(
        "-f",
        "--download-folder",
        type=str,
        default="data/download",
        dest="download_folder",
        help="Folder for downloaded and extracted files (default: data/download)",
    )
    parser.add_argument(
        "-i",
        "--input-folder",
        type=str,
        default="data/download",
        dest="input_folder",
        help="Input folder with CSV files for processing (default: data/download)",
    )
    parser.add_argument(
        "-o",
        "--output",
        type=str,
        default="data/ddkg.sqlite",
        dest="output",
        help="Output SQLite database file (default: data/ddkg.sqlite)",
    )
    parser.add_argument(
        "-l",
        "--log",
        type=str,
        dest="log",
        help="Log file path (optional)",
    )
    parser.add_argument(
        "-O",
        "--force-clean-db",
        action="store_true",
        dest="force_clean_db",
        help="Remove old database and start fresh",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Enable verbose logging",
    )

    args = parser.parse_args()

    # Set logging level
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    # Add file handler if log file specified
    if args.log:
        file_handler = logging.FileHandler(args.log)
        file_handler.setLevel(logging.DEBUG if args.verbose else logging.INFO)
        formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
        file_handler.setFormatter(formatter)
        logging.getLogger().addHandler(file_handler)

    # Download if requested
    if args.download or args.force_download:
        downloader = DataDownloader()
        try:
            downloader.download_and_extract_all(
                output_dir=args.download_folder,
                force_download=args.force_download,
            )
        except KeyboardInterrupt:
            logger.info("Download interrupted by user")
            sys.exit(1)
        except Exception as e:
            logger.error(f"Download error: {e}")
            sys.exit(1)

    # Always build the database
    builder = DatabaseBuilder(db_path=args.output, force_clean_db=args.force_clean_db)
    try:
        builder.build(data_folder=args.input_folder)
    except KeyboardInterrupt:
        logger.info("Build interrupted by user")
        sys.exit(1)
    except Exception as e:
        logger.error(f"Build error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()

