# CFDE REVEAL Knowledge Graph Data Distillery

A Python utility to download, extract, and build a SQLite knowledge graph database from CFDE (Common Fund Data Ecosystem) REVEAL data sources.

## Overview

The Data Distillery automates the process of:
1. **Downloading** zip files containing CFDE data from multiple sources (SPARC, etc.)
2. **Extracting** CSV files from those archives
3. **Building** a SQLite database with a normalized schema for nodes, edges, and cross-references

## Components

### `data_distillery_kc.py`
Main CLI entry point with flexible command-line arguments to control download and database building.

### `dd_download.py`
Handles downloading and extracting zip files:
- Reads download URLs from `data/DataDistillerySources.tsv` (column 7)
- Downloads files with progress logging
- Extracts zip contents to organized folder structure
- Cleans up partial folders on extraction failure
- Checks if data is already extracted before re-downloading

### `dd_build_db.py`
Builds SQLite database from CSV files:
- Auto-detects tab or comma delimiters
- Loads node data (ID, name/label, type, and xrefs)
- Loads edge data (source, target, relation, metadata)
- Handles missing column headers (first column often has no header)
- Stores xref values as strings (preserves `916.0` as-is, not converted to integer)
- Supports batch commits or per-row commits (verbose mode)

### `ddkg_schema.sql`
SQLite database schema with three tables:
- **nodes**: node_id (PK), name (NOT NULL), type
- **edges**: edge_id (PK auto), source (FK), target (FK), relation, sab, evidence_class, dcc
- **xref**: xref_id (PK auto), node_id (FK), source, id
- Indexes on foreign keys and common query fields

## Installation

```bash
pip install requests
```

## Usage

### Basic: Download and build database (clean)
```bash
python data_distillery_kc.py -O
```
- Downloads all files to `data/download/`
- Extracts and processes CSVs
- Creates fresh database at `data/ddkg.sqlite`
- Uses `-O` flag to delete old database

### Download only (no clean)
```bash
python data_distillery_kc.py -d -f data/download
```
- Downloads files if not already extracted
- Keeps existing database

### Process existing files (no download)
```bash
python data_distillery_kc.py -i data/download
```
- Skips download entirely
- Processes CSVs from specified folder

### Force re-download all files
```bash
python data_distillery_kc.py -D -O
```
- Forces download of all files (even if already extracted)
- Cleans database and starts fresh

### Verbose logging with file output
```bash
python data_distillery_kc.py -O -v -l build.log
```
- `-v`: Show debug output (commits after each node)
- `-l build.log`: Write logs to file

### Custom output paths
```bash
python data_distillery_kc.py -f data/raw -i data/processed -o mydb.sqlite
```
- `-f data/raw`: Download to `data/raw/`
- `-i data/processed`: Process CSVs from `data/processed/`
- `-o mydb.sqlite`: Create database at `mydb.sqlite`

## Command-Line Arguments

| Flag | Long | Description | Default |
|------|------|-------------|---------|
| `-d` | `--download` | Download if not yet extracted | False |
| `-D` | `--force-download` | Force re-download all files | False |
| `-f` | `--download-folder` | Folder for downloads/extracts | `data/download` |
| `-i` | `--input-folder` | Input folder for CSV processing | `data/download` |
| `-o` | `--output` | Output SQLite database file | `data/ddkg.sqlite` |
| `-O` | `--force-clean-db` | Delete old database and start fresh | False |
| `-l` | `--log` | Log file path (optional) | None |
| `-v` | `--verbose` | Enable debug logging (per-row commits) | False |

## Data Source

Downloads are sourced from URLs in `data/DataDistillerySources.tsv`:
- Column 7 contains download URLs
- Files are organized by source (SPARC, etc.)
- Extracted CSVs follow naming pattern: `*.nodes.csv` and `*.edges.csv`

## CSV Format

### Node Files (*.nodes.csv)
- **Column 1** (no header): node_id (UUID)
- **Column 2** (label/name): Human readable name
- **Column 3** (type): Node classification
- **Columns 4+** (SAB headers): External references as strings (e.g., "916.0")

Example:
```
,label,type,UBERON,FMA,CARO,CL
c34f2608-e6ce-5541-8b02-3d5f9544ff12,Abdomen,Anatomy,916.0,9577.0,,
```

### Edge Files (*.edges.csv)
- **source**: Source node_id
- **target**: Target node_id
- **relation**: Edge type
- **SAB**: Source authority
- **evidence_class**: Evidence type
- **dcc**: Data coordination center

## Database Schema

### nodes table
```sql
CREATE TABLE nodes (
    node_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    type TEXT
);
```

### edges table
```sql
CREATE TABLE edges (
    edge_id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT NOT NULL,
    target TEXT NOT NULL,
    relation TEXT,
    sab TEXT,
    evidence_class TEXT,
    dcc TEXT,
    FOREIGN KEY (source) REFERENCES nodes(node_id),
    FOREIGN KEY (target) REFERENCES nodes(node_id)
);
```

### xref table
```sql
CREATE TABLE xref (
    xref_id INTEGER PRIMARY KEY AUTOINCREMENT,
    node_id TEXT NOT NULL,
    source TEXT,
    id TEXT,
    FOREIGN KEY (node_id) REFERENCES nodes(node_id)
);
```

## Features

- **Automatic delimiter detection**: Handles both tab and comma-separated CSV files
- **Missing value handling**: Uses node_id as fallback for empty names (NOT NULL constraint)
- **String preservation**: All xref values stored as strings (e.g., "916.0" not converted to 916)
- **Batch vs. per-row commits**: Normal mode batches commits; verbose mode (`-v`) commits after each node for better debugging
- **Foreign key support**: Automatically creates placeholder nodes for edges referencing non-existent nodes
- **Flexible paths**: Separate download folder from processing folder
- **Logging**: File logging, debug output, progress reporting

## Examples

### Start from scratch
```bash
# Clean build: download, extract, and create fresh database
python data_distillery_kc.py -D -O -v -l build.log
```

### Incremental builds
```bash
# Download only new files, add to existing database
python data_distillery_kc.py -d -i data/download

# Reprocess existing files without re-downloading
python data_distillery_kc.py -i data/download
```

### Multi-folder workflow
```bash
# Download to staging area
python data_distillery_kc.py -D -f data/staging

# Process from validation area
python data_distillery_kc.py -i data/validated -o production.sqlite
```

## Troubleshooting

### "FOREIGN KEY constraint failed" on node load
- Check that node_id column is not empty
- Verify name column is populated (or node_id will be used as fallback)
- Use `-v` flag to see which rows are causing issues

### "No CSV files found" warning
- Verify download folder has subdirectories with `*.nodes.csv` and `*.edges.csv` files
- Check that files were extracted correctly with `-v` flag
- Use `-D` to force re-download and extract

### Decimal values being stored (916.0 vs 916)
- This is intentional—xref IDs are stored as strings exactly as they appear in CSVs
- If you need integer values, post-process with SQL or export script
