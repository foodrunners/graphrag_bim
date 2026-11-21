"""Run Microsoft's noun-phrase graph and inspect the source records for a term."""

import argparse
import asyncio
from collections import Counter
from pathlib import Path

from graphrag.api import build_index
from graphrag.config.load_config import load_config
import pandas as pd

from clause_trace import follow, pilot_records
from multicode import read_graph, trace


ROOT = Path(__file__).resolve().parents[1]


def evidence_hits(relationships, units, documents, term):
    term = term.casefold()
    mask = (relationships["source"].str.casefold().str.contains(term, regex=False)
            | relationships["target"].str.casefold().str.contains(term, regex=False))
    document_of = units.set_index("id")["document_id"].to_dict()
    titles = documents.set_index("id")["title"].to_dict()
    counts = Counter()
    for unit_ids in relationships.loc[mask, "text_unit_ids"]:
        for doc_id in {document_of[unit_id] for unit_id in unit_ids}:
            counts[titles[doc_id]] += 1
    return sorted(counts.items(), key=lambda pair: (-pair[1], pair[0]))


def preview(scope, term):
    engine = ROOT / "03_graphrag" / scope
    if not (engine / "settings.yaml").is_file():
        raise ValueError(f"Prepare the {scope} scope first with _tools/prepare.py.")
    destination = engine / "preview"
    destination.mkdir(exist_ok=True)
    check = destination / "check.md"
    check.write_text("pending\n", encoding="utf-8")
    try:
        config = load_config(root_dir=engine)
        config.workflows = [
            "load_input_documents", "create_base_text_units", "create_final_documents", "extract_graph_nlp"
        ]
        config.output_storage.base_dir = str(destination)
        config.reporting.base_dir = str(destination / "logs")
        config.cache.type = "none"
        for result in asyncio.run(build_index(config=config)):
            if result.error:
                raise RuntimeError(f"{result.workflow}: {result.error}")
        docs, units, nodes, edges = [
            pd.read_parquet(destination / f"{table}.parquet")
            for table in ("documents", "text_units", "entities", "relationships")
        ]
        if set(units["document_id"]) != set(docs["id"]) or nodes.empty or edges.empty:
            raise ValueError("Graph is empty or source document links are incomplete.")
        locator_key = "source_locator" if scope == "multicode" else "pdf_page"
        if not all(locator_key in text for text in units["text"]):
            raise ValueError("A text unit lost its source locator.")
        if not set(edges["text_unit_ids"].explode().dropna()).issubset(set(units["id"])):
            raise ValueError("A graph edge points to an unknown text unit.")
        hits = evidence_hits(edges, units, docs, term)
        report = [
            "pass", "", f"Microsoft GraphRAG NLP preview | {scope}", "",
            f"{len(docs)} documents, {len(units)} text units, {len(nodes)} noun-phrase nodes, {len(edges)} co-occurrence edges.",
            "", f"Source documents connected to a noun phrase containing {term!r}, ordered by number of matching edges.", "",
        ]
        report.extend(f"- {title} ({count} edges)" for title, count in hits[:8])
        if not hits:
            report.append("No matching noun phrase. Try a shorter term.")
        if scope == "pilot" and hits:
            records = pilot_records()
            refs = {row["title"]: row["code_ref"] for row in records}
            expanded = follow(records, [refs[title] for title, _ in hits])
            if expanded:
                report.extend(["", "Explicit references followed in the pilot", ""])
                report.extend(f"- {line}" for line in expanded)
        if scope == "multicode" and hits:
            graph = read_graph()
            matched_titles = {title for title, _ in hits}
            for topic in graph[2]:
                keys, lines = trace(topic, graph)
                if any(graph[0][key]["title"] in matched_titles for key in keys):
                    report.extend(["", *lines])
        message = "\n".join(report) + "\n"
        check.write_text(message, encoding="utf-8")
        print(message)
    except Exception as error:
        check.write_text(f"fail: {error}\n", encoding="utf-8")
        raise


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("scope", choices=["pilot", "full", "multicode"])
    parser.add_argument("--find", default="alarm", help="Substring of a noun phrase in the local graph.")
    args = parser.parse_args()
    if not args.find.strip():
        parser.error("--find needs a nonempty term")
    preview(args.scope, args.find.strip())
