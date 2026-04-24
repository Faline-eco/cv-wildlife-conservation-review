import re
from collections import Counter
from pathlib import Path

import pandas as pd
import requests, time
import networkx as nx

from review.visualization.graph.cache import GBIFCache
from review.visualization.graph.ranks import RANKS
from review.visualization.graph.to_html import build_taxonomy_html
from review.visualization.graph.to_neo4j import nx_to_neo4j

BASE = "https://api.gbif.org/"

def gbif_match_cached(name: str, cache: GBIFCache, retry_with_species_search: bool = True):
    # 1) cache lookup
    cached_key, cached_match, in_cache = cache.get(name)
    if in_cache: # and cached_key is not None:
        print("----- Cached")
        return cached_key, cached_match

    # 2) call GBIF if not cached
    try:
        r = requests.get(f"{BASE}/v2/species/match", params={"name": name}, timeout=10)
        r.raise_for_status()
        m = r.json()
    except Exception as e:
        # Network or API error: treat as miss (so we don't hammer GBIF repeatedly in this run)
        cache.put_miss(name, match={"error": str(e)})
        return None, {"error": str(e)}

    # Prefer accepted usage (synonyms → accepted), else usageKey
    key = m.get("acceptedUsageKey") or m.get("usageKey")

    if key:
        cache.put_hit(name, key, m)
    else:
        if retry_with_species_search:
            print("----- No result with gbif /v2/species/match")
            end_of_records = False
            keys = []
            offset = 0
            print("----- Trying gbif /v1/species/search")
            while not end_of_records:
                try:
                    response = requests.get(f"{BASE}/v1/species/search", params={"q": name, "offset": offset, "limit": 200}, timeout=10)
                    response.raise_for_status()
                    response = response.json()
                    num_results = len(response["results"])
                    print(f"------- {offset + num_results} / {response['count']}")
                    for res in response["results"]:
                        keys.append(res["key"])
                    if num_results == 0:
                        break
                    offset += num_results
                    end_of_records = response["endOfRecords"]
                except Exception as e:
                    print("------- Error gbif /v1/species/search")
                    break
            counter = Counter(keys)
            if len(counter) > 0:
                print("----- Fixed")
                most_common_key = counter.most_common(1)[0][0]
                key = most_common_key
                m2 = requests.get(f"{BASE}/v1/species/{most_common_key}", timeout=10).json()
                cache.put_hit(name, most_common_key, m2)
            else:
                print("----- Also failed")
                cache.put_miss(name, m)
        else:
            cache.put_miss(name, m)

    return key, m


def node_label(u):
    # helpful label "Rank: ScientificName (key)"
    rank = (u.get("rank") or "").title()
    name = u.get("scientificName") or u.get("canonicalName") or u.get("vernacularName") or "?"
    return f"{rank}: {name} ({u['key']})"

def _key_field(rank: str) -> str:
    return f"{rank}Key"

def _name_field(rank: str) -> str:
    return rank

def _node_id(rec: dict, rank: str):
    # kf = _key_field(rank)
    # if kf in rec and rec[kf] is not None:
    #     return f"{rank}:{rec[kf]}"
    nf = _name_field(rank)
    if nf in rec and rec[nf]:
        rec_nf = re.sub(r'[^A-Za-z]', '', rec[nf])
        res = f"{rank}:{rec_nf}".lower().strip()
        if res == "kingdom:animal":
            res = "kingdom:animalia"
        return res
    return None

def _node_attrs(rec: dict, rank: str):
    kf, nf = _key_field(rank), _name_field(rank)
    key = rec.get(kf)
    name = rec.get(nf)
    attrs = {"rank": rank, "name": name, "gbifKey": key}
    if key:
        attrs["gbifUrl"] = f"https://www.gbif.org/species/{key}"
    return attrs

def _present_ranks(rec: dict):
    return [r for r in RANKS if _node_id(rec, r) is not None]

def _leaf_rank(rec: dict) -> str:
    """Leaf = lowest available rank from our RANKS list for this record."""
    ranks = _present_ranks(rec)
    return ranks[-1] if ranks else None

def _normalize_source_info(src: dict) -> dict:
    """Ensure list-like fields are lists; leave keys as provided."""
    out = dict(src or {})
    k = "payload"
    if k in out and out[k] is not None and not isinstance(out[k], list):
        out[k] = [out[k]]
    return out

def _merge_lists(a, b):
    """Union while preserving order."""
    seen = set()
    merged = []
    for x in (a or []) + (b or []):
        if x not in seen:
            seen.add(x)
            merged.append(x)
    return merged

def _merge_source_records(existing: dict, incoming: dict) -> dict:
    """
    Merge two source dicts (same DOI). List fields are unioned; scalars prefer
    non-empty incoming values but keep existing if incoming is empty.
    """
    res = dict(existing)
    for k, v in incoming.items():
        if isinstance(v, list):
            res[k] = _merge_lists(existing.get(k, []), v)
        else:
            res[k] = v if v not in (None, "") else existing.get(k)
    return res

def add_gbif_record_to_graph(G: nx.DiGraph, rec: dict, source_info: dict | None = None):
    """Adds taxonomy chain; optionally attaches/merges a source onto the leaf node."""
    chain = _present_ranks(rec)
    if not chain:
        return

    # ensure nodes with attrs
    node_ids = []
    for r in chain:
        nid = _node_id(rec, r)
        node_ids.append(nid)
        if not G.has_node(nid):
            G.add_node(nid, **_node_attrs(rec, r))
        else:
            G.nodes[nid].update({k: v for k, v in _node_attrs(rec, r).items() if v is not None})

    # link edges parent → child
    for p, c in zip(node_ids[:-1], node_ids[1:]):
        if not G.has_edge(p, c):
            child_rank = G.nodes[c].get("rank")
            child_name = G.nodes[c].get("name")
            G.add_edge(p, c, to_rank=child_rank, name=child_name)

    # attach source to leaf (species for typical GBIF records)
    if source_info:
        leaf = node_ids[-1]
        src = _normalize_source_info(source_info)
        sources = list(G.nodes[leaf].get("sources", []))

        doi = (src.get("doi") or "").strip() if src.get("doi") else None
        if doi:
            # dedup/merge by DOI
            idx = next((i for i, s in enumerate(sources) if (s.get("doi") or "").strip() == doi), None)
            if idx is None:
                sources.append(src)
            else:
                sources[idx] = _merge_source_records(sources[idx], src)
        else:
            # no DOI → append as-is (can't dedup reliably)
            sources.append(src)

        G.nodes[leaf]["sources"] = sources


def build_taxonomy_graph(graph, source, doi, payload, species_names, cache: GBIFCache, delay=0.1):
    length = len(species_names)
    for idx, n in enumerate(species_names):
        print(f"--- {idx} / {length} Translate {n}")
        key, match = gbif_match_cached(n,cache)
        cache.save()
        if not key:
            print(f"----- [WARN] No GBIF match for {n}")
            continue
        add_gbif_record_to_graph(graph, match, source_info={
            "source": source,
            "doi": doi,
            "payload": payload,
        })
        time.sleep(delay)  # be polite to the API

# ---- run it
if __name__ == '__main__':
    sources = [r"D:\LiteratureReviewCVinWC\review_output\cv4animals.parquet"] #[r"D:\LiteratureReviewCVinWC\review_output\20250731_fixed.parquet", r"D:\LiteratureReviewCVinWC\review_output\manual.parquet"]
    target_folder = r"D:\LiteratureReviewCVinWC\review_output"
    cache_path = Path(rf"{target_folder}\gbif_cache.json")  # choose your location
    cache = GBIFCache(cache_path)
    G = nx.DiGraph()

    # cnt = 0
    for source in sources:
        source = Path(source)
        df = pd.read_parquet(source)

        length = len(df)
        for index, row in df.iterrows():
            print(f"{index} / {length}: {row['doi']} ...")
            all_species = []
            for s in (row['Species (Text)(translated) - verified'] +
                                               # row['Species (Text)(translated) - unverified'] +
                                               row['Species (Images)(translated) - verified']# +
                                               # row['Species (Images)(translated) - unverified']
            ):
                if isinstance(s, str):
                    all_species.append(s)
                else:
                    all_species.extend(s["translations"])

            build_taxonomy_graph(G,
                                   source.name,
                                   row["doi"],
                                   row.to_json(),
                                   set(all_species),
                cache=cache)
            # cnt += 1
            # if cnt >= 5:
            #     break
        #
        # break

    # nx.drawing.nx_pydot.write_dot(G, source +".dot")
    # nx.write_graphml(prepare_graph_for_graphml(G), source + ".graphml"
    # A = nx.nx_agraph.to_agraph(G)
    # A.write(rf"{target_folder}\graph.dot")
    html = build_taxonomy_html(G, sources_attr="sources", title="Computer Vision in Wildlife Conservation")
    with open(rf"{target_folder}\taxonomy.html", "w", encoding="utf-8") as f:
        f.write(html)
    # net = Network(notebook=False, directed=True)
    # net.from_nx(G)
    # net.show("taxonomy.html")
    print("Now save to Neo4j")
    nx_to_neo4j(G, "bolt://54.159.163.217:7687", "neo4j", "images-misalinement-crystal")
    nx.readwrite.json_graph.node_link_data(G)  # or export as needed
    print(f"Nodes: {G.number_of_nodes()}, Edges: {G.number_of_edges()}")
