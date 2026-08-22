"""
Download and extract functions for CFDE data from dd-kg-ui.cfde.cloud/downloads.

This module provides the DataDownloader class for downloading and extracting zip files.
"""

import csv
import logging
import shutil
import sys
import zipfile
from pathlib import Path
from typing import List
from urllib.parse import urlparse

logger = logging.getLogger(__name__)


class DataDownloader:
    """Handle downloading and extracting zip files from a TSV source list."""

    def __init__(self, tsv_file: str = "data/DataDistilleryKG/DataDistillerySources.tsv"):
        """
        Initialize the downloader.

        Args:
            tsv_file: Path to TSV file with download links
        """
        self.tsv_file = Path(tsv_file)
        if not self.tsv_file.exists():
            raise FileNotFoundError(f"TSV file not found: {tsv_file}")

    def parse_download_links(self) -> List[str]:
        """
        Parse zip file links from the TSV file.

        Returns:
            List of URLs to zip files
        """
        logger.info(f"Reading download links from {self.tsv_file}")
        links = []

        try:
            with open(self.tsv_file, 'r', encoding='utf-8') as f:
                reader = csv.DictReader(f, delimiter='\t')
                
                # Verify that 'URL' column exists
                if reader.fieldnames is None or 'URL' not in reader.fieldnames:
                    logger.error(f"'URL' column not found in {self.tsv_file}")
                    logger.error(f"Available columns: {reader.fieldnames}")
                    raise ValueError("'URL' column not found in TSV file")
                
                for row in reader:
                    url = row.get('URL', '').strip()
                    if url and url.endswith('.zip'):
                        links.append(url)
                        logger.debug(f"Found zip link: {url}")

        except Exception as e:
            logger.error(f"Failed to parse TSV file: {e}")
            raise

        logger.info(f"Found {len(links)} zip file links")
        return links

    def download_file(self, url: str, destination: Path) -> bool:
        """
        Download a file from a URL.

        Args:
            url: URL to download from
            destination: Path where to save the file

        Returns:
            True if successful, False otherwise
        """
        try:
            import requests
            filename = urlparse(url).path.split("/")[-1]
            logger.info(f"Downloading {filename}...")

            response = requests.get(url, timeout=30, stream=True)
            response.raise_for_status()

            # Ensure parent directory exists
            destination.parent.mkdir(parents=True, exist_ok=True)

            # Download with progress
            total_size = int(response.headers.get("content-length", 0))
            downloaded = 0

            with open(destination, "wb") as f:
                for chunk in response.iter_content(chunk_size=1024*1024):
                    if chunk:
                        f.write(chunk)
                        downloaded += len(chunk)

            logger.info(f"Successfully downloaded {filename}")
            return True

        except Exception as e:
            logger.error(f"Failed to download {url}: {e}")
            return False

    def extract_zip(self, zip_path: Path, extract_to: Path) -> bool:
        """
        Extract a zip file.

        Args:
            zip_path: Path to the zip file
            extract_to: Directory to extract to

        Returns:
            True if successful, False otherwise
        """
        try:
            logger.info(f"Extracting {zip_path.name} to {extract_to}...")
            extract_to.mkdir(parents=True, exist_ok=True)

            with zipfile.ZipFile(zip_path, "r") as zip_ref:
                zip_ref.extractall(extract_to)

            logger.info(f"Successfully extracted {zip_path.name}")
            return True

        except zipfile.BadZipFile as e:
            logger.error(f"Invalid zip file {zip_path.name}: {e}")
            # Clean up partial extraction
            if extract_to.exists():
                shutil.rmtree(extract_to)
                logger.info(f"Removed partial extraction directory: {extract_to}")
            return False
        except Exception as e:
            logger.error(f"Failed to extract {zip_path.name}: {e}")
            # Clean up partial extraction
            if extract_to.exists():
                shutil.rmtree(extract_to)
                logger.info(f"Removed partial extraction directory: {extract_to}")
            return False

    def move_zip_to_subfolder(self, zip_path: Path, zip_subfolder: Path) -> bool:
        """
        Move a zip file to a subfolder.

        Args:
            zip_path: Path to the zip file
            zip_subfolder: Path to the zip subfolder

        Returns:
            True if successful, False otherwise
        """
        try:
            zip_subfolder.mkdir(parents=True, exist_ok=True)
            destination = zip_subfolder / zip_path.name
            shutil.move(str(zip_path), str(destination))
            logger.info(f"Moved {zip_path.name} to {zip_subfolder.name}/")
            return True
        except Exception as e:
            logger.error(f"Failed to move {zip_path.name}: {e}")
            return False

    def download_and_extract_all(
        self,
        output_dir: Path,
        force_download: bool = False,
    ) -> None:
        """
        Download and extract all zip files.

        Args:
            output_dir: Directory to extract files to
            force_download: If True, re-download even if files exist
        """
        output_dir = Path(output_dir)
        zip_subfolder = output_dir / "zip"

        # Parse links
        try:
            links = self.parse_download_links()
        except Exception as e:
            logger.error(f"Failed to parse links: {e}")
            sys.exit(1)

        if not links:
            logger.error("No zip files found on the download page")
            sys.exit(1)

        # Download and extract each file
        successful = 0
        failed = 0

        for url in links:
            filename = urlparse(url).path.split("/")[-1]
            zip_path = output_dir / filename
            extract_dir = output_dir / filename.replace(".zip", "")

            # Check if file has already been processed (extracted)
            if extract_dir.exists() and not force_download:
                logger.info(f"{extract_dir.name}/ already exists, skipping download")
                successful += 1
            else:
                # Download file
                if self.download_file(url, zip_path):
                    # Extract file
                    if self.extract_zip(zip_path, extract_dir):
                        # Move zip to subfolder
                        if self.move_zip_to_subfolder(zip_path, zip_subfolder):
                            successful += 1
                        else:
                            failed += 1
                    else:
                        failed += 1
                else:
                    failed += 1

        # Summary
        logger.info(f"\n{'='*60}")
        logger.info(f"Download and extraction complete!")
        logger.info(f"Successful: {successful}/{len(links)}")
        logger.info(f"Failed: {failed}/{len(links)}")
        logger.info(f"Files extracted to: {output_dir}")
        logger.info(f"Zip files moved to: {zip_subfolder}")
        logger.info(f"{'='*60}\n")

        if failed > 0:
            sys.exit(1)
