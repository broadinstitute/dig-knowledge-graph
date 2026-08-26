"""
REVEAL Knowledge Graph loader with CLI interface.

Loads REVEAL CSV data into the normalized SQLite database.
Uses DatabaseManager for database lifecycle and RevealDataBuilder for data loading.
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


class RevealDataBuilder:
    """Build REVEAL knowledge graph data from CSV files into database."""

    def __init__(self, database_manager: DatabaseManager, config: dict):
        """
        Initialize the data builder.

        Args:
            database_manager: DatabaseManager instance to use for operations
            config: Configuration dictionary from reveal_config.yaml
        """
        self.db = database_manager
        self.config = config
        self.nodes_file_name = config.get('nodes_file_name', 'nodes.csv')
        self.edge_file_name = config.get('edge_file_name', 'edges.csv')
        self.batch_size = config.get('batch_size', 50000)
        # Build reverse mapping: base_iri -> prefix for CURIE generation
        self.base_iri_to_prefix = config.get('url_prefix_mapping', {})
        
        self.node_id_mapping: Dict[str, str] = {}  # (node_type, label) -> UUID
        self.node_cache: set = set()  # node_ids already in DB
        self.node_type_status_pairs: set = set()  # (node_type, mapping_status, iri_prefix) tuples
        self.node_type_status_pairs: set = set()  # (node_type, mapping_status) pairs

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

        # Load nodes file
        nodes_file = folder / self.nodes_file_name
        if nodes_file.exists():
            logger.info(f"Loading nodes from {self.nodes_file_name}")
            self._load_nodes_from_file(str(nodes_file))
        else:
            logger.warning(f"Nodes file not found: {nodes_file.name}")

        # Build mapping from (node_type, label) to UUIDs for edge loading
        self._build_node_id_mapping()
        
        # Print distinct (node_type, mapping_status) pairs
        self._print_node_type_status_summary()        
        # Print collected external base IRIs in YAML format
        self._print_external_base_iris_yaml()
        logger.info("Data loading completed")

    def _extract_iri_prefix(self, iri: str) -> str:
        """
        Extract the base IRI namespace from an IRI.
        
        Handles patterns like:
        - http://purl.obolibrary.org/obo/HP_0000539 -> http://purl.obolibrary.org/obo/HP_
        - http://www.ebi.ac.uk/efo/EFO_0010112 -> http://www.ebi.ac.uk/efo/EFO_
        - http://www.ncbi.nlm.nih.gov/gene/23140 -> http://www.ncbi.nlm.nih.gov/gene/
        
        Args:
            iri: The IRI string
            
        Returns:
            The base IRI namespace, or 'unknown' if unable to extract
        """
        try:
            # Extract the identifier from the URL (last path segment)
            identifier = iri.split('/')[-1]
            
            # Try to split on underscore and take first part
            if '_' in identifier:
                prefix = identifier.split('_')[0]
                # Reconstruct base IRI: everything up to last '/' + prefix + '_'
                base_iri = iri.rsplit('/', 1)[0] + '/' + prefix + '_'
                return base_iri
            
            # If no underscore, return everything up to and including the last '/'
            # (e.g., http://www.ncbi.nlm.nih.gov/gene/ from http://www.ncbi.nlm.nih.gov/gene/23140)
            base_iri = iri.rsplit('/', 1)[0] + '/'
            return base_iri
        except Exception as e:
            logger.debug(f"Error extracting IRI prefix from {iri}: {e}")
            return 'unknown'

    def _generate_curie(self, iri: str) -> Optional[Tuple[str, str]]:
        """
        Generate a CURIE from an IRI using config prefix mapping.
        
        Args:
            iri: The IRI string
            
        Returns:
            Tuple of (prefix, curie) or None if cannot generate
            Example: ('HP', 'HP:0000539')
        """
        try:
            # Extract base IRI using existing method
            base_iri = self._extract_iri_prefix(iri)
            if base_iri == 'unknown':
                logger.warning(f"Cannot extract base IRI from: {iri}")
                return None
            
            # Look up prefix in config mapping
            prefix = self.base_iri_to_prefix.get(base_iri)
            if not prefix:
                logger.warning(f"Cannot map base IRI to prefix: {base_iri} (from IRI: {iri})")
                return None
            
            # Extract local ID: everything after base_iri
            local_id = iri[len(base_iri):]
            
            # Create CURIE: prefix:local_id
            curie = f"{prefix}:{local_id}"
            return (prefix, curie)
        except Exception as e:
            logger.debug(f"Error generating CURIE from {iri}: {e}")
            return None

    def _load_nodes_from_file(self, csv_path: str):
        """Load nodes from a CSV file."""
        try:
            with open(csv_path, 'r', encoding='utf-8') as f:
                # Detect delimiter
                first_line = f.readline()
                f.seek(0)
                delimiter = '\t' if '\t' in first_line else ','
                
                reader = csv.DictReader(f, delimiter=delimiter)
                self._load_nodes(reader, csv_path)
        except Exception as e:
            logger.error(f"Failed to load {csv_path}: {e}")
            raise

    def _load_nodes(self, reader, csv_path: str):
        """Load nodes from CSV reader with UUID generation and batch processing."""
        count = 0
        batch: List[Tuple[str, str, str]] = []
        identifiers_batch: List[Tuple[str, str, str]] = []
        assert self.db.cursor is not None and self.db.conn is not None
        
        try:
            for row_num, row in enumerate(reader, 1):
                node_iri = (row.get('node_iri') or '').strip()
                node_type = (row.get('node_type') or '').strip()
                label = (row.get('label') or '').strip()
                mapping_status = (row.get('mapping_status') or '').strip()
                
                # Skip rows with empty node_iri
                if not node_iri:
                    continue
                
                # Extract meaningful IRI prefix
                iri_prefix = self._extract_iri_prefix(node_iri)
                
                # Track (node_type, mapping_status, iri_prefix) tuple
                self.node_type_status_pairs.add((node_type, mapping_status, iri_prefix))
                
                # Generate UUID for this node
                node_uuid = str(uuid.uuid4())
                
                batch.append((node_uuid, node_type, label))
                identifiers_batch.append((node_uuid, mapping_status, node_iri))
                
                # Generate CURIE for external identifiers
                if mapping_status != 'local_cfde_reveal':
                    curie_info = self._generate_curie(node_iri)
                    if curie_info:
                        prefix, curie = curie_info
                        identifiers_batch.append((node_uuid, prefix, curie))
                                
                self.node_cache.add(node_iri)
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

    def _print_node_type_status_summary(self):
        """Print all distinct (node_type, mapping_status, iri_prefix) tuples found."""
        if not self.node_type_status_pairs:
            logger.info("No node type/status pairs found")
            return
        
        logger.info(f"\nDistinct (node_type, mapping_status, iri_prefix) tuples ({len(self.node_type_status_pairs)} total):")
        for node_type, mapping_status, iri_prefix in sorted(self.node_type_status_pairs):
            logger.info(f"  ({node_type!r}, {mapping_status!r}, {iri_prefix!r})")

    def _print_external_base_iris_yaml(self):
        """Print collected external base IRIs as a dict mapping base_iri -> prefix."""
        # Collect mapping of base IRI to prefix
        iris_dict = {}
        for node_type, mapping_status, iri_prefix in self.node_type_status_pairs:
            if mapping_status.startswith('external_') and iri_prefix != 'unknown':
                # Extract prefix from the base IRI (last segment or last segment before trailing /)
                if iri_prefix.endswith('/'):
                    # For NCBI: http://www.ncbi.nlm.nih.gov/gene/ -> gene
                    prefix_key = iri_prefix.rstrip('/').split('/')[-1]
                else:
                    # For EFO: http://purl.obolibrary.org/obo/EFO -> EFO
                    prefix_key = iri_prefix.split('/')[-1]
                
                iris_dict[iri_prefix] = prefix_key
        
        if not iris_dict:
            print("\nNo external base IRIs found")
            return
        
        print("\n# Add the following to reveal_config.yaml under url_prefix_mapping:")
        for base_iri in sorted(iris_dict.keys()):
            print(f"  \"{base_iri}\": \"{iris_dict[base_iri]}\"")

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
        """Build mapping from (node_type, label) to node UUIDs."""
        assert self.db.cursor is not None
        
        try:
            self.db.cursor.execute('SELECT type, label, node_id FROM nodes')
            for node_type, label, node_uuid in self.db.cursor.fetchall():
                key = (node_type, label)
                self.node_id_mapping[key] = node_uuid
            logger.info(f"Built mapping for {len(self.node_id_mapping)} nodes")
        except Exception as e:
            logger.error(f"Error building node ID mapping: {e}")
            raise

    def _load_edges_from_file(self, csv_path: str):
        """Load edges from a CSV file."""
        # TODO: Implement edge loading from CSV
        pass

    def _load_edges(self, reader, csv_path: str):
        """Load edges from CSV reader using UUID mappings and batch processing."""
        # TODO: Implement edge loading logic with batch processing
        pass

    def _insert_edges_batch(self, batch: List[Tuple[str, str, str, str]]):
        """Insert a batch of edges."""
        # TODO: Implement batch insert for edges
        pass


def main():
    """Main entry point with CLI interface."""
    parser = ArgumentParser(
        description="REVEAL Knowledge Graph - Load CSV data into normalized SQLite database"
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
        default="data/reveal_kg.sqlite",
        dest="output",
        help="Output SQLite database file (default: data/reveal_kg.sqlite)",
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
        config_path = script_dir / 'reveal_config.yaml'
        
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
        builder = RevealDataBuilder(db, config)
        builder.load_folder(args.input_folder)
        
        # Create indexes if requested
        if args.build_index:
            db.create_indexes()
        
        db.disconnect()
        logger.info("REVEAL KG loading completed successfully!")
        
    except Exception as e:
        logger.error(f"Error during loading: {e}")
        sys.exit(1)


if __name__ == '__main__':
    main()
