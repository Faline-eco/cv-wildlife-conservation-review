import networkx as nx


def prepare_graph_for_graphml(G: nx.Graph) -> nx.Graph:
    """
    Returns a copy of G where any list-valued attributes are converted to
    comma-separated strings, so it's safe to export to GraphML.
    """
    G2 = nx.Graph() if not G.is_directed() else nx.DiGraph()
    G2.add_nodes_from(G.nodes())
    G2.add_edges_from(G.edges())

    # Copy node attributes with list-to-string conversion
    for n, attrs in G.nodes(data=True):
        new_attrs = {}
        for k, v in attrs.items():
            if isinstance(v, list):
                # Convert list elements to strings and join
                new_attrs[k] = ", ".join(str(x) for x in v)
            elif isinstance(v, dict):
                # If you have nested dicts like "sources", handle them separately
                new_attrs[k] = str(v)
            else:
                new_attrs[k] = v
        G2.nodes[n].update(new_attrs)

    # Copy edge attributes with list-to-string conversion
    for u, v, attrs in G.edges(data=True):
        new_attrs = {}
        for k, val in attrs.items():
            if isinstance(val, list):
                new_attrs[k] = ", ".join(str(x) for x in val)
            elif isinstance(val, dict):
                new_attrs[k] = str(val)
            else:
                new_attrs[k] = val
        G2.edges[u, v].update(new_attrs)

    return G2