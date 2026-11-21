"""Trace selected regulatory provisions through a shared space or element."""

import argparse
from collections import deque
import csv
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def read_graph():
    sources = json.loads((ROOT / "01_source/sources.json").read_text(encoding="utf-8"))
    dataset = json.loads((ROOT / "02_evidence/multicode.json").read_text(encoding="utf-8"))
    registry = {source["source_id"]: source for source in sources}
    labels = {s["document_id"]: s.get("document_label", s["document"]) for s in sources}
    labels.update({c["id"]: c["label"] for c in dataset["concepts"]})
    topics = {c["topic"]: c["id"] for c in dataset["concepts"] if "topic" in c}
    records = {}
    for clause in dataset["clauses"]:
        source = registry[clause["source_id"]]
        ref = clause["code_ref"]
        key = f"{source['source_id']}/{ref}"
        if key in labels:
            raise ValueError(f"Duplicate node: {key}")
        page = clause.get("pdf_page")
        locator = f"{ref} | PDF p. {page}" if page else f"HTML clause {ref}"
        title = f"{source['authority']} | {source['edition']} | {locator}"
        url = f"{source['url']}#page={page}" if page else clause["section_url"]
        records[key] = {
            "id": key, "title": title, "source_id": source["source_id"],
            "authority": source["authority"], "edition": source["edition"],
            "checked_on": source["checked_on"], "code_ref": ref, "source_locator": locator,
            "record_kind": clause["record_kind"], "source_url": url,
            "applies_when": clause["applies_when"],
            "text": f"Scope: {clause['applies_when']}\nSource summary: {clause['summary']}",
        }
        labels[key] = title
    with (ROOT / "02_evidence/links.csv").open(encoding="utf-8", newline="") as source:
        links = list(csv.DictReader(source))
    for edge in links:
        if edge["from_id"] not in labels or edge["to_id"] not in labels:
            raise ValueError(f"Unknown link endpoint: {edge}")
        if edge["evidence_id"] not in records:
            raise ValueError(f"Missing evidence for link: {edge}")
    return records, labels, topics, links


def trace(topic, graph):
    records, labels, topics, links = graph
    if topic not in topics:
        raise ValueError(f"Choose a topic from {', '.join(topics)}")
    space = topics[topic]
    todo = deque([space])
    seen = set()
    selected = []
    for_current = {}
    for index, e in enumerate(links):
        # Scope and accepted-solution links are also discoverable from the object.
        for_current.setdefault(e["from_id"], []).append((index, e["to_id"]))
        if e["relation"] in {"applies_to", "acceptable_solution_for"}:
            for_current.setdefault(e["to_id"], []).append((index, e["from_id"]))
    used_edges = set()
    while todo:
        current = todo.popleft()
        if current in seen:
            continue
        seen.add(current)
        for index, neighbour in for_current.get(current, []):
            if index not in used_edges:
                selected.append(links[index])
                used_edges.add(index)
            todo.append(neighbour)

    lines = [f"## {labels[space]}", ""]
    for e in selected:
        proof = records[e["evidence_id"]]
        lines.append(f"- {labels[e['from_id']]} → {e['relation']} → {labels[e['to_id']]} "
                     f"({e['basis']}). [Source]({proof['source_url']})")
    return [key for key in records if key in seen], lines


def main():
    graph = read_graph()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("topic", choices=graph[2])
    keys, lines = trace(parser.parse_args().topic, graph)
    print("\n".join(lines))
    print("\nApplicability to verify:\n")
    for key in keys:
        record = graph[0][key]
        print(f"- {record['title']}: {record['applies_when']}")


if __name__ == "__main__":
    main()
