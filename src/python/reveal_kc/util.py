"""
Utility script to generate xref_config.json by analyzing CSV files.

Crawls through data/download folder, reads all node files, and identifies:
- Columns with decimal values that look like integers (e.g., 916.0)
- Sources to exclude (e.g., SNOMEDCT_US)

Usage:
    python util.py
"""

import csv
import json
import logging
import sys
from pathlib import Path
from collections import defaultdict

logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger(__name__)


def find_decimal_columns(data_folder: str = "data/download"):
    """
    Analyze node CSV files to find columns with decimal values.
    
    Returns:
        decimal_columns: dict mapping SAB -> set of column names with .0 values
        exclude_sources: dict mapping SAB -> set of sources to exclude (e.g., SNOMEDCT_US)
    """
    data_path = Path(data_folder)
    
    if not data_path.exists():
        logger.error(f"Data folder not found: {data_path}")
        return {}, {}
    
    decimal_columns = defaultdict(set)
    exclude_sources = defaultdict(set)
    
    # Find all *.nodes.csv files recursively
    node_files = list(data_path.rglob("*.nodes.csv"))
    logger.info(f"Found {len(node_files)} node files")
    
    for csv_path in sorted(node_files):
        # Extract SAB from filename (e.g., "SPARC.Anatomy.nodes.csv" -> "SPARC")
        filename = csv_path.name
        sab = filename.split('.')[0] if '.' in filename else None
        
        if not sab:
            logger.warning(f"Could not extract SAB from filename: {filename}")
            continue
        
        logger.info(f"Processing {filename} (SAB: {sab})")
        
        try:
            with open(csv_path, 'r', encoding='utf-8') as f:
                # Detect delimiter
                first_line = f.readline()
                delimiter = '\t' if '\t' in first_line else ','
                f.seek(0)
                
                reader = csv.DictReader(f, delimiter=delimiter)
                fieldnames = reader.fieldnames
                
                if not fieldnames:
                    logger.warning(f"No fieldnames in {filename}")
                    continue
                
                # Columns 3+ are xref sources (columns 0=node_id, 1=name, 2=type)
                xref_sources = fieldnames[3:] if len(fieldnames) > 3 else []
                
                # Track decimal columns and exclude sources
                decimal_candidates = defaultdict(int)  # Column -> count of .0 values
                found_exclude_sources = set()
                
                for row_num, row in enumerate(reader, 1):
                    for source in xref_sources:
                        value = row.get(source, '').strip()
                        
                        # Check for SNOMEDCT_US (exclude from all data)
                        if source == 'SNOMEDCT_US' and value:
                            found_exclude_sources.add(source)
                        
                        # Check for decimal pattern (e.g., 916.0, 123.0)
                        if value and '.' in value:
                            try:
                                float_val = float(value)
                                # Check if it's an integer value with .0 decimal
                                if float_val == int(float_val):
                                    decimal_candidates[source] += 1
                            except ValueError:
                                pass  # Not numeric, skip
                
                # If column had mostly .0 values, add to decimal_columns
                # (threshold: at least 1 value found, or 90% of non-empty values)
                for source, count in decimal_candidates.items():
                    decimal_columns[sab].add(source)
                    logger.debug(f"  Found {count} decimal values in {source}")
                
                if found_exclude_sources:
                    exclude_sources[sab].update(found_exclude_sources)
                    logger.info(f"  Found sources to exclude: {found_exclude_sources}")
                    
        except Exception as e:
            logger.error(f"Error processing {filename}: {e}")
            continue
    
    return dict(decimal_columns), dict(exclude_sources)


def build_config(decimal_columns: dict, exclude_sources: dict):
    """
    Build xref_config dict from analysis results.
    
    Args:
        decimal_columns: dict mapping SAB -> set of column names with .0 values
        exclude_sources: dict mapping SAB -> set of sources to exclude
    
    Returns:
        config: dict ready to be written as JSON
    """
    config = {"xref_processing": [], "xref_exclude": {}}
    
    # Build remove_decimal rule
    if decimal_columns:
        remove_decimal_sources = {}
        for sab, sources in decimal_columns.items():
            if sources:
                remove_decimal_sources[sab] = sorted(list(sources))
        
        if remove_decimal_sources:
            config["xref_processing"].append({
                "type": "remove_decimal",
                "description": "Identifiers are integers, remove .0 suffix",
                "sources": remove_decimal_sources
            })
    
    # Build exclude rules
    if exclude_sources:
        for sab, sources in exclude_sources.items():
            if sources:
                config["xref_exclude"][sab] = sorted(list(sources))
    
    return config


def main():
    """Main entry point."""
    logger.info("Analyzing CSV files to generate xref_config.json...")
    
    # Analyze data files
    decimal_columns, exclude_sources = find_decimal_columns()
    
    logger.info(f"\nSummary:")
    logger.info(f"  Columns with .0 decimals: {decimal_columns}")
    logger.info(f"  Sources to exclude: {exclude_sources}")
    
    # Build config
    config = build_config(decimal_columns, exclude_sources)
    
    # Write to file
    config_path = Path(__file__).parent / "xref_config.json"
    try:
        with open(config_path, 'w') as f:
            json.dump(config, f, indent=2)
        logger.info(f"\nWrote config to {config_path}")
        logger.info(f"Config contents:\n{json.dumps(config, indent=2)}")
    except Exception as e:
        logger.error(f"Failed to write config: {e}")
        return 1
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
