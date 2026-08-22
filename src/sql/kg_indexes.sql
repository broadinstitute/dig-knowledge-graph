-- Query Indexes for Knowledge Graph Database
-- These indexes are created AFTER bulk data loading for optimal query performance.
-- Do not load during initial schema creation - add them after data population.

-- ============================================================================
-- EDGE INDEXES
-- ============================================================================

-- Filter edges by source or target node
CREATE INDEX idx_edges_source ON edges(source_node_id);
CREATE INDEX idx_edges_target ON edges(target_node_id);

-- Filter edges by predicate/relationship type
CREATE INDEX idx_edges_predicate ON edges(predicate);


-- ============================================================================
-- PROPERTY INDEXES (MANY-TO-MANY LOOKUPS)
-- ============================================================================

-- Look up properties BY PROPERTY (find all nodes/edges with a property)
CREATE INDEX idx_node_properties_property ON node_properties(property_id);
CREATE INDEX idx_edge_properties_property ON edge_properties(property_id);

-- Look up properties BY NODE/EDGE (find all properties of a node/edge)
-- CRITICAL: These were missing and caused full table scans
CREATE INDEX idx_node_properties_node ON node_properties(node_id);
CREATE INDEX idx_edge_properties_edge ON edge_properties(edge_id);


-- ============================================================================
-- IDENTIFIER INDEXES
-- ============================================================================

-- Look up identifiers by node (most common query: find all identifiers for a node)
-- CRITICAL: This was missing - caused full table scan of identifiers table
CREATE INDEX idx_identifiers_node_id ON identifiers(node_id);

-- Look up identifiers by type and value (cross-reference lookups)
CREATE INDEX idx_identifiers_type_value ON identifiers(identifier_type, identifier_value);


-- ============================================================================
-- NODE INDEXES
-- ============================================================================

-- Filter nodes by type
CREATE INDEX idx_nodes_type ON nodes(type);
