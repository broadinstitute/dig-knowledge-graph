"""
Biomarker Knowledge Graph loader with CLI interface.

Loads biomarker CSV data into the normalized SQLite database.
Uses DatabaseManager for database lifecycle and BiomarkerDataBuilder for data loading.
Follows config-driven semantic type mapping from biomarker_config.yaml.
"""

import csv
import logging
import sqlite3
import sys
import uuid
import yaml
from argparse import ArgumentParser
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from kg_database import DatabaseManager

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


class BiomarkerDataBuilder:
    """Build biomarker knowledge graph data from CSV files into database."""

    def __init__(self, database_manager: DatabaseManager, config: dict):
        """
        Initialize the data builder.

        Args:
            database_manager: DatabaseManager instance to use for operations
            config: Configuration dictionary from biomarker_config.yaml
        """
        self.db = database_manager
        self.config = config
        self.node_types = config['nodes']['types']
        self.sab_default = config['edges']['default_sab']
        self.batch_size = config['loading']['batch_size']
        self.skip_duplicates = config['loading']['skip_duplicates']
        
        self.node_id_mapping: Dict[str, str] = {}  # original_id -> UUID
        self.node_cache: set = set()  # node_ids already in DB

    def load_folder(self, folder_path: str):
        """
        Load all CSV data from a folder into the database.
        
        Assumes database is already initialized and connected.

        Args:
            folder_path: Path to folder containing CSV files
        """
        folder = Path(folder_path)
        if not folder.exists():
            logger.error(f"Folder not found: {folder_path}")
            raise FileNotFoundError(f"Folder not found: {folder_path}")

        logger.info(f"Loading data from folder: {folder_path}")

        # Find all CSV files matching patterns
        node_files = sorted(folder.glob("**/*.nodes.csv"))
        edge_files = sorted(folder.glob("**/*.edges.csv"))

        if not node_files and not edge_files:
            logger.warning(f"No CSV files found in {folder_path}")
            return

        # Load node files
        for csv_file in node_files:
            # Extract node type from filename (e.g., "HGNC.nodes.csv" -> "HGNC")
            node_type_name = csv_file.stem.split('.')[0]
            
            if node_type_name not in self.node_types:
                logger.warning(f"Unknown node type: {node_type_name}, skipping {csv_file.name}")
                continue
            
            node_type = self.node_types[node_type_name]
            logger.info(f"Loading nodes from {csv_file.name} (type: {node_type})")
            self._load_nodes_from_file(str(csv_file), node_type)

        # Build mapping from original IDs to UUIDs for edge loading
        self._build_node_id_mapping()

        # Load edge files
        for csv_file in edge_files:
            logger.info(f"Loading edges from {csv_file.name}")
            self._load_edges_from_file(str(csv_file))

        logger.info("Data loading completed")

    def _load_nodes_from_file(self, csv_path: str, node_type: str):
        """Load nodes from a CSV file."""
        try:
            with open(csv_path, 'r', encoding='utf-8') as f:
                # Detect delimiter
                first_line = f.readline()
                f.seek(0)
                delimiter = '\t' if '\t' in first_line else ','
                
                reader = csv.DictReader(f, delimiter=delimiter)
                self._load_nodes(reader, csv_path, node_type)
        except Exception as e:
            logger.error(f"Failed to load {csv_path}: {e}")
            raise

    def _load_nodes(self, reader, csv_path: str, node_type: str):
        """Load nodes from CSV reader with UUID generation and batch processing."""
        count = 0
        batch: List[Tuple[str, str, str]] = []
        identifiers_batch: List[Tuple[str, str, str]] = []
        assert self.db.cursor is not None and self.db.conn is not None
        
        try:
            for row_num, row in enumerate(reader, 1):
                original_id = (row.get('id') or row.get('node_id') or '').strip()
                label = (row.get('label') or row.get('name') or '').strip()
                
                # Skip rows with empty original_id
                if not original_id:
                    continue
                
                # Skip if already loaded and skip_duplicates is enabled
                if self.skip_duplicates and original_id in self.node_cache:
                    continue
                
                # Use original_id as fallback if label is empty
                if not label:
                    label = original_id
                
                # Generate UUID for this node
                node_uuid = str(uuid.uuid4())
                
                # Extract identifier type from original_id (prefix before ':')
                identifier_type = original_id.split(':')[0] if ':' in original_id else 'unknown'
                
                batch.append((node_uuid, node_type, label))
                identifiers_batch.append((node_uuid, identifier_type, original_id))
                self.node_cache.add(original_id)
                count += 1
                
                # Insert batch when it reaches batch_size
                if len(batch) >= self.batch_size:
                    self._insert_nodes_batch(batch, identifiers_batch)
                    batch = []
                    identifiers_batch = []
            
            # Insert remaining batch
            if batch:
                self._insert_nodes_batch(batch, identifiers_batch)
            
            logger.info(f"Loaded {count} nodes from {csv_path}")
        except Exception as e:
            logger.error(f"Failed to load nodes: {e}")
            self.db.conn.rollback()
            raise

    def _insert_nodes_batch(self, batch: List[Tuple[str, str, str]], identifiers_batch: List[Tuple[str, str, str]]):
        """Insert a batch of nodes and their identifiers."""
        assert self.db.cursor is not None and self.db.conn is not None
        try:
            self.db.cursor.executemany(
                'INSERT OR IGNORE INTO nodes (node_id, type, label) VALUES (?, ?, ?)',
                batch
            )
            self.db.cursor.executemany(
                'INSERT OR IGNORE INTO identifiers (node_id, identifier_type, identifier_value) VALUES (?, ?, ?)',
                identifiers_batch
            )
            self.db.conn.commit()
        except sqlite3.IntegrityError as e:
            logger.error(f"Error inserting nodes batch: {e}")
            self.db.conn.rollback()

    def _build_node_id_mapping(self):
        """Build mapping from original node IDs to UUIDs from identifiers table."""
        assert self.db.cursor is not None
        
        try:
            self.db.cursor.execute('SELECT identifier_value, node_id FROM identifiers')
            for original_id, node_uuid in self.db.cursor.fetchall():
                self.node_id_mapping[original_id] = node_uuid
            logger.info(f"Built mapping for {len(self.node_id_mapping)} node identifiers")
        except Exception as e:
            logger.error(f"Error building node ID mapping: {e}")
            raise

    def _load_edges_from_file(self, csv_path: str):
        """Load edges from a CSV file."""
        try:
            with open(csv_path, 'r', encoding='utf-8') as f:
                # Detect delimiter
                first_line = f.readline()
                f.seek(0)
                delimiter = '\t' if '\t' in first_line else ','
                
                reader = csv.DictReader(f, delimiter=delimiter)
                self._load_edges(reader, csv_path)
        except Exception as e:
            logger.error(f"Failed to load {csv_path}: {e}")
            raise

    def _load_edges(self, reader, csv_path: str):
        """Load edges from CSV reader using UUID mappings and batch processing."""
        count = 0
        missing_nodes_count = 0
        batch: List[Tuple[str, str, str, str]] = []
        assert self.db.cursor is not None and self.db.conn is not None
        
        try:
            for row_num, row in enumerate(reader, 1):
                source_orig = row.get('source', '').strip()
                target_orig = row.get('target', '').strip()
                # Handle case-insensitive column names for relation and SAB
                predicate = (row.get('relation', '') or row.get('Relation', '')).strip()
                sab = (row.get('SAB', '') or row.get('sab', '') or self.sab_default).strip()
                
                # Skip rows with empty source or target
                if not source_orig or not target_orig:
                    continue
                
                # Map original node IDs to UUIDs
                source_uuid = self.node_id_mapping.get(source_orig)
                target_uuid = self.node_id_mapping.get(target_orig)
                
                if not source_uuid:
                    logger.debug(f"Source node not found: {source_orig}")
                    missing_nodes_count += 1
                    continue
                if not target_uuid:
                    logger.debug(f"Target node not found: {target_orig}")
                    missing_nodes_count += 1
                    continue
                
                batch.append((source_uuid, predicate, target_uuid, sab))
                count += 1
                
                # Insert batch when it reaches batch_size
                if len(batch) >= self.batch_size:
                    self._insert_edges_batch(batch)
                    batch = []
            
            # Insert remaining batch
            if batch:
                self._insert_edges_batch(batch)
            
            if missing_nodes_count > 0:
                logger.warning(f"Loaded {count} edges from {csv_path} "
                              f"(skipped {missing_nodes_count} edges with missing nodes)")
            else:
                logger.info(f"Loaded {count} edges from {csv_path}")
        except Exception as e:
            logger.error(f"Failed to load edges: {e}")
            self.db.conn.rollback()
            raise

    def _insert_edges_batch(self, batch: List[Tuple[str, str, str, str]]):
        """Insert a batch of edges."""
        assert self.db.cursor is not None and self.db.conn is not None
        try:
            self.db.cursor.executemany(
                'INSERT OR IGNORE INTO edges (source_node_id, predicate, target_node_id, sab) VALUES (?, ?, ?, ?)',
                batch
            )
            self.db.conn.commit()
        except sqlite3.IntegrityError as e:
            logger.error(f"Error inserting edges batch: {e}")
            self.db.conn.rollback()


def main():
    """Main entry point with CLI interface."""
    parser = ArgumentParser(
        description="Biomarker Knowledge Graph - Load CSV data into normalized SQLite database"
    )
    parser.add_argument(
        "-i",
        "--input-folder",
        type=str,
        required=True,
        dest="input_folder",
        help="Input folder with CSV files (required)",
    )
    parser.add_argument(
        "-o",
        "--output",
        type=str,
        default="data/biomarker_kg.sqlite",
        dest="output",
        help="Output SQLite database file (default: data/biomarker_kg.sqlite)",
    )
    parser.add_argument(
        "-O",
        "--force-clean-db",
        action="store_true",
        dest="force_clean_db",
        help="Remove old database and start fresh",
    )
    parser.add_argument(
        "-X",
        "--index",
        action="store_true",
        dest="build_index",
        help="Create query performance indexes after loading",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Enable verbose logging",
    )
    parser.add_argument(
        "-l",
        "--log",
        type=str,
        dest="log",
        help="Log file path (optional)",
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

    try:
        # Load config
        script_dir = Path(__file__).parent
        config_path = script_dir / 'biomarker_config.yaml'
        
        if not config_path.exists():
            logger.error(f"Config file not found: {config_path}")
            sys.exit(1)
        
        with open(config_path, 'r') as f:
            config = yaml.safe_load(f)
        
        # Initialize database
        logger.info(f"Input folder: {args.input_folder}")
        logger.info(f"Output database: {args.output}")
        logger.info(f"Config file: {config_path}")
        
        db = DatabaseManager(args.output, force_clean_db=args.force_clean_db)
        db.initialize()
        
        # Load data with config
        builder = BiomarkerDataBuilder(db, config)
        builder.load_folder(args.input_folder)
        
        # Create indexes if requested
        if args.build_index:
            db.create_indexes()
        
        db.disconnect()
        logger.info("Biomarker KG loading completed successfully!")
        
    except Exception as e:
        logger.error(f"Error during loading: {e}")
        sys.exit(1)


if __name__ == '__main__':
    main()
