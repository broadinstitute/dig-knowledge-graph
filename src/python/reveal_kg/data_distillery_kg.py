"""
CFDE REVEAL Knowledge Graph Data Distillery for Knowledge Commons.

This module provides CLI utilities to download and process CFDE data.
"""

import logging
import sys
from argparse import ArgumentParser
from pathlib import Path

from dd_download import DataDownloader
from dd_build_db import DatabaseManager, DataBuilder

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
        default="data/DataDistilleryKG/download",
        dest="download_folder",
        help="Folder for downloaded and extracted files (default: data/download)",
    )
    parser.add_argument(
        "-i",
        "--input-folder",
        type=str,
        default="data/DataDistilleryKG/download",
        dest="input_folder",
        help="Input folder with CSV files for processing (default: data/download)",
    )
    parser.add_argument(
        "-o",
        "--output",
        type=str,
        default="data/DataDistilleryKG/ddkg.sqlite",
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
    parser.add_argument(
        "-X",
        "--index",
        action="store_true",
        dest="build_index",
        help="Create query performance indexes after loading (recommended for multi-folder builds)",
    )
    parser.add_argument(
        "-I",
        "--all-folders",
        action="store_true",
        dest="process_all",
        help="Process all downloaded/extracted folders in the download folder",
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
    downloaded = False
    if args.download or args.force_download:
        # Ensure download folder exists
        download_path = Path(args.download_folder)
        download_path.mkdir(parents=True, exist_ok=True)
        logger.info(f"Using download folder: {download_path.resolve()}")
        
        downloader = DataDownloader()
        try:
            downloader.download_and_extract_all(
                output_dir=args.download_folder,
                force_download=args.force_download,
            )
            downloaded = True
        except KeyboardInterrupt:
            logger.info("Download interrupted by user")
            sys.exit(1)
        except Exception as e:
            logger.error(f"Download error: {e}")
            sys.exit(1)

    # Only build database if we have data to process
    should_build = (
        downloaded or 
        args.process_all or 
        Path(args.input_folder).exists()
    )
    
    if not should_build:
        logger.warning(
            f"No data to process. "
            f"Use -d/-D to download files, -I to process all folders, "
            f"or -i with an existing folder path."
        )
        sys.exit(0)

    # Build the database
    db = DatabaseManager(db_path=args.output, force_clean_db=args.force_clean_db)
    builder = DataBuilder(db)
    
    # Determine if indexes should be created
    # True if: -X flag explicitly passed OR processing all folders with -I
    build_indexes = args.build_index or args.process_all
    
    if args.process_all:
        # Process all folders found in download_folder
        logger.info(f"Processing all folders in {args.download_folder}")
        download_path = Path(args.download_folder)
        
        # Create folder if it doesn't exist (will be empty, checked below)
        download_path.mkdir(parents=True, exist_ok=True)
        
        # Find all subdirectories that contain CSV files
        csv_folders = set()
        for csv_file in download_path.rglob("*.nodes.csv"):
            # Add the top-level folder under download_path
            csv_folders.add(csv_file.parent)
        
        if not csv_folders:
            logger.warning(f"No CSV files found in {download_path}")
            sys.exit(1)
        
        logger.info(f"Found {len(csv_folders)} folder(s) with CSV files")
        
        # Process all folders into the same database
        try:
            # Initialize database once (schema created, old db cleaned if -O)
            db.initialize()
            
            # Load data from all folders
            for folder in sorted(csv_folders):
                logger.info(f"Processing {folder.name}...")
                builder.load_folder(str(folder))
            
            # Create indexes after all data is loaded
            if build_indexes:
                db.create_indexes()
                
            logger.info("All folders processed successfully")
        except KeyboardInterrupt:
            logger.info("Build interrupted by user")
            sys.exit(1)
        except Exception as e:
            logger.error(f"Build error: {e}")
            sys.exit(1)
        finally:
            db.disconnect()
    else:
        # Process single folder specified by -i
        logger.info(f"Processing {args.input_folder}")
        try:
            # Initialize database (schema created, old db cleaned if -O)
            db.initialize()
            
            # Load data from single folder
            builder.load_folder(args.input_folder)
            
            # Create indexes if requested
            if build_indexes:
                db.create_indexes()
                
            logger.info("Folder processed successfully")
        except KeyboardInterrupt:
            logger.info("Build interrupted by user")
            sys.exit(1)
        except Exception as e:
            logger.error(f"Build error: {e}")
            sys.exit(1)
        finally:
            db.disconnect()


if __name__ == "__main__":
    main()

