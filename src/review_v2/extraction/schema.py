"""Extraction schema v2: closed vocabularies and the JSON schema enforced on the extractor output."""

SCHEMA_VERSION = "2.0"

CRITERIA = ["none", "E-PLANT", "E-AGRI", "E-LAB", "E-CAPTIVE", "E-HUMAN", "E-NOCV", "E-AUDIO",
            "E-REVIEW", "E-GENERIC"]
SUBJECT_TYPES = ["wild_free_ranging", "captive_or_zoo", "laboratory", "livestock_or_pet", "specimen",
                 "mixed", "no_animals", "not_reported"]
PAPER_TYPES = ["method", "application", "dataset", "benchmark", "review", "other"]

PLATFORMS = [
    "Camera Trap", "Non-specialized Camera", "Unmanned aerial vehicle (UAV; e.g. drone)",
    "Crewed aerial vehicle (CAV; e.g. plane, helicopter)", "Satellite",
    "Remotely operated underwater vehicle (ROV)", "Autonomous Underwater Vehicle (AUV)",
    "Stationary underwater camera", "Ground Robot", "Animal-mounted Camera", "Depth Sensor / Lidar",
    "Web / citizen-science images", "Other", "Not reported",
]
SPECTRA = [
    "RGB (visible)", "Grayscale", "Near Infrared (NIR)", "Long-wave Infrared / Thermal (LWIR)",
    "Short-wave Infrared (SWIR)", "Mid-wave Infrared (MWIR)", "Ultraviolet (UV-A/B)", "Multispectral",
    "Hyperspectral", "Panchromatic", "Depth / LiDAR", "Radar / Synthetic-Aperture Radar (SAR)",
    "Active Imaging Sonar (multibeam)", "Other",
]
HABITATS = [
    "Forest", "Savanna", "Shrubland", "Grassland", "Wetlands (inland)",
    "Rocky areas (e.g. inland cliffs, mountain peaks)", "Cave and subterranean habitats (non-aquatic)",
    "Desert", "Marine", "Artificial Terrestrial", "Artificial Aquatic", "Other", "Not reported",
]
TASKS = ["Detection", "Classification", "Segmentation", "Tracking", "Re-Identification",
         "Activity Recognition", "Pose Estimation", "Reconstruction", "Synthesis", "Counting", "Other"]
ALGO_TYPES = ["classical_image_processing", "classical_machine_learning", "cnn", "transformer",
              "foundation_model", "other"]


def _obj(props):
    return {"type": "object", "properties": props, "required": list(props), "additionalProperties": False}


def _enum(values):
    return {"type": "string", "enum": values}


STR = {"type": "string"}
EVIDENCE = {"quote": STR, "page": {"type": "integer"}}
FLAG = _obj({"value": {"type": "boolean"}, **EVIDENCE})

SCHEMA = _obj({
    "eligibility": _obj({
        "include": {"type": "boolean"}, "criterion": _enum(CRITERIA),
        "subject_type": _enum(SUBJECT_TYPES), "paper_type": _enum(PAPER_TYPES), "reason": STR,
        **EVIDENCE,
    }),
    "settings": {"type": "array", "items": _obj({
        "platform": _enum(PLATFORMS),
        "spectra": {"type": "array", "items": _obj({
            "value": _enum(SPECTRA), "source": _enum(["text", "caption", "implied"]), **EVIDENCE})},
        "habitat": _enum(HABITATS),
        "countries": {"type": "array", "items": STR},
        "location_detail": STR,
        "species": {"type": "array", "items": STR},
        "datasets": {"type": "array", "items": STR},
        **EVIDENCE,
    })},
    "species": {"type": "array", "items": _obj({
        "name": STR, "scientific_name": STR,
        "rank": _enum(["species", "genus", "family", "order", "class", "group"]),
        "role": _enum(["target", "benchmark_class", "mentioned"]),
        "domestic": {"type": "boolean"}, "n_taxa": {"type": "integer"}, **EVIDENCE,
    })},
    "datasets": {"type": "array", "items": _obj({
        "name": STR,
        "role": _enum(["collected_by_authors", "public_wildlife_dataset", "generic_benchmark",
                       "pretraining_only"]),
        "availability": _enum(["public", "on_request", "not_stated"]),
        "origin": _enum(["field_deployment", "citizen_science", "web_scraped", "captive_or_lab",
                         "synthetic", "mixed", "not_stated"]),
        **EVIDENCE,
    })},
    "tasks": {"type": "array", "items": _obj({
        "task": _enum(TASKS), "role": _enum(["primary", "auxiliary"]), **EVIDENCE})},
    "algorithms": {"type": "array", "items": _obj({
        "name": STR, "type": _enum(ALGO_TYPES), "role": _enum(["proposed", "backbone", "baseline"]),
        **EVIDENCE})},
    "flags": _obj({"cost_reported": FLAG, "ethics_statement": FLAG, "explainability": FLAG}),
})
