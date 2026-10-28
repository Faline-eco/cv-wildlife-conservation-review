"""Reference search string of the review (variant actually used in the library search,
manuscript source line 511) and its translation into the syntax of each metadata index."""

POPULATION = ['"computer vision"', '"machine vision"']

INTERVENTION_TERMS = [
    "detection", "recognition", "prediction", "identification", "segmentation", "tracking",
    "classification", "pose", "estimation", "generation", "synthesis", "camera", "satellite",
    "UAV", "ROV", "drone", "aircraft", "plane", '"remote sensing"', '"animal borne"',
]
INTERVENTION_PLATFORM_A = ["aerial", "airborne", "terrestrial", "ground", "underwater", "marine"]
INTERVENTION_PLATFORM_B = ["vehicle", "robot"]

CONTEXT = ["wildlife", "animal", "ecology", "conservation"]

YEAR_FROM = 2014
YEAR_TO = 2026


def _or(terms):
    return "(" + " OR ".join(terms) + ")"


def boolean_query() -> str:
    """Generic Boolean form, identical in structure to the string in the manuscript."""
    intervention = (
        "(" + " OR ".join(INTERVENTION_TERMS)
        + " OR (" + _or(INTERVENTION_PLATFORM_A) + " AND " + _or(INTERVENTION_PLATFORM_B) + "))"
    )
    return f"{_or(POPULATION)} AND {intervention} AND {_or(CONTEXT)}"


def scopus_query(year_from: int = YEAR_FROM, year_to: int = YEAR_TO) -> str:
    return (
        f"TITLE-ABS-KEY({boolean_query()})"
        f" AND PUBYEAR > {year_from - 1} AND PUBYEAR < {year_to + 1}"
        " AND LANGUAGE(english) AND (DOCTYPE(ar) OR DOCTYPE(cp))"
    )


def openalex_filter(year_from: int = YEAR_FROM, year_to: int = YEAR_TO) -> str:
    return (
        f"title_and_abstract.search:{boolean_query()},"
        f"publication_year:{year_from}-{year_to},language:en,type:article"
    )


def pubmed_query(year_from: int = YEAR_FROM, year_to: int = YEAR_TO) -> str:
    def tiab(terms):
        return "(" + " OR ".join(f"{t}[tiab]" for t in terms) + ")"

    intervention = (
        "(" + " OR ".join(f"{t}[tiab]" for t in INTERVENTION_TERMS)
        + " OR (" + tiab(INTERVENTION_PLATFORM_A) + " AND " + tiab(INTERVENTION_PLATFORM_B) + "))"
    )
    return (
        f"{tiab(POPULATION)} AND {intervention} AND {tiab(CONTEXT)}"
        f" AND ({year_from}:{year_to}[dp]) AND english[la]"
    )
