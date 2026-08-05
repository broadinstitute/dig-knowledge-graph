"""
CFDE REVEAL Knowledge Graph Data Distillery for Knowledge Commons.

This module provides CLI utilities to download and process CFDE data.
"""

import logging
import sys
from argparse import ArgumentParser
from pathlib import Path

from dd_download import DataDownloader

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


def main():
    """Main entry point."""
    parser = ArgumentParser(
        description="Download and extract CFDE data from DataDistillerySources.tsv"
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
        "--folder",
        type=str,
        default="data/download",
        dest="folder",
        help="Output folder for extracted files (default: data/download)",
    )
    parser.add_argument(
        "-l",
        "--log",
        type=str,
        dest="log",
        help="Log file path (optional)",
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

    # Check if either download flag is set
    if not args.download and not args.force_download:
        parser.print_help()
        sys.exit(0)

    # Create downloader and run
    downloader = DataDownloader()
    try:
        downloader.download_and_extract_all(
            output_dir=args.folder,
            force_download=args.force_download,
        )
    except KeyboardInterrupt:
        logger.info("Download interrupted by user")
        sys.exit(1)
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()

