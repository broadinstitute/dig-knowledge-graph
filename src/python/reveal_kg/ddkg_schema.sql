-- CFDE REVEAL Knowledge Graph SQLite Schema

-- Enable foreign keys
PRAGMA foreign_keys = ON;

-- Nodes table
CREATE TABLE IF NOT EXISTS nodes (
    node_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    type TEXT
);

-- Edges table with foreign key constraints
CREATE TABLE IF NOT EXISTS edges (
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

-- Xref table with foreign key constraint
CREATE TABLE IF NOT EXISTS xref (
    xref_id INTEGER PRIMARY KEY AUTOINCREMENT,
    node_id TEXT NOT NULL,
    source TEXT,
    id TEXT,
    FOREIGN KEY (node_id) REFERENCES nodes(node_id)
);

-- Indexes for query performance
CREATE INDEX IF NOT EXISTS idx_edges_source ON edges(source);
CREATE INDEX IF NOT EXISTS idx_edges_target ON edges(target);
CREATE INDEX IF NOT EXISTS idx_xref_node_id ON xref(node_id);
CREATE INDEX IF NOT EXISTS idx_xref_source ON xref(source);
CREATE INDEX IF NOT EXISTS idx_xref_id ON xref(id);
CREATE INDEX IF NOT EXISTS idx_nodes_type ON nodes(type);
