
import csv
from pathlib import Path
from collections import defaultdict
import sys
from typing import Dict, Tuple

def parse_trait_mappings(mapping_file: str) -> Dict[str, Dict[str, str]]:
    """
    Parse SSSOM trait mapping file into dict keyed by subject_label.
    
    For each row:
    - Include subject_id (replacing PORTAL: with KPN.TRAIT:) with empty string predicate
    - Include object_id only if object_label matches subject_label (case insensitive), with predicate
    
    Args:
        mapping_file: Path to SSSOM TSV mapping file
        
    Returns:
        Dict[subject_label] = Dict[identifier] = predicate
        (Duplicates automatically removed; each identifier appears once per trait)
    """
    trait_map = defaultdict(dict)
    
    with open(mapping_file, 'r', encoding='utf-8') as f:
        # Skip comment lines
        for line in f:
            if not line.startswith('#'):
                # Found start of data, create reader from remaining content
                f.seek(0)
                break
        
        # Skip all comment lines
        while True:
            pos = f.tell()
            line = f.readline()
            if not line.startswith('#'):
                f.seek(pos)
                break
        
        # Parse TSV data
        reader = csv.DictReader(f, delimiter='\t')
        
        for row in reader:
            subject_label = (row.get('subject_label') or '').strip()
            subject_id = (row.get('subject_id') or '').strip()
            object_id = (row.get('object_id') or '').strip()
            object_label = (row.get('object_label') or '').strip()
            predicate_id = (row.get('predicate_id') or '').strip()
            
            if not subject_label:
                continue
            
            # Replace PORTAL: with KPN.TRAIT:
            if subject_id.startswith('PORTAL:'):
                subject_id = 'KPN.TRAIT:' + subject_id[7:]
            
            # Add subject_id with empty string predicate (duplicates automatically removed by dict)
            trait_map[subject_label][subject_id] = ''
            
            # Add object_id if object_label matches subject_label (case insensitive), with predicate
            if object_label and subject_label.lower() == object_label.lower():
                trait_map[subject_label][object_id] = predicate_id
    
    return trait_map



def _load_portal_phenotype_registry(folder_path: str):
    """
    Load portal phenotype registry TSV file into memory.
    Maps phenotype_name to (portal_id, trait_type).
    
    Args:
        folder_path: Path to the input folder containing the registry file
    """
    portal_phenotype_file = 'portal_phenotype_registry.tsv'
    portal_phenotype_data: Dict[str, Tuple[str, str, str]] = {}
    mapped_portal_phenotype_data: Dict[str, Tuple[str, str, str]] = {}

    if not portal_phenotype_file:
        print("Portal phenotype registry file name not set in config", file=sys.stderr)
        return {}
    
    portal_file = Path(folder_path) / portal_phenotype_file
    if not portal_file.exists():
        print(f"Portal phenotype registry file not found: {portal_file}", file=sys.stderr)
        return {}
    
    with open(portal_file, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f, delimiter='\t')
        for row in reader:
            phenotype_name = (row.get('phenotype_name') or '').strip()
            portal_id = (row.get('portal_id') or '').strip()
            trait_type = (row.get('trait_type') or '').strip()
            
            if phenotype_name and portal_id and trait_type:
                portal_phenotype_data[phenotype_name] = (portal_id, phenotype_name, trait_type)
                if phenotype_name and ',' in phenotype_name:
                    mapped_phenotype_name = phenotype_name.replace(',', ';')
                    mapped_portal_phenotype_data[mapped_phenotype_name] = (portal_id, phenotype_name, trait_type)
        
        print(f"Loaded {len(portal_phenotype_data)} phenotype records from portal registry", file=sys.stderr)

    return portal_phenotype_data, mapped_portal_phenotype_data



def _load_nodes_from_file( folder_path: str, portal_phenotype_data, mapped_portal_phenotype_data, ai_mappings):
    """Load nodes from a CSV file."""
    
    csv_path = Path(folder_path) / 'node_mapping_summary.csv'
    counts = defaultdict(int)
    print('node_iri', 'label', 'portal_id', 'portal_phenotype_name', 'trait_type', 'mapping_status', 'comment', sep='\t')
    with open(csv_path, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f, delimiter=',')
        n = 0
        for row in reader:
            node_iri = (row.get('node_iri') or '').strip()
            node_type = (row.get('node_type') or '').strip()
            label = (row.get('label') or '').strip()
            mapping_status = (row.get('mapping_status') or '').strip()
            if node_type == 'Trait':
                n += 1
                if label and label in portal_phenotype_data:
                    print(node_iri, label, *portal_phenotype_data[label], 'exact match', '', sep='\t')
                    counts['exact match'] += 1
                    pass
                elif label and label in mapped_portal_phenotype_data:
                    print(node_iri, label, *mapped_portal_phenotype_data[label], 'exact match after comma-to-semicolon mapping', '', sep='\t')
                    counts['mapped_after_comma_to_semicolon'] += 1
                    pass
                elif label and label in ai_mappings:
                    print(node_iri, label, *ai_mappings[label], sep='\t')
                    counts[ai_mappings[label][3]] += 1
                    pass
                else:
                    print(node_iri, label, '', sep='\t')
                    print(node_iri, label, '', sep='\t', file=sys.stderr)
                    counts['unmapped'] += 1
        print(f"Total Trait nodes processed: {n}", file=sys.stderr)
        print("Mapping counts:", file=sys.stderr)
        for k, v in counts.items():
            print(f"  {k}: {v}", file=sys.stderr)


def load_ai_mappings(folder_path: str):
    """Load AI mappings from a CSV file."""
    ai_mappings = {}
    csv_path = Path(folder_path) / 'claude_mapped_nodes.tsv'
    with open(csv_path, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f, delimiter='\t')
        for row in reader:
            source_term = (row.get('source_term') or '').strip()
            portal_id = (row.get('portal_id') or '').strip()
            portal_phenotype_name = (row.get('portal_phenotype_name') or '').strip()
            trait_type = (row.get('trait_type') or '').strip()
            match_type = "claude: "+(row.get('match_type') or '').strip()
            candidate_suggestions = (row.get('candidate_suggestions') or '').strip()
            if source_term:
                ai_mappings[source_term] = (portal_id, portal_phenotype_name, trait_type, match_type, candidate_suggestions)
    return ai_mappings


def main():
    folder_path = 'data/REVEALKG/mapping'
    portal_phenotype_data, mapped_portal_phenotype_data = _load_portal_phenotype_registry(folder_path)
    ai_mappings = load_ai_mappings(folder_path)
    print(f"Loaded portal phenotype data: {len(portal_phenotype_data.keys())} records", file=sys.stderr)
    print(f"Loaded mapped portal phenotype data: {len(mapped_portal_phenotype_data.keys())} records", file=sys.stderr)
    _load_nodes_from_file(folder_path, portal_phenotype_data, mapped_portal_phenotype_data, ai_mappings)


def mainX():

    mapping_file = 'data/REVEALKG/dig-portal-data-modelsx/versions/phenotype/v0.0.1/portal_phenotype_mappings.sssom.tsv'
    
    print(f"Parsing trait mappings from: {mapping_file}\n", file=sys.stderr)
    
    trait_map = parse_trait_mappings(mapping_file)
    
    print(f"Total traits: {len(trait_map)}\n", file=sys.stderr)
    print("First 50 entries:", file=sys.stderr)
    print("-" * 100, file=sys.stderr)
    
    for i, (trait_label, identifiers_dict) in enumerate(list(trait_map.items())[:50]):
        print(f"{i+1:3d}. {trait_label}", file=sys.stderr)
        for ident, predicate in sorted(identifiers_dict.items()):
            print(f"       - {ident} ({predicate})", file=sys.stderr)
        print(file=sys.stderr)
        print(file=sys.stderr)

    print(trait_map['Abdominal aortic aneurysm'], file=sys.stderr)

if __name__ == '__main__':
    main()