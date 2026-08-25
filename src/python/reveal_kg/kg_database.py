"""
SQLite database management for Knowledge Graph.

Provides DatabaseManager class for database lifecycle operations:
- Connection management
- Schema initialization
- Index creation
"""

import logging
import sqlite3
from pathlib import Path

logger = logging.getLogger(__name__)


class DatabaseManager:
    """Manage SQLite database lifecycle and operations."""

    def __init__(self, db_path: str = "data/ddkg.sqlite", force_clean_db: bool = False):
        """
        Initialize the database manager.

        Args:
            db_path: Path to the SQLite database file
            force_clean_db: If True, delete existing database before initializing
        """
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.force_clean_db = force_clean_db
        self.conn = None
        self.cursor = None

    def initialize(self):
        """Initialize the database: cleanup old one (if -O flag), connect, and create schema."""
        if self.force_clean_db and self.db_path.exists():
            self.db_path.unlink()
            logger.info(f"Removed old database: {self.db_path}")
        
        self.connect()
        self.create_schema()

    def connect(self):
        """Connect to the database."""
        try:
            self.conn = sqlite3.connect(str(self.db_path))
            self.cursor = self.conn.cursor()
            # Enable foreign keys
            self.cursor.execute("PRAGMA foreign_keys = ON")
            logger.info(f"Connected to database: {self.db_path}")
        except sqlite3.Error as e:
            logger.error(f"Failed to connect to database: {e}")
            raise

    def disconnect(self):
        """Disconnect from the database."""
        if self.conn:
            self.conn.close()
            logger.info("Disconnected from database")

    def create_schema(self):
        """Create database schema from SQL file."""
        assert self.cursor is not None and self.conn is not None
        try:
            logger.info("Creating database schema...")

            # Read and execute schema file from src/sql/kg_schema.sql
            schema_file = Path(__file__).parent.parent.parent / "sql" / "kg_schema.sql"
            
            if not schema_file.exists():
                logger.error(f"Schema file not found: {schema_file}")
                raise FileNotFoundError(f"Schema file not found: {schema_file}")

            with open(schema_file, 'r') as f:
                schema_sql = f.read()

            # Execute all statements in the schema file
            self.cursor.executescript(schema_sql)
            self.conn.commit()
            logger.info("Database schema created successfully")

        except sqlite3.Error as e:
            logger.error(f"Failed to create schema: {e}")
            raise

    def create_indexes(self):
        """
        Create query performance indexes from kg_indexes.sql file.
        Call this after all data loading is complete.
        """
        assert self.cursor is not None and self.conn is not None
        try:
            index_file = Path(__file__).parent.parent.parent / "sql" / "kg_indexes.sql"
            if not index_file.exists():
                logger.warning(f"Index file not found: {index_file}")
                return
            
            with open(index_file, 'r', encoding='utf-8') as f:
                index_sql = f.read()
            
            # Normalize line endings (handle both Windows CRLF and Unix LF)
            index_sql = index_sql.replace('\r\n', '\n').replace('\r', '\n')
            
            logger.info("Creating query performance indexes...")
            
            # Split into individual statements and log each one
            statements = []
            raw_statements = index_sql.split(';')
            logger.info(f"Total segments after split by ';': {len(raw_statements)}")
            
            for i, segment in enumerate(raw_statements):
                # Remove all comment lines from the segment
                lines = segment.split('\n')
                sql_lines = [line for line in lines if line.strip() and not line.strip().startswith('--')]
                
                # Rejoin to get the pure SQL
                statement = '\n'.join(sql_lines).strip()
                
                # Skip if nothing remains after removing comments
                if not statement:
                    logger.debug(f"  Segment {i}: Skipped (empty or comments only)")
                    continue
                
                statements.append(statement)
                logger.debug(f"  Segment {i}: Parsed statement {len(statements)}: {statement[:80]}")
            
            logger.info(f"Found {len(statements)} index statements to create")
            created_count = 0
            errors = []
            
            # Execute each statement with detailed logging
            for i, statement in enumerate(statements, 1):
                # Extract index name for logging
                index_name = "Unknown"
                if "CREATE INDEX" in statement.upper():
                    parts = statement.split()
                    for j, part in enumerate(parts):
                        if part.upper() == "INDEX" and j + 1 < len(parts):
                            index_name = parts[j + 1]
                            break
                
                try:
                    logger.debug(f"[{i}/{len(statements)}] Executing: {statement[:80]}...")
                    self.cursor.execute(statement)
                    logger.info(f"✓ Index created: {index_name}")
                    created_count += 1
                except sqlite3.Error as e:
                    error_msg = f"✗ Index {index_name}: {str(e)}"
                    logger.error(error_msg)
                    errors.append(error_msg)
                except Exception as e:
                    error_msg = f"✗ Index {index_name}: Unexpected error: {str(e)}"
                    logger.error(error_msg)
                    errors.append(error_msg)
            
            self.conn.commit()
            
            # Summary
            total = len(statements)
            logger.info(f"Query performance index creation complete: {created_count}/{total} successful")
            
            if errors:
                logger.warning(f"{len(errors)} indexes failed to create:")
                for error in errors:
                    logger.warning(f"  {error}")
                if created_count == 0:
                    raise RuntimeError(f"All {total} index creation attempts failed")
        except Exception as e:
            logger.error(f"Failed to create indexes: {e}")
            raise

    def commit(self):
        """Commit current transaction."""
        if self.conn:
            self.conn.commit()

    def rollback(self):
        """Rollback current transaction."""
        if self.conn:
            self.conn.rollback()
