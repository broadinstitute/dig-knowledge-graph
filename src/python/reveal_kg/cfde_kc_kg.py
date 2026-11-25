"""
Scan a KG edges file (TSV) and identify blocks of edges sharing the same
pattern, where a pattern is:

    (subject prefix, relationship, object prefix, evidence keys)

e.g. the edge

    HGNC HGNC:1008	associated_with	MONDO MONDO:0001356	posterior_probability=0.2274

has the pattern

    HGNC *	associated_with	MONDO *	posterior_probability

Blocking modes:
    contiguous  - a block is a run of consecutive lines with the same pattern
    global      - a block is all lines with the same pattern anywhere in the file

Usage:
    python cfde_kc_kg.py edges.tsv
    python cfde_kc_kg.py edges.tsv --mode contiguous
    python cfde_kc_kg.py edges.tsv --tsv edge_blocks.tsv
    python cfde_kc_kg.py edges.tsv.gz --examples 3
"""

import argparse
import csv
import gzip
import sys
from collections import OrderedDict
from typing import Iterator, List, NamedTuple, Optional, TextIO, Tuple

HEADER_FIRST_COLUMN = "subject_id"


class Pattern(NamedTuple):
    subject_prefix: str
    relationship: str
    object_prefix: str
    evidence_keys: Tuple[str, ...]

    def format(self) -> str:
        return "\t".join(
            [
                f"{self.subject_prefix} *",
                self.relationship,
                f"{self.object_prefix} *",
                ",".join(self.evidence_keys),
            ]
        )


class Block:
    def __init__(self, pattern: Pattern, line_no: int, raw_line: str, max_examples: int):
        self.pattern = pattern
        self.first_line = line_no
        self.last_line = line_no
        self.n_edges = 0
        self.examples: List[str] = []
        self.max_examples = max_examples
        self.add(line_no, raw_line)

    def add(self, line_no: int, raw_line: str) -> None:
        self.last_line = line_no
        self.n_edges += 1
        if len(self.examples) < self.max_examples:
            self.examples.append(raw_line)


def id_prefix(node_id: str) -> str:
    """'HGNC HGNC:1008' -> 'HGNC'; falls back to the CURIE prefix 'HGNC:1008' -> 'HGNC'."""
    node_id = node_id.strip()
    if " " in node_id:
        return node_id.split(" ", 1)[0]
    if ":" in node_id:
        return node_id.split(":", 1)[0]
    return node_id


def evidence_keys(evidence: str) -> Tuple[str, ...]:
    """'enrichment=1.5,p_value=9e-4' -> ('enrichment', 'p_value')"""
    evidence = evidence.strip()
    if not evidence:
        return ()
    return tuple(part.split("=", 1)[0].strip() for part in evidence.split(",") if part.strip())


def parse_pattern(fields: List[str]) -> Pattern:
    subject_id, relationship, object_id = fields[0], fields[1], fields[2]
    evidence = fields[3] if len(fields) > 3 else ""
    return Pattern(id_prefix(subject_id), relationship.strip(), id_prefix(object_id), evidence_keys(evidence))


def open_text(path: str) -> TextIO:
    if path == "-":
        return sys.stdin
    if path.endswith(".gz"):
        return gzip.open(path, "rt", encoding="utf-8")
    return open(path, "r", encoding="utf-8")


def iter_edges(handle: TextIO) -> Iterator[Tuple[int, str, Pattern]]:
    """Yield (line_no, raw_line, pattern) for each data line; skips header and blank lines."""
    for line_no, line in enumerate(handle, start=1):
        raw = line.rstrip("\r\n")
        if not raw.strip():
            continue
        fields = raw.split("\t")
        if line_no == 1 and fields[0].strip() == HEADER_FIRST_COLUMN:
            continue
        if len(fields) < 3:
            print(f"[warn] line {line_no}: expected >= 3 columns, got {len(fields)}; skipped", file=sys.stderr)
            continue
        yield line_no, raw, parse_pattern(fields)


def contiguous_blocks(edges: Iterator[Tuple[int, str, Pattern]], max_examples: int) -> Iterator[Block]:
    current: Optional[Block] = None
    for line_no, raw, pattern in edges:
        if current is not None and current.pattern == pattern:
            current.add(line_no, raw)
            continue
        if current is not None:
            yield current
        current = Block(pattern, line_no, raw, max_examples)
    if current is not None:
        yield current


def global_blocks(edges: Iterator[Tuple[int, str, Pattern]], max_examples: int) -> Iterator[Block]:
    blocks: "OrderedDict[Pattern, Block]" = OrderedDict()
    for line_no, raw, pattern in edges:
        block = blocks.get(pattern)
        if block is None:
            blocks[pattern] = Block(pattern, line_no, raw, max_examples)
        else:
            block.add(line_no, raw)
    yield from blocks.values()


# To switch the default blocking strategy, change --mode's default in main().
BLOCKERS = {
    "contiguous": contiguous_blocks,
    "global": global_blocks,
}


def print_block(index: int, block: Block, mode: str) -> None:
    span = "lines" if mode == "contiguous" else "first/last line"
    print(f"# block {index}: {span} {block.first_line}-{block.last_line} ({block.n_edges} edges)")
    print(block.pattern.format())
    for example in block.examples:
        print(f"  e.g. {example}")
    print()


def print_summary(blocks: List[Block]) -> None:
    totals: "OrderedDict[Pattern, List[int]]" = OrderedDict()
    for block in blocks:
        entry = totals.setdefault(block.pattern, [0, 0])
        entry[0] += 1
        entry[1] += block.n_edges

    print("=== summary ===")
    print(f"blocks: {len(blocks)}, distinct patterns: {len(totals)}, edges: {sum(b.n_edges for b in blocks)}")
    print("n_blocks\tn_edges\tpattern")
    for pattern, (n_blocks, n_edges) in totals.items():
        print(f"{n_blocks}\t{n_edges}\t{pattern.format()}")


def write_tsv(path: str, blocks: List[Block]) -> None:
    with open(path, "w", encoding="utf-8", newline="") as out:
        writer = csv.writer(out, delimiter="\t", lineterminator="\n")
        writer.writerow(
            [
                "block",
                "subject_prefix",
                "relationship",
                "object_prefix",
                "evidence_keys",
                "first_line",
                "last_line",
                "n_edges",
                "example",
            ]
        )
        for index, block in enumerate(blocks, start=1):
            p = block.pattern
            writer.writerow(
                [
                    index,
                    p.subject_prefix,
                    p.relationship,
                    p.object_prefix,
                    ",".join(p.evidence_keys),
                    block.first_line,
                    block.last_line,
                    block.n_edges,
                    block.examples[0] if block.examples else "",
                ]
            )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("edges", help="Edges TSV file (.gz supported, '-' for stdin)")
    parser.add_argument("--mode", choices=sorted(BLOCKERS), default="global", help="How blocks are defined")
    parser.add_argument("--examples", type=int, default=1, help="Example rows to print per block")
    parser.add_argument("--tsv", help="Also write blocks to this TSV file")
    args = parser.parse_args()

    handle = open_text(args.edges)
    try:
        blocks = list(BLOCKERS[args.mode](iter_edges(handle), args.examples))
    finally:
        if handle is not sys.stdin:
            handle.close()

    for index, block in enumerate(blocks, start=1):
        print_block(index, block, args.mode)
    print_summary(blocks)

    if args.tsv:
        write_tsv(args.tsv, blocks)
        print(f"\nwrote {len(blocks)} blocks to {args.tsv}", file=sys.stderr)


if __name__ == "__main__":
    main()
