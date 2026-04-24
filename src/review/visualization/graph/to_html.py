from html import escape
import re

RANKS = ["kingdom", "phylum", "class", "order", "family", "genus", "species"]
RANK_INDEX = {r: i for i, r in enumerate(RANKS)}

def parse_node_key(node_key: str):
    if not isinstance(node_key, str) or ":" not in node_key:
        return None, str(node_key)
    rank, val = node_key.split(":", 1)
    rank = rank.strip().lower()
    val = val.strip()
    return (rank if rank in RANK_INDEX else None, val)

def slugify(s: str) -> str:
    s = re.sub(r"\s+", "-", s.strip())
    s = re.sub(r"[^a-zA-Z0-9_.-]", "", s)
    return s or "item"

def _linkify(value: str) -> str:
    if not isinstance(value, str):
        return escape(str(value))
    v = value.strip()
    # simple DOI/URL detection
    if v.startswith("http://") or v.startswith("https://"):
        return f"<a href='{escape(v)}' target='_blank' rel='noopener'>{escape(v)}</a>"
    if v.lower().startswith("doi:") or v.lower().startswith("https://doi.org/"):
        return f"<a href='{escape(v if v.lower().startswith('http') else 'https://doi.org/' + v.split(':',1)[-1])}' target='_blank' rel='noopener'>{escape(v)}</a>"
    return escape(v)

def _render_kv_table(d: dict) -> str:
    rows = []
    for k, v in d.items():
        if isinstance(v, (list, tuple, set)):
            val = ", ".join(_linkify(x) if isinstance(x, str) else escape(str(x)) for x in v)
        elif isinstance(v, dict):
            val = "; ".join(f"{escape(str(ik))}={escape(str(iv))}" for ik, iv in v.items())
        else:
            val = _linkify(v) if isinstance(v, str) else escape(str(v))
        rows.append(f"<tr><th>{escape(str(k))}</th><td>{val}</td></tr>")
    return "<table class='sources'><tbody>" + "".join(rows) + "</tbody></table>"

def format_sources_accordions(sources, nid_prefix: str) -> str:
    """
    sources: list[dict] expected. Renders:
      <details class='sources-block'>
        <summary>Sources (N)</summary>
        <details class='source-item'>...</details>
        ...
      </details>
    """
    if not sources:
        return ""
    # If a single dict was provided, wrap it into a list for consistency
    if isinstance(sources, dict):
        sources = [sources]
    if not isinstance(sources, (list, tuple)):
        # Fallback to simple block
        return f"<div class='sources-wrap'><div class='sources'>{escape(str(sources))}</div></div>"

    items_html = []
    for i, s in enumerate(sources, 1):
        title_bits = []
        if isinstance(s, dict):
            # Use some nice fields for summary if present
            if "source" in s: title_bits.append(str(s.get("source")))
            if "doi" in s:    title_bits.append(str(s.get("doi")))
            if not title_bits:
                title_bits.append(f"Source {i}")
            summary = " — ".join(title_bits)
            body = _render_kv_table(s)
        else:
            summary = f"Source {i}"
            body = f"<div class='sources'>{escape(str(s))}</div>"

        sid = f"{nid_prefix}-src-{i}"
        items_html.append(
            f"<details id='{sid}' class='source-item'>"
            f"<summary>{escape(summary)}</summary>"
            f"{body}"
            f"</details>"
        )

    block_id = f"{nid_prefix}-sources"
    return (
        f"<details id='{block_id}' class='sources-block'>"
        f"<summary>Sources ({len(items_html)})</summary>"
        + "".join(items_html) +
        "</details>"
    )

def build_taxonomy_html(G, sources_attr="sources", title="Taxonomy Browser"):
    def node_data(n):
        return G.nodes[n] if n in G.nodes else {}

    def children_of(n):
        return list(G.successors(n))  # flip to predecessors if your edges are child→parent

    # Roots = nodes whose key starts with "kingdom"
    roots = [n for n in G.nodes if parse_node_key(n)[0] == "kingdom"]
    roots.sort(key=lambda n: parse_node_key(n)[1] or str(n))

    def render_node(n, path_ids):
        r, v = parse_node_key(n)
        rank_idx = RANK_INDEX.get(r, -1)
        nid_core = f"{r or 'node'}-{v}"
        nid = "-".join([slugify(p) for p in path_ids + [nid_core]])

        # Heading
        heading = f"{escape(v or str(n))}"
        if r:
            heading += f" <span class='rank-badge'>{escape(r)}</span>"

        # SOURCES as nested accordions (before children)
        srcs = node_data(n).get(sources_attr)
        sources_html = format_sources_accordions(srcs, nid_prefix=nid)

        # Children ordered by taxonomy rank then name
        kids = children_of(n)
        def sort_key(c):
            cr, cv = parse_node_key(c)
            return (RANK_INDEX.get(cr, 999), cv or str(c))
        kids.sort(key=sort_key)

        # Only descend to deeper ranks
        pruned = [c for c in kids if RANK_INDEX.get(parse_node_key(c)[0], 999) > rank_idx]

        children_html = "".join(render_node(c, path_ids + [nid_core]) for c in pruned)

        if not pruned:
            if sources_html:
                return (
                    f"<details id='{nid}' class='taxon leaf' open>"
                    f"<summary>{heading}</summary>"
                    f"{sources_html}"
                    f"</details>"
                )
            else:
                return (
                    f"<details id='{nid}' class='taxon leaf' open>"
                    f"<summary>{heading}</summary>"
                    f"<div class=\"leaf-note\">No further levels.</div>"
                    f"</details>"
                )

        return (
            f"<details id='{nid}' class='taxon'>"
            f"<summary>{heading}</summary>"
            f"{sources_html}"
            f"{children_html}"
            f"</details>"
        )

    body = "".join(render_node(r, []) for r in roots) if roots else "<div class='empty'>No kingdoms found.</div>"

    styles = """
    <style>
      :root { --gap: 0.5rem; --radius: 12px; --shadow: 0 2px 10px rgba(0,0,0,.06); }
      body { font-family: system-ui, -apple-system, Segoe UI, Roboto, Ubuntu, Cantarell, Arial; margin: 1.25rem; line-height: 1.5; }
      h1 { font-size: 1.4rem; margin-bottom: 1rem; }
      .controls { display: flex; gap: var(--gap); margin-bottom: 1rem; flex-wrap: wrap; }
      button { border: 1px solid #ddd; padding: .4rem .7rem; border-radius: 999px; cursor: pointer; background: #fafafa; }
      button:hover { background: #f2f2f2; }
      details.taxon { margin: .35rem 0; padding: .25rem .5rem; border-radius: var(--radius); border: 1px solid #eee; box-shadow: var(--shadow); }
      details.taxon > summary { cursor: pointer; font-weight: 600; }
      details.taxon > summary::-webkit-details-marker { display: none; }
      details.taxon > summary::before { display: inline-block; width: 1.1em; transition: transform .15s ease; }
      details[open] > summary::before { transform: rotate(90deg); }
      .rank-badge { font-size: .8rem; padding: .05rem .45rem; margin-left: .4rem; border-radius: 999px; background: #eef5ff; border: 1px solid #d8e7ff; }
      .leaf-note { margin-left: 1.4rem; font-size: .9rem; color: #666; }
      /* Sources */
      .sources-block { margin: .4rem 0 .6rem 1.4rem; border: 1px dashed #e8e8e8; border-radius: 10px; padding: .25rem .5rem; }
      .sources-block > summary { font-weight: 600; }
      .source-item { margin: .35rem 0 0 .8rem; }
      table.sources { width: max(40%, 420px); border-collapse: collapse; margin: .25rem 0 .5rem 0; }
      table.sources th, table.sources td { text-align: left; padding: .25rem .5rem; border-bottom: 1px solid #f0f0f0; vertical-align: top; }
      .empty { color: #a00; }
    </style>
    """

    script = """
    <script>
      function toggleAll(open) {
        document.querySelectorAll('details.taxon').forEach(d => { d.open = open; });
      }
      function filterItems(q) {
        q = (q || "").trim().toLowerCase();
    
        const allNodes = Array.from(document.querySelectorAll("details.taxon"));
        const roots = allNodes.filter(d => !d.parentElement.closest("details.taxon"));
    
        // Reset quickly when query is empty
        if (!q) {
          allNodes.forEach(d => {
            d.style.display = "";
            // keep current open/closed state; comment next line in if you want them collapsed:
            // d.open = false;
          });
          return;
        }
    
        // Check if this node matches itself (summary or its Sources block)
        function selfMatches(d) {
          const summary = d.querySelector(":scope > summary");
          const sumText = (summary ? summary.textContent : "").toLowerCase();
    
          const src = d.querySelector(":scope > .sources-block");
          const srcText = (src ? src.textContent : "").toLowerCase();
    
          return sumText.includes(q) || srcText.includes(q);
        }
    
        // Post-order traversal: decide visibility from children up
        function applyFilter(d) {
          const children = Array.from(d.querySelectorAll(":scope > details.taxon"));
          let anyChildVisible = false;
          for (const c of children) {
            if (applyFilter(c)) anyChildVisible = true;
          }
    
          const me = selfMatches(d);
          const visible = me || anyChildVisible;
    
          d.style.display = visible ? "" : "none";
          // Open branches that contain a match
          d.open = visible && (me || anyChildVisible);
    
          return visible;
        }
    
        roots.forEach(applyFilter);
      }
    </script>
    """

    controls = """
    <div class="controls">
      <button onclick="toggleAll(true)">Expand all</button>
      <button onclick="toggleAll(false)">Collapse all</button>
      <input type="search" placeholder="Filter by name or rank…" oninput="filterItems(this.value)" style="flex:1; min-width:220px; padding:.45rem .6rem; border-radius:12px; border:1px solid #ddd;">
    </div>
    """

    return (
        "<!doctype html><html><head><meta charset='utf-8'>"
        f"<title>{escape(title)}</title>{styles}</head><body>"
        f"<h1>{escape(title)}</h1>{controls}{body}{script}</body></html>"
    )
