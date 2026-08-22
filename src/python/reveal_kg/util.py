"""
Utility script for analyzing and managing CFDE data CSV files.

Commands:
    config: Generate xref_config.json by analyzing CSV files for decimal columns and sources to exclude
    list-edges: List all edge file headers with folder name and SAB information
    list-nodes: List all node file headers with folder name and SAB information

Usage:
    python util.py config [-f DATA_FOLDER]
    python util.py list-edges [-f DATA_FOLDER]
    python util.py list-nodes [-f DATA_FOLDER]
"""

import argparse
import csv
import json
import logging
import sys
from pathlib import Path
from collections import defaultdict

logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger(__name__)


def find_decimal_columns(data_folder: str = "data/DataDistilleryKG"):
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

                        # Check for PUBMED (exclude from all data)
                        if source == 'PUBMED' and value:
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


def list_edge_headers(data_folder: str = "data/DataDistilleryKG"):
    """
    Crawl through edge files and print headers with folder and SAB information.
    
    Args:
        data_folder: Root folder to search for edge files
    """
    data_path = Path(data_folder)
    
    if not data_path.exists():
        logger.error(f"Data folder not found: {data_path}")
        return
    
    # Find all *.edges.csv files recursively
    edge_files = sorted(data_path.rglob("*.edges.csv"))
    logger.info(f"Found {len(edge_files)} edge files\n")
    
    for csv_path in edge_files:
        # Extract folder name and SAB
        folder_name = csv_path.parent.name
        filename = csv_path.name
        sab = filename.split('.')[0] if '.' in filename else "UNKNOWN"
        
        try:
            with open(csv_path, 'r', encoding='utf-8') as f:
                # Detect delimiter
                first_line = f.readline()
                delimiter = '\t' if '\t' in first_line else ','
                f.seek(0)
                
                reader = csv.reader(f, delimiter=delimiter)
                header = next(reader, None)
                
                if header:
                    # Format output: folder_name | SAB | header columns
                    header_str = " | ".join(header)
                    print(f"{folder_name:30s} | {sab:12s} | {header_str}")
                else:
                    logger.warning(f"No header found in {csv_path}")
                    
        except Exception as e:
            logger.error(f"Error reading {csv_path}: {e}")
            continue


def list_node_headers(data_folder: str = "data/DataDistilleryKG"):
    """
    Crawl through node files and print headers with folder and SAB information.
    
    Args:
        data_folder: Root folder to search for node files
    """
    data_path = Path(data_folder)
    
    if not data_path.exists():
        logger.error(f"Data folder not found: {data_path}")
        return
    
    # Find all *.nodes.csv files recursively
    node_files = sorted(data_path.rglob("*.nodes.csv"))
    logger.info(f"Found {len(node_files)} node files\n")
    
    for csv_path in node_files:
        # Extract folder name and SAB
        folder_name = csv_path.parent.name
        filename = csv_path.name
        sab = filename.split('.')[0] if '.' in filename else "UNKNOWN"
        
        try:
            with open(csv_path, 'r', encoding='utf-8') as f:
                # Detect delimiter
                first_line = f.readline()
                delimiter = '\t' if '\t' in first_line else ','
                f.seek(0)
                
                reader = csv.reader(f, delimiter=delimiter)
                header = next(reader, None)
                
                if header:
                    # Format output: folder_name | SAB | header columns
                    header_str = " | ".join(header)
                    print(f"{folder_name:30s} | {sab:12s} | {header_str}")
                else:
                    logger.warning(f"No header found in {csv_path}")
                    
        except Exception as e:
            logger.error(f"Error reading {csv_path}: {e}")
            continue


def cmd_config(data_folder: str = "data/DataDistilleryKG"):
    """Command: Generate dd_config.json by analyzing CSV files."""
    logger.info("Analyzing CSV files to generate dd_config.json...")
    
    # Analyze data files
    decimal_columns, exclude_sources = find_decimal_columns(data_folder)
    
    logger.info(f"\nSummary:")
    logger.info(f"  Columns with .0 decimals: {decimal_columns}")
    logger.info(f"  Sources to exclude: {exclude_sources}")
    
    # Build config
    config = build_config(decimal_columns, exclude_sources)
    
    # Write to file
    config_path = Path(__file__).parent / "dd_config.json"
    try:
        with open(config_path, 'w') as f:
            json.dump(config, f, indent=2)
        logger.info(f"\nWrote config to {config_path}")
    except Exception as e:
        logger.error(f"Failed to write config: {e}")
        return 1
    
    return 0


def cmd_list_edges(data_folder: str = "data/DataDistilleryKG"):
    """Command: List all edge file headers with folder and SAB information."""
    logger.info(f"Scanning for edge files in {data_folder}...\n")
    list_edge_headers(data_folder)
    return 0


def cmd_list_nodes(data_folder: str = "data/DataDistilleryKG"):
    """Command: List all node file headers with folder and SAB information."""
    logger.info(f"Scanning for node files in {data_folder}...\n")
    list_node_headers(data_folder)
    return 0


def main():
    """Main entry point with CLI argument parsing."""
    parser = argparse.ArgumentParser(
        description="Utility script for analyzing CFDE data CSV files and generating dd_config.json"
    )
    
    subparsers = parser.add_subparsers(dest="command", help="Command to run")
    
    # Config command
    config_parser = subparsers.add_parser(
        "config",
        help="Generate dd_config.json by analyzing CSV files"
    )
    config_parser.add_argument(
        "-f",
        "--folder",
        type=str,
        default="data/DataDistilleryKG",
        dest="data_folder",
        help="Data folder to analyze (default: data/DataDistilleryKG)",
    )
    
    # List-edges command
    edges_parser = subparsers.add_parser(
        "list-edges",
        help="List all edge file headers with folder and SAB information"
    )
    edges_parser.add_argument(
        "-f",
        "--folder",
        type=str,
        default="data/DataDistilleryKG",
        dest="data_folder",
        help="Data folder to search (default: data/DataDistilleryKG)",
    )
    
    # List-nodes command
    nodes_parser = subparsers.add_parser(
        "list-nodes",
        help="List all node file headers with folder and SAB information"
    )
    nodes_parser.add_argument(
        "-f",
        "--folder",
        type=str,
        default="data/DataDistilleryKG",
        dest="data_folder",
        help="Data folder to search (default: data/DataDistilleryKG)",
    )
    
    args = parser.parse_args()
    
    # Dispatch to appropriate command
    if args.command == "config":
        return cmd_config(args.data_folder)
    elif args.command == "list-edges":
        return cmd_list_edges(args.data_folder)
    elif args.command == "list-nodes":
        return cmd_list_nodes(args.data_folder)
    else:
        parser.print_help()
        return 0


if __name__ == "__main__":
    sys.exit(main())
