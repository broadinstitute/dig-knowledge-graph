"""
Script to populate the Knowledge Graph SQLite database from CSV files.
"""

import sqlite3
import csv
import yaml
import logging
import uuid
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Union
from collections import defaultdict

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class KGLoader:
    """Load knowledge graph data from CSV files into SQLite database."""
    
    def __init__(self, config: dict, data_path: str, db_path: str):
        """
        Initialize the loader.
        
        Args:
            config: Loaded configuration dictionary
            data_path: Path to the directory containing CSV files
            db_path: Path to the SQLite database file
        """
        self.config = config
        self.data_path = Path(data_path)
        self.db_path = Path(db_path)
        
        self.node_types = self.config['nodes']['types']
        self.sab_default = self.config['edges']['default_sab']
        self.batch_size = self.config['loading']['batch_size']
        self.skip_duplicates = self.config['loading']['skip_duplicates']
        
        self.conn: Optional[sqlite3.Connection] = None
        self.cursor: Optional[sqlite3.Cursor] = None
        
        # Caches for deduplication
        self.property_cache: Dict[Tuple[str, str, str], int] = {}  # (key, value, type) -> property_id
        self.node_cache: set = set()  # node_ids already in DB
        self.node_id_mapping: Dict[str, str] = {}  # original_id -> uuid
    
    def connect(self):
        """Connect to the database."""
        self.conn = sqlite3.connect(str(self.db_path))
        self.cursor = self.conn.cursor()
        logger.info(f"Connected to database: {self.db_path}")
    
    def close(self):
        """Close the database connection."""
        if self.conn:
            self.conn.close()
            logger.info("Database connection closed")
    
    def load_schema(self, schema_path: Union[str, Path]):
        """Load the schema from SQL file."""
        assert self.cursor is not None and self.conn is not None
        schema_path = Path(schema_path)
        with open(schema_path, 'r') as f:
            schema_sql = f.read()
        
        # Split by ; and execute each statement
        for statement in schema_sql.split(';'):
            statement = statement.strip()
            if statement:
                try:
                    self.cursor.execute(statement)
                except sqlite3.OperationalError as e:
                    if "already exists" in str(e):
                        logger.info(f"Table already exists: {e}")
                    else:
                        raise
        
        self.conn.commit()
        logger.info("Schema loaded successfully")
    
    def load_nodes(self):
        """Load all node CSV files."""
        node_files = list(self.data_path.glob('*.nodes.csv'))
        logger.info(f"Found {len(node_files)} node files")
        
        total_nodes = 0
        for node_file in sorted(node_files):
            # Extract node type from filename (e.g., "HGNC.nodes.csv" -> "HGNC")
            node_type_name = node_file.stem.split('.')[0]
            
            if node_type_name not in self.node_types:
                logger.warning(f"Unknown node type: {node_type_name}, skipping {node_file.name}")
                continue
            
            node_type = self.node_types[node_type_name]
            count = self._load_node_file(node_file, node_type)
            total_nodes += count
            logger.info(f"Loaded {count} nodes from {node_file.name} (type: {node_type})")
        
        logger.info(f"Total nodes loaded: {total_nodes}")
    
    def _load_node_file(self, node_file: Path, node_type: str) -> int:
        """Load a single node CSV file."""
        count = 0
        batch = []
        identifiers_batch = []
        
        with open(node_file, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                original_id = row['id'].strip()
                label = row['label'].strip()
                
                # Skip if already loaded
                if self.skip_duplicates and original_id in self.node_cache:
                    continue
                
                # Generate UUID for node
                node_uuid = str(uuid.uuid4())
                
                # Extract identifier type from original_id (prefix before ':')
                identifier_type = original_id.split(':')[0] if ':' in original_id else 'unknown'
                
                batch.append((node_uuid, node_type, label))
                identifiers_batch.append((node_uuid, identifier_type, original_id))
                self.node_cache.add(original_id)
                count += 1
                
                if len(batch) >= self.batch_size:
                    self._insert_nodes_batch(batch, identifiers_batch)
                    batch = []
                    identifiers_batch = []
        
        # Insert remaining batch
        if batch:
            self._insert_nodes_batch(batch, identifiers_batch)
        
        return count
    
    def _insert_nodes_batch(self, batch: List[Tuple[str, str, str]], identifiers_batch: List[Tuple[str, str, str]]):
        """Insert a batch of nodes and their identifiers."""
        assert self.cursor is not None and self.conn is not None
        try:
            self.cursor.executemany(
                'INSERT OR IGNORE INTO nodes (node_id, type, label) VALUES (?, ?, ?)',
                batch
            )
            self.cursor.executemany(
                'INSERT OR IGNORE INTO identifiers (node_id, identifier_type, identifier_value) VALUES (?, ?, ?)',
                identifiers_batch
            )
            self.conn.commit()
        except sqlite3.IntegrityError as e:
            logger.error(f"Error inserting nodes batch: {e}")
            self.conn.rollback()
    
    def _build_node_id_mapping(self):
        """Build mapping from original node IDs to UUIDs from identifiers table."""
        assert self.cursor is not None
        self.node_id_mapping: Dict[str, str] = {}  # original_id -> uuid
        
        try:
            self.cursor.execute('SELECT identifier_value, node_id FROM identifiers')
            for original_id, node_uuid in self.cursor.fetchall():
                self.node_id_mapping[original_id] = node_uuid
            logger.info(f"Built mapping for {len(self.node_id_mapping)} node identifiers")
        except Exception as e:
            logger.error(f"Error building node ID mapping: {e}")
            raise
    
    def load_edges(self):
        """Load all edge CSV files."""
        edge_files = list(self.data_path.glob('*.edges.csv'))
        logger.info(f"Found {len(edge_files)} edge files")
        
        total_edges = 0
        for edge_file in sorted(edge_files):
            count = self._load_edge_file(edge_file)
            total_edges += count
            logger.info(f"Loaded {count} edges from {edge_file.name}")
        
        logger.info(f"Total edges loaded: {total_edges}")
    
    def _load_edge_file(self, edge_file: Path) -> int:
        """Load a single edge CSV file."""
        # Parse edge filename: {predicate}.{target_type}.edges.csv
        # Example: BIOMARKER.indicated_by_above_normal_level_of.HGNC.edges.csv
        parts = edge_file.stem.split('.')
        if len(parts) < 3:
            logger.warning(f"Invalid edge filename format: {edge_file.name}")
            return 0
        
        sab = self.sab_default  # Can be extended to parse from filename if needed
        
        count = 0
        batch = []
        
        with open(edge_file, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                source_orig = row['source'].strip()
                predicate = row['relation'].strip()
                target_orig = row['target'].strip()
                
                # Map original node IDs to UUIDs
                source_uuid = self.node_id_mapping.get(source_orig)
                target_uuid = self.node_id_mapping.get(target_orig)
                
                if not source_uuid:
                    logger.warning(f"Source node not found: {source_orig}")
                    continue
                if not target_uuid:
                    logger.warning(f"Target node not found: {target_orig}")
                    continue
                
                batch.append((source_uuid, predicate, target_uuid, sab))
                count += 1
                
                if len(batch) >= self.batch_size:
                    self._insert_edges_batch(batch)
                    batch = []
        
        # Insert remaining batch
        if batch:
            self._insert_edges_batch(batch)
        
        return count
    
    def _insert_edges_batch(self, batch: List[Tuple[str, str, str, str]]):
        """Insert a batch of edges."""
        assert self.cursor is not None and self.conn is not None
        try:
            self.cursor.executemany(
                'INSERT OR IGNORE INTO edges (source_node_id, predicate, target_node_id, sab) VALUES (?, ?, ?, ?)',
                batch
            )
            self.conn.commit()
        except sqlite3.IntegrityError as e:
            logger.error(f"Error inserting edges batch: {e}")
            self.conn.rollback()
    
    def create_indexes(self):
        """Create indexes after data loading."""
        assert self.cursor is not None and self.conn is not None
        logger.info("Creating indexes...")
        
        indexes = [
            'CREATE INDEX IF NOT EXISTS idx_properties_key_value ON properties(property_key, property_value);',
            'CREATE INDEX IF NOT EXISTS idx_edges_source ON edges(source_node_id);',
            'CREATE INDEX IF NOT EXISTS idx_edges_target ON edges(target_node_id);',
            'CREATE INDEX IF NOT EXISTS idx_node_properties_property ON node_properties(property_id);',
            'CREATE INDEX IF NOT EXISTS idx_edge_properties_property ON edge_properties(property_id);',
            'CREATE INDEX IF NOT EXISTS idx_identifiers_type_value ON identifiers(identifier_type, identifier_value);',
            'CREATE INDEX IF NOT EXISTS idx_nodes_type ON nodes(type);',
            'CREATE INDEX IF NOT EXISTS idx_edges_predicate ON edges(predicate);',
        ]
        
        for idx_sql in indexes:
            try:
                self.cursor.execute(idx_sql)
            except sqlite3.OperationalError as e:
                logger.error(f"Error creating index: {e}")
        
        self.conn.commit()
        logger.info("Indexes created successfully")
    
    def run(self, schema_path: str):
        """Run the full loading process."""
        try:
            self.connect()
            self.load_schema(schema_path)
            self.load_nodes()
            self._build_node_id_mapping()
            self.load_edges()
            self.create_indexes()
            logger.info("Loading completed successfully!")
        except Exception as e:
            logger.error(f"Error during loading: {e}")
            raise
        finally:
            self.close()


def main():
    """Main entry point."""
    # Get paths relative to this script
    script_dir = Path(__file__).parent
    config_path = script_dir / 'load_config.yaml'
    
    # Load config once
    with open(config_path, 'r') as f:
        config = yaml.safe_load(f)
    
    # Read database path from config
    db_path = config['database']['path']
    if not Path(db_path).is_absolute():
        db_path = script_dir / db_path
    
    data_path = script_dir / 'data' / 'BiomarkerKG' / 'processed'
    schema_path = script_dir.parent.parent / 'sql' / 'kg_schema.sql'
    
    logger.info(f"Config: {config_path}")
    logger.info(f"Data: {data_path}")
    logger.info(f"Database: {db_path}")
    logger.info(f"Schema: {schema_path}")
    
    loader = KGLoader(config, str(data_path), str(db_path))
    loader.run(str(schema_path))


if __name__ == '__main__':
    main()
