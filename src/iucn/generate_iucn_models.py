# generate_iucn_models.py
# Python 3.9+; Pydantic v2 (works with v1 for these basics too)

from __future__ import annotations

import re
from collections import defaultdict
from typing import Dict, List, Tuple

# ---------------------------
# 0.) Copy and paste the IUCN habitat text (current version 3.1)
# ---------------------------

iucn_habitat_text = """
1. Forest
1.1. Forest – Boreal
1.2. Forest - Subarctic
1.3. Forest – Subantarctic
1.4. Forest – Temperate
1.5. Forest – Subtropical/tropical dry
1.6. Forest – Subtropical/tropical moist lowland
1.7. Forest – Subtropical/tropical mangrove vegetation above high tide level
1.8. Forest – Subtropical/tropical swamp
1.9. Forest – Subtropical/tropical moist montane
 
2. Savanna
2.1. Savanna - Dry
2.2. Savanna - Moist
 
3. Shrubland
3.1. Shrubland – Subarctic
3.2. Shrubland – Subantarctic
3.3. Shrubland – Boreal
3.4. Shrubland –Temperate
3.5. Shrubland – Subtropical/tropical dry
3.6. Shrubland – Subtropical/tropical moist
3.7. Shrubland – Subtropical/tropical high altitude
3.8. Shrubland – Mediterranean-type shrubby vegetation
 
4. Grassland
4.1. Grassland – Tundra
4.2. Grassland – Subarctic
4.3. Grassland – Subantarctic
4.4. Grassland – Temperate
4.5. Grassland – Subtropical/tropical dry
4.6. Grassland – Subtropical/tropical seasonally wet/flooded
4.7. Grassland – Subtropical/tropical high altitude
 
5. Wetlands (inland)
5.1. Wetlands (inland) – Permanent rivers/streams/creeks (includes waterfalls)
5.2. Wetlands (inland) – Seasonal/intermittent/irregular rivers/streams/creeks
5.3. Wetlands (inland) – Shrub dominated wetlands
5.4. Wetlands (inland) – Bogs, marshes, swamps, fens, peatlands
5.5. Wetlands (inland) – Permanent freshwater lakes (over 8 ha)
5.6. Wetlands (inland) – Seasonal/intermittent freshwater lakes (over 8 ha)
5.7. Wetlands (inland) – Permanent freshwater marshes/pools (under 8 ha)
5.8. Wetlands (inland) – Seasonal/intermittent freshwater marshes/pools (under 8 ha)
5.9. Wetlands (inland) – Freshwater springs and oases
5.10. Wetlands (inland) – Tundra wetlands (inc. pools and temporary waters from snowmelt)
5.11. Wetlands (inland) – Alpine wetlands (inc. temporary waters from snowmelt)
5.12. Wetlands (inland) – Geothermal wetlands
5.13. Wetlands (inland) – Permanent inland deltas
5.14. Wetlands (inland) – Permanent saline, brackish or alkaline lakes
5.15. Wetlands (inland) – Seasonal/intermittent saline, brackish or alkaline lakes and flats
5.16. Wetlands (inland) – Permanent saline, brackish or alkaline marshes/pools
5.17. Wetlands (inland) – Seasonal/intermittent saline, brackish or alkaline marshes/pools
5.18. Wetlands (inland) – Karst and other subterranean hydrological systems (inland)
 
6. Rocky Areas (e.g., inland cliffs, mountain peaks)
 
7. Caves & Subterranean Habitats (non-aquatic)
7.1. Caves and Subterranean Habitats (non-aquatic) – Caves
7.2. Caves and Subterranean Habitats (non-aquatic) – Other subterranean habitats
 
8. Desert
8.1. Desert – Hot
8.2. Desert – Temperate
8.3. Desert – Cold
 
9. Marine Neritic
9.1. Marine Neritic – Pelagic
9.2. Marine Neritic – Subtidal rock and rocky reefs
9.3. Marine Neritic – Subtidal loose rock/pebble/gravel
9.4. Marine Neritic – Subtidal sandy
9.5. Marine Neritic – Subtidal sandy-mud
9.6. Marine Neritic – Subtidal muddy
9.7. Marine Neritic – Macroalgal/kelp
9.8. Marine Neritic – Coral Reef
9.8.1. Outer reef channel
9.8.2. Back slope
9.8.3. Foreslope (outer reef slope)
9.8.4. Lagoon
9.8.5. Inter-reef soft substrate
9.8.6. Inter-reef rubble substrate
9.9 Seagrass (Submerged)
9.10 Estuaries
 
10 Marine Oceanic
10.1 Epipelagic (0–200 m)
10.2 Mesopelagic (200–1,000 m)
10.3 Bathypelagic (1,000–4,000 m)
10.4 Abyssopelagic (4,000–6,000 m)
 
11 Marine Deep Ocean Floor (Benthic and Demersal)
11.1 Continental Slope/Bathyl Zone (200–4,000 m)
11.1.1 Hard Substrate
11.1.2 Soft Substrate
11.2 Abyssal Plain (4,000–6,000 m)
11.3 Abyssal Mountain/Hills (4,000–6,000 m)
11.4 Hadal/Deep Sea Trench (>6,000 m)
11.5 Seamount
11.6 Deep Sea Vents (Rifts/Seeps)
 
12 Marine Intertidal
12.1 Rocky Shoreline
12.2 Sandy Shoreline and/or Beaches, Sand Bars, Spits, etc.
12.3 Shingle and/or Pebble Shoreline and/or Beaches
12.4 Mud Shoreline and Intertidal Mud Flats
12.5 Salt Marshes (Emergent Grasses)
12.6 Tidepools
12.7 Mangrove Submerged Roots
 
13 Marine Coastal/Supratidal
13.1 Sea Cliffs and Rocky Offshore Islands
13.2 Coastal Caves/Karst
13.3 Coastal Sand Dunes
13.4 Coastal Brackish/Saline Lagoons/Marine Lakes
13.5 Coastal Freshwater Lakes
 
14 Artificial - Terrestrial
14.1 Arable Land
14.2 Pastureland
14.3 Plantations
14.4 Rural Gardens
14.5 Urban Areas
14.6 Subtropical/Tropical Heavily Degraded Former Forest
 
15 Artificial - Aquatic
15.1 Water Storage Areas [over 8 ha]
15.2 Ponds [below 8 ha]
15.3 Aquaculture Ponds
15.4 Salt Exploitation Sites
15.5 Excavations (open)
15.6 Wastewater Treatment Areas
15.7 Irrigated Land [includes irrigation channels]
15.8 Seasonally Flooded Agricultural Land
15.9 Canals and Drainage Channels, Ditches
15.10 Karst and Other Subterranean Hydrological Systems [human-made]
15.11 Marine Anthropogenic Structures
15.12 Mariculture Cages
15.13 Mari/Brackish-culture Ponds
 
16 Introduced Vegetation
 
17 Other
 
18 Unknown
"""

# ---------------------------
# 1) Your source dictionary
# ---------------------------
# Regex: capture the numeric code (ending with a dot) and the rest of the line as the label.
line_re = re.compile(r'^\s*((?:\d+\.)+)\s+(.*\S)\s*$', flags=re.UNICODE)

iucn_habitats: Dict[str, str] = {}
for line in iucn_habitat_text.splitlines():
    if not line.strip():
        continue  # skip blank lines
    m = line_re.match(line)
    if m:
        code, label = m.groups()
        iucn_habitats[code] = label
    else:
        # If any line doesn't match, you can log or handle it here.
        # print(f"Skipped (no match): {line!r}")
        pass



# ---------------------------
# 2) Helpers for parsing & naming
# ---------------------------

def split_code(code: str) -> List[int]:
    """Convert '9.8.1.' -> [9, 8, 1]."""
    parts = [p for p in code.split(".") if p]
    return [int(p) for p in parts]


def code_parent(code: str) -> str | None:
    parts = [p for p in code.split(".") if p]
    if len(parts) <= 1:
        return None
    return ".".join(parts[:-1]) + "."


def to_snake(label: str) -> str:
    """Sanitize label to a valid snake_case identifier."""
    # Lowercase, replace non-alphanumerics with space
    s = re.sub(r"[^\w]+", " ", label, flags=re.UNICODE)
    s = s.strip().lower()
    s = re.sub(r"\s+", "_", s)
    if re.match(r"^\d", s):
        s = "_" + s
    if not s:
        s = "field"
    return s


def to_camel(label: str) -> str:
    """Sanitize label to a CamelCase class name."""
    parts = re.sub(r"[^\w]+", " ", label, flags=re.UNICODE).strip().split()
    name = "".join(p.capitalize() for p in parts if p)
    if re.match(r"^\d", name or ""):
        name = "N" + name
    return name or "Model"


def sort_key_by_code(code: str) -> Tuple[int, ...]:
    return tuple(split_code(code))


# ---------------------------
# 3) Build a simple tree index
# ---------------------------

class Node:
    __slots__ = ("code", "label", "children")
    def __init__(self, code: str, label: str):
        self.code = code
        self.label = label
        self.children: List[str] = []  # store child codes for simplicity

nodes: Dict[str, Node] = {c: Node(c, lbl) for c, lbl in iucn_habitats.items()}

for code in sorted(iucn_habitats.keys(), key=sort_key_by_code):
    parent = code_parent(code)
    if parent and parent in nodes:
        nodes[parent].children.append(code)

# Level classification
level1_codes = [c for c in iucn_habitats if len(split_code(c)) == 1]
level2_codes = [c for c in iucn_habitats if len(split_code(c)) == 2]
level3_codes = [c for c in iucn_habitats if len(split_code(c)) == 3]

# Level-2s that have children (i.e., become classes)
level2_with_children = [c for c in level2_codes if nodes[c].children]


# ---------------------------
# 4) Generate Pydantic code
# ---------------------------

HEADER = '''\
from __future__ import annotations
from pydantic import BaseModel, Field

"""
Auto-generated from the IUCN habitats dictionary.

Rules:
- Level-1 codes (e.g., "1.") become classes.
- Level-2 codes without children become boolean fields on their Level-1 class.
- Level-2 codes WITH children become their own classes (fields are the Level-3 leaves),
  and the corresponding field on the Level-1 class is typed as that class.
"""
'''

def unique_name(base: str, used: set[str]) -> str:
    """Ensure no duplicate identifiers within the same scope."""
    name = base
    i = 2
    while name in used:
        name = f"{base}_{i}"
        i += 1
    used.add(name)
    return name


def emit_level2_class(code: str, parent_label: str) -> str:
    """Emit a Level-2 class for a node that has Level-3 children."""
    node = nodes[code]
    # Class name is prefixed with the Level-1 class to avoid cross-group collisions.
    cls_name = to_camel(parent_label) + to_camel(node.label)
    lines = [f"class {cls_name}(BaseModel):"]
    # Collect level-3 children as boolean fields
    used_fields: set[str] = set()
    for child_code in sorted(nodes[code].children, key=sort_key_by_code):
        child_label = nodes[child_code].label
        field_name = unique_name(to_snake(child_label), used_fields)
        # Add description for readability
        lines.append(f"    {field_name}: bool = Field(False, description={child_label!r})")
    if len(lines) == 1:
        field_name = unique_name(to_snake(cls_name), used_fields)
        child_label = nodes[cls_name].label
        lines.append(f"    {field_name}: bool = Field(False, description={child_label!r})")
    lines.append("")  # blank line after class
    return "\n".join(lines)


def emit_level1_class(code: str) -> str:
    """Emit a Level-1 class. Level-2 leaves => bool fields; Level-2 with children => nested class fields."""
    node = nodes[code]
    parent_label = node.label
    parent_cls = to_camel(parent_label)

    # Build a map for level-2 children
    level2_children = sorted(node.children, key=sort_key_by_code)
    lines = [f"class {parent_cls}(BaseModel):"]
    used_fields: set[str] = set()

    for l2_code in level2_children:
        l2_label = nodes[l2_code].label
        field_name = unique_name(to_snake(_strip_parent_from_l2_label(l2_label, parent_label)), used_fields)

        if nodes[l2_code].children:  # becomes its own class
            l2_cls_name = to_camel(parent_label) + to_camel(l2_label)
            # default_factory ensures a fresh nested model instance
            lines.append(
                f"    {field_name}: {l2_cls_name} = Field(default_factory={l2_cls_name}, "
                f"description={l2_label!r})"
            )
        else:
            lines.append(f"    {field_name}: bool = Field(False, description={l2_label!r})")

    if len(lines) == 1:
        lines.append("    pass")
    lines.append("")
    return "\n".join(lines)


def _strip_parent_from_l2_label(l2_label: str, parent_label: str) -> str:
    """
    For nicer field names, drop the duplicated parent part if present, e.g.
    'Marine Neritic – Coral Reef' -> 'Coral Reef' when parent is 'Marine Neritic'.
    """
    # Normalize dashes and spaces, then try a few common patterns
    # Replace various dashes with a single hyphen for matching
    norm = re.sub(r"[–—−]+", "-", l2_label)
    parent_norm = re.sub(r"[–—−]+", "-", parent_label)
    for sep in [" - ", " – ", " — ", " -", "- ", " –", "– "]:
        token = parent_norm + sep
        if norm.startswith(token):
            return l2_label[len(token):].strip()
    return l2_label


def generate_models_module() -> str:
    parts: List[str] = [HEADER]

    # First: all Level-2 classes that have children (must appear before L1 classes that reference them)
    for l2_code in sorted(level2_with_children, key=sort_key_by_code):
        parent_code = code_parent(l2_code)
        assert parent_code is not None
        parent_label = nodes[parent_code].label
        parts.append(emit_level2_class(l2_code, parent_label))

    # Then: all Level-1 classes
    for l1_code in sorted(level1_codes, key=sort_key_by_code):
        parts.append(emit_level1_class(l1_code))

    # Optional: aggregate root model to hold everything
    parts.append("class IUCNHabitats(BaseModel):")
    used_fields: set[str] = set()
    for l1_code in sorted(level1_codes, key=sort_key_by_code):
        l1_label = nodes[l1_code].label
        field_name = unique_name(to_snake(l1_label), used_fields)
        cls_name = to_camel(l1_label)
        parts.append(
            f"    {field_name}: {cls_name} = Field(default_factory={cls_name}, description={l1_label!r})"
        )
    parts.append("")  # trailing newline

    return "\n".join(parts)


if __name__ == "__main__":
    module_text = generate_models_module()
    out_path = "iucn_models.py"
    # with open(out_path, "w", encoding="utf-8") as f:
    #     f.write(module_text)
    print(f"Wrote {out_path}")

    # ---- NEW: print the names of the leaf classes (no changes to model names) ----
    leaf_class_names = [
        to_camel(nodes[c].label)
        for c in sorted(level1_codes, key=sort_key_by_code)
    ]
    print("Leaf model classes:")
    for name in leaf_class_names:
        print(name)
