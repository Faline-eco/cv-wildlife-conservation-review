from neo4j import GraphDatabase


def nx_to_neo4j(G, uri, user, password):
    def split_key(k):
        rank, key = k.split(":", 1)
        return rank.title(), key

    nodes = []
    for k, data in G.nodes(data=True):
        rank_label, key = split_key(k)
        node_structure = {
            "gbifKey": key,                 # numeric GBIF key
            "rankLabel": rank_label,        # e.g. "Species", "Genus", "Family"...
            "name": data.get("name"),
            "rank": data.get("rank"),
            "label": data.get("label"),
            "found_in_review": "Rank"
        }

        if data.get("sources") is not None:
            node_structure["sources"] = [x["source"] for x in data.get("sources")]
            node_structure["dois"] = [x["doi"] for x in data.get("sources")]
            # node_structure["payloads"] = list(set([habitat for source in data.get("payloads", []) for habitat in source["payloads"]]))
            node_structure["found_in_review"] = "Paper"

        nodes.append(node_structure)

    def rel_split(k):  # parent/child keys also need parsing
        return k.split(":",1)[1]

    rels = [{"parent": rel_split(u), "child": rel_split(v)} for u, v in G.edges()]

    cypher_constraint = """
    CREATE CONSTRAINT taxon_gbif_unique IF NOT EXISTS
    FOR (t:Taxon) REQUIRE t.gbifKey IS UNIQUE;
    """

    cypher_nodes = """
    UNWIND $rows AS row
    MERGE (t:Taxon {gbifKey: row.gbifKey})
    SET t.name = row.name,
        t.rank = row.rank,
        t.label = row.label,
        t.dois = row.dois,
        t.habitats = row.habitats,
        t.imaging_methods = row.imaging_methods
    WITH t, row
    CALL apoc.create.addLabels(id(t), [row.rankLabel, row.found_in_review]) YIELD node
    RETURN count(node) AS _;  // optional
    """

    cypher_rels = """
    UNWIND $rows AS row
    MATCH (p:Taxon {gbifKey: row.parent})
    MATCH (c:Taxon {gbifKey: row.child})
    MERGE (p)-[:PARENT_OF]->(c);
    """

    driver = GraphDatabase.driver(uri, auth=(user, password))
    with driver.session() as s:
        s.run(cypher_constraint)
        s.run(cypher_nodes, rows=nodes)
        s.run(cypher_rels, rows=rels)
    driver.close()