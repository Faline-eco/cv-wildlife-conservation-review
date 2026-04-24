# wildcv_review/extractors.py
import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Tuple, Type, Optional, Iterable, Union, Any

from pydantic import BaseModel, ValidationError

from iucn import iucn_models
from iucn.gemini_iucn_models import gemini_safe_model
from iucn.generate_iucn_models import to_camel, to_snake
from iucn.iucn_models import IUCNHabitats
from review.schemas import IsCVWildlife, Datasets, StringList, ItemList, TopicSpec, DatasetEvidenceList, \
    ReviewedPaperEvidenceList
from review.topics import HABITAT_EVIDENCE_PROMPT, ARRAY_WITH_EVIDENCE_GUIDANCE, REVIEW_ONLY_GUARD
from review.utils import parse_json_array, dedup_preserve_order, filter_allowed, extract_true_labels, \
    labels_to_allowed_list_str, canonical_path_label, items_to_datasets
from review.verify import verify_items_against_pdf

SYSTEM_ECO_CS = (
    "Assume the role of an expert researcher in ecology & computer vision. "
    "Your job is to extract meaningful information from the given content."
)
SYSTEM_ECO_ONLY = (
    "Assume the role of an expert researcher in ecology. "
    "Your job is to extract meaningful information from the given content."
)

async def check_topic(llm, pdf_path: str) -> IsCVWildlife:
    async with llm.uploaded_file(pdf_path) as f:
        prompt = ("Does the paper conduct a **new** study using computer vision in wildlife conservation "
                  "(animals in focus, not plants/agriculture/aquaculture/poachers/medical)? "
                  "Exclude review articles. Return JSON with fields: "
                  "`is_computer_vision_in_wildlife_study`, `is_review`, `explanation`.")
        text = await llm.generate([f, prompt], system_instruction=SYSTEM_ECO_CS, response_model=IsCVWildlife)
    return IsCVWildlife.model_validate_json(text)

async def get_datasets(
    llm,
    pdf_path: str,
    dataset_prompt: str
) -> Union[Datasets, Dict[str, Any]]:
    """
    Evidence-aware, verified dataset extraction.

    - Asks the model for (value=name|private, url?, quote, page).
    - Verifies quotes+pages against the local PDF via verify_items_against_pdf().
    - strict_mode=True  -> returns Datasets with only verified items.
    - strict_mode=False -> returns {"evidences":[...], "verified": Datasets, "unverified": Datasets}.

    Tip: configure your LLM client with deterministic decoding (temperature=0, top_p=0).
    """
    async with llm.uploaded_file(pdf_path) as f:
        # Ask for schema-enforced JSON with evidence
        text = await llm.generate(
            contents=[f, dataset_prompt],
            system_instruction=SYSTEM_ECO_CS,
            response_model=DatasetEvidenceList,
        )

    # Parse + verify
    out = DatasetEvidenceList.model_validate_json(text)
    evidence_items = [i.model_dump() for i in out.items]

    verified_items, unverified_items = verify_items_against_pdf(Path(pdf_path), evidence_items)

    # Convert to your schema
    verified_ds = verified_items
    unverified_ds = unverified_items

    return {
        "evidences": evidence_items,
        "verified": verified_ds,
        "unverified": unverified_ds,
    }

def _human_label_for_field(field_info) -> str:
    """Prefer the field description we emitted in codegen; fallback to field name."""
    desc = getattr(field_info, "description", None)
    if desc:
        return desc
    return field_info.alias or field_info.title or ""


def _build_model_map(use_leaf: bool = False) -> Dict[str, Tuple[Type[BaseModel], str]]:
    """
    Build a map:
        field_name -> (TopLevelModelClassToUse, human_label_for_prompt)
    If use_leaf=True, use the corresponding *Leaf class (e.g., ForestLeaf).
    """
    model_map: Dict[str, Tuple[Type[BaseModel], str]] = {}

    for field_name, field in IUCNHabitats.model_fields.items():
        # The field's annotation is the top-level class (e.g., Forest, Savanna, ...)
        model_cls = field.annotation  # type: ignore[attr-defined]
        if not isinstance(model_cls, type) or not issubclass(model_cls, BaseModel):
            # Skip any non-BaseModel fields (unlikely in this design)
            continue

        human_label = _human_label_for_field(field)
        if use_leaf:
            # Convert Forest -> ForestLeaf etc.
            leaf_name = model_cls.__name__ + "Leaf"
            model_cls = getattr(iucn_models, leaf_name)  # raises if missing, which is good
        model_map[field_name] = (model_cls, human_label or model_cls.__name__)

    return model_map

def _fill_missing_booleans(model_cls: Type[BaseModel], data: dict) -> dict:
    """
    Defensive: if Gemini drops required fields, fill them with False (or empty object) so
    validation against your original model cannot fail.
    """
    fixed = dict(data)
    for name, f in model_cls.model_fields.items():
        typ = f.annotation
        if isinstance(typ, type) and issubclass(typ, BaseModel):
            sub = fixed.get(name) or {}
            fixed[name] = _fill_missing_booleans(typ, sub)
        else:
            fixed.setdefault(name, False)
    return fixed

async def get_habitats(
    llm,
    pdf_path: str,
    habitat_prompt: str,
    *,
    use_leaf: bool = False,
) -> Tuple[IUCNHabitats, Dict]:
    """
    Returns:
        (boolean_model, verified_labels) in strict mode
        (boolean_model, {"verified":[...], "unverified":[...]}) in audit mode

    - boolean_model: your composed IUCNHabitats instance (same as your current function)
    - verified_labels: canonical strings like "Marine Neritic — Coral Reef: Lagoon"
    """
    model_map = _build_model_map(use_leaf=use_leaf)  # {group_key: (ModelClass, group_human_label)}

    # First pass: boolean predictions per group, exactly as your current implementation
    async with llm.uploaded_file(pdf_path) as f:
        typed_results: Dict[str, BaseModel] = {}
        group_true_labels: Dict[str, List[str]] = {}  # group_human_label -> [leaf labels]

        for group_key, (model_cls, human_label) in model_map.items():
            # Prompt for booleans (your schema-only technique)
            prompt = habitat_prompt.replace("{human_label}", human_label).replace("{model_cls.__name__}", model_cls.__name__)
            schema_only = gemini_safe_model(model_cls)

            text = await llm.generate(
                [f, prompt],
                system_instruction=SYSTEM_ECO_ONLY,
                response_model=schema_only,
            )

            # Validate against your original class
            try:
                parsed = model_cls.model_validate_json(text)
            except ValidationError:
                raw = json.loads(text)
                filled = _fill_missing_booleans(model_cls, raw if isinstance(raw, Dict) else {})
                parsed = model_cls.model_validate(filled)

            typed_results[group_key] = parsed

            # Collect the human-readable labels for fields set to True
            positives = extract_true_labels(model_cls, parsed)
            if positives:
                group_true_labels[human_label] = positives

        # Second pass: ask for evidence only for labels predicted True
        verified_all: List[str] = []
        unverified_all: List[str] = []
        items_all = []
        logging.info(f"Verifying extracted habitats: {group_true_labels}")
        for human_label, positives in group_true_labels.items():
            allowed_str = labels_to_allowed_list_str(positives)
            ev_prompt = HABITAT_EVIDENCE_PROMPT.replace("{human_label}", f"{human_label}").replace("{allowed_labels}", f"{allowed_str}")

            text = await llm.generate(
                [f, ev_prompt],
                system_instruction=SYSTEM_ECO_ONLY,
                response_model=ItemList,  # {"items":[{"value": str, "evidence": {...}}]}
            )
            out = ItemList.model_validate_json(text)
            items = [i.model_dump() for i in out.items]

            # Verify against the PDF text
            verified, unverified = verify_items_against_pdf(Path(pdf_path), items)

            # Canonicalize values with group path and dedupe
            v_values = [
                canonical_path_label(human_label, x.get("value", "").strip())
                for x in verified if x.get("value")
            ]
            u_values = [
                canonical_path_label(human_label, x.get("value", "").strip())
                for x in unverified if x.get("value")
            ]

            normalized_items = []
            for item in items:
                c = item.copy()
                c["value"] = to_camel(human_label) + "." + to_snake(c["value"])
                normalized_items.append(c)

            items_all.extend(normalized_items)
            verified_all.extend(v_values)
            unverified_all.extend(u_values)

    verified_all = dedup_preserve_order(verified_all)
    unverified_all = dedup_preserve_order(unverified_all)

    return IUCNHabitats(**typed_results), {"evidences": items_all, "verified": verified_all, "unverified": unverified_all}


async def extract_topics(
    llm,
    pdf_path: str,
    topics: List[TopicSpec],
    *,
    strict_mode: bool = False,  # "strict" (only verified) or "audit" (include unverified)
) -> Dict[str, List[str] | Dict[str, List[str]]]:
    """
    Evidence-aware, verified topic extraction.

    - Uses native JSON schema (ItemList) to force shape.
    - Requests short verbatim quotes + page numbers.
    - Verifies quotes against the local PDF text.
    - Applies optional allowed_vocab filtering per topic.
    - Returns only verified items in 'strict' mode, or a dict with both
      lists in 'audit' mode: {"verified":[...], "unverified":[...]}.

    NOTE: For best results, set your LLM client to deterministic decoding
          (e.g., temperature=0, top_p=0) in its configuration.
    """
    results: Dict[str, List[str] | Dict[str, List[str]]] = {}

    # Upload once per PDF; reuse handle across calls
    async with llm.uploaded_file(pdf_path) as f:
        for spec in topics:
            logging.info(f"Checking topic {spec.key}")
            # Build a per-topic prompt
            constraints = []
            if spec.allowed_vocab:
                constraints.append(
                    "Allowed values only: " + ", ".join(spec.allowed_vocab) + ". "
                    "If the paper uses synonyms, map them to the closest allowed value; "
                    "if no allowed value matches, do not include the item."
                )
            if spec.require_images_only:
                constraints.append(
                    "Consider ONLY information derived from figures/diagrams/captions, not the main text."
                )

            prompt = (
                spec.prompt.strip() + "\n\n" +
                ((" ".join(constraints) + "\n") if constraints else "") +
                ARRAY_WITH_EVIDENCE_GUIDANCE
            )
            text = None
            retries = 0
            while text is None and retries < 3:
                # Call the model with schema-enforced JSON
                text = await llm.generate(
                    contents=[f, prompt],
                    system_instruction=SYSTEM_ECO_CS,
                    response_model=ItemList,
                )
                retries += 1
            if text is None:
                continue
            # Parse and verify
            out = ItemList.model_validate_json(text)

            items = [i.model_dump() for i in out.items]
            verified, unverified = verify_items_against_pdf(Path(pdf_path), items)

            # Pull only the 'value' fields
            v_values = [x.get("value", "").strip() for x in verified if x.get("value")]
            u_values = [x.get("value", "").strip() for x in unverified if x.get("value")]

            # Apply allowed vocabulary constraint if provided
            if spec.allowed_vocab:
                v_values = filter_allowed(v_values, spec.allowed_vocab)
                # In audit mode, report unverified that WOULD HAVE been allowed (optional)
                if not strict_mode:
                    u_values = filter_allowed(u_values, spec.allowed_vocab)

            # Deduplicate, preserve order
            v_values = dedup_preserve_order(v_values)
            u_values = dedup_preserve_order(u_values)

            # Record
            if strict_mode:
                results[spec.key] = v_values
            else:
                results[spec.key] = {"evidences": items, "verified": v_values, "unverified": u_values}
    return results

async def summarize_paper(llm, pdf_path: str):
    """
    Returns dict with keys: evidences, verified, unverified.
    Each item includes: value (title, verbatim), doi?, url?, year?, evidence {page, quote}.
    """
    async with llm.uploaded_file(pdf_path) as f:
        prompt = (
            "You are an expert in computer vision and wildlife conservation research.I will provide you with the text of a literature review paper.Your task is to produce a concise, well-structured summary that focuses specifically on:"
            "Computer Vision Methods — Describe the algorithms, models, datasets, or imaging techniques discussed, including their purpose, strengths, and limitations."
            "Wildlife Conservation Context — Summarize how these methods are applied to wildlife monitoring, species identification, population estimation, behavior analysis, habitat mapping, or other conservation-related tasks."
            "Integration and Trends — Highlight emerging trends, innovative applications, and key research challenges at the intersection of computer vision and wildlife conservation."
            "Keep the summary factual, technically accurate, and no longer than 500 words.Use clear, academic language without unnecessary generalizations.Where possible, group related works and note significant gaps or opportunities for future research."
        )
        text = await llm.generate(contents=[f, prompt])
    return text


async def extract_reviewed_papers(llm, pdf_path: str):
    """
    Returns dict with keys: evidences, verified, unverified.
    Each item includes: value (title, verbatim), doi?, url?, year?, evidence {page, quote}.
    """
    async with llm.uploaded_file(pdf_path) as f:
        prompt = (
            "List all papers INCLUDED by this review (final set after screening) as part of THEIR methodology. Don't include related work like other reviews referenced!"
            "For each, provide title (verbatim), DOI if stated, URL if stated, and publication year if stated.\n\n"
            f"{REVIEW_ONLY_GUARD}\n\n"
            "Return JSON exactly as: "
            "{\"items\":[{\"value\":\"<title>\",\"doi\":\"<doi|omit>\",\"url\":\"<url|omit>\","
            "\"year\":<int|omit>,\"evidence\":{\"page\":<int|null>,\"quote\":\"<≤25 words>\"}}]}"
        )
        text = await llm.generate(contents=[f, prompt], response_model=ReviewedPaperEvidenceList)
    out = ReviewedPaperEvidenceList.model_validate_json(text)
    items = [i.model_dump() for i in out.items]
    verified, unverified = verify_items_against_pdf(Path(pdf_path), items)
    return {"evidences": items, "verified": verified, "unverified": unverified}


async def get_review_datasets(llm, pdf_path: str, dataset_prompt: str):
    """
    Datasets overview across INCLUDED STUDIES only.
    """
    from review.schemas import DatasetEvidenceList
    async with llm.uploaded_file(pdf_path) as f:
        text = await llm.generate(contents=[f, dataset_prompt], response_model=DatasetEvidenceList)
    out = DatasetEvidenceList.model_validate_json(text)
    items = [i.model_dump() for i in out.items]
    verified, unverified = verify_items_against_pdf(Path(pdf_path), items)
    return {"evidences": items, "verified": verified, "unverified": unverified}
