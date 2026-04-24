from review.schemas import TopicSpec

# general things

ARRAY_WITH_EVIDENCE_GUIDANCE = (
    "Return application/json exactly as: "
    "{\"items\":[{\"value\":\"<verbatim>\",\"evidence\":{\"page\":<int|null>,\"quote\":\"<verbatim ≤25 words>\"}}]}. "
    "If nothing is found, return {\"items\":[]} strictly. "
    "Copy phrases verbatim. Keep quotes short (≤ 25 words)."
)

HABITAT_EVIDENCE_PROMPT = (
    "Provide concise, verbatim evidence for the following IUCN habitat labels that are claimed to apply "
    "in THIS paper (not related work). Focus ONLY on the '{human_label}' group.\n\n"
    "Allowed values only (pick from this list exactly; do not invent new labels): {allowed_labels}\n\n"
    "For each label actually present in the document, return an item with:\n"
    "- value: the label string copied exactly from the allowed list (no rewording)\n"
    "- evidence: { page: <1-based page if visible or null>, quote: a short (≤ 25 words) verbatim quote }\n\n"
    "If you cannot find a direct textual support for a label, do not include it.\n"
    "Return application/json exactly as: "
    "{\"items\":[{\"value\":\"<label>\",\"evidence\":{\"page\":<int|null>,\"quote\":\"<≤25 words verbatim>\"}}]}"
)

REVIEW_ONLY_GUARD = (
    "IMPORTANT: Only include items that the article explicitly lists as INCLUDED STUDIES "
    "(papers actually reviewed). Exclude background/related work and any citations not part of the inclusion set."
)


# computer vision in wildlife conservation topics
cv_in_wc_topic_species_text = TopicSpec(key="Species (Text)",
                                        prompt="Extract animal species covered in THIS paper's methodology (not related work) (prefer taxonomic names). Return one item per species.")
cv_in_wc_topic_species_images = TopicSpec(key="Species (Images)",
                                          prompt="From figures/diagrams only, extract animal species depicted in THIS paper (not related work) (prefer taxonomic names).",
                                          require_images_only=True)
cv_in_wc_topic_country = TopicSpec(key="Country",
                                   prompt="Extract all countries in which THIS paper's methodology (not related work) has been used. If only continents are given, include them suffixed with '(C)'.")
cv_in_wc_topic_imaging_method = TopicSpec(key="Imaging Method",
                                          prompt="Extract imaging methods that have been used in THIS paper's  methodology (not related work) (e.g., AUV, ROV, animal-mounted camera, UAV, camera trap, satellite, digital imaging, photography, vid).")
cv_in_wc_topic_light_spectra_text = TopicSpec(key="Light Spectra (Text)",
                                              prompt="Extract used light spectra mentioned in THIS paper's methodology (not related work) (e.g. Visible, NIR, SWIR, UV, X-rays).")
cv_in_wc_topic_light_spectra_images = TopicSpec(key="Light Spectra (Images)",
                                                prompt="From sample images, infer light spectra used in THIS paper's methodology (not related work) (e.g. Visible, NIR, SWIR, UV, X-rays).",
                                                require_images_only=True)
cv_in_wc_topic_cv_tasks = TopicSpec(key="CV Tasks",
                                    prompt="Which computer-vision TASKS are analyzed in THIS paper's methodology (not related work)?",
                                    allowed_vocab=["Classification", "Segmentation", "Counting", "Reconstruction",
                                                   "Pose Estimation", "Synthesis", "Tracking", "Re-Identification",
                                                   "Activity Recognition", "Behavior Analysis",
                                                   "Interaction Monitoring", "Localization"])
cv_in_wc_topic_cv_algorithms = TopicSpec(key="CV Algorithms",
                                         prompt="Extract computer-vision models/algorithms explicitly analyzed in THIS paper's methodology (not related work) (e.g., ResNet, U-Net, YOLO, RCNN, ViT, watershed, HOG, DeepSORT, SfM, SLAM, GANs, diffusion, optical flow, thresholding). "                              "Do NOT include libraries or frameworks.")

cv_in_wc_HABITAT_PROMPT = (
            "Extract all habitats analyzed in this paper's methodology (not related work); classify according to the IUCN Habitats "
            "Classification Scheme.\n\n"
            "⚠️ Focus ONLY on the '{human_label}' group.\n"
            "Return a JSON object that EXACTLY matches the provided response model: "
            "{model_cls.__name__}. Do not include any extra keys.\n"
            "If none apply, return the schema with all fields set to false."
        )

cv_in_wc_DATASET_PROMPT = (
            "Extract datasets analyzed directly in this paper. "
            "If a dataset is public, include its name and (paper-stated) URL. "
            "If private or unspecified, set name='private' and omit URL.\n\n"
            f"{ARRAY_WITH_EVIDENCE_GUIDANCE}\n\n"
            "For each item, set:\n"
            "- value: dataset name (or 'private')\n"
            "- url: dataset URL if explicitly present in the paper text; otherwise omit\n"
            "- quote: short verbatim snippet proving the dataset mention\n"
            "- page: 1-based page number for that quote\n"
        )


# review paper topics
review_topic_species = TopicSpec(key="species",
                                 prompt="List wildlife species the REVIEW reports were analyzed by the INCLUDED STUDIES (not related work). Prefer scientific names; if only common names appear, use those.")
review_topic_imaging_method = TopicSpec(key="imaging_method",
                                        prompt="List imaging methods USED by the INCLUDED STUDIES (e.g., camera trap, UAV/drone, video camera, satellite, thermal camera). Exclude background/related work.")
review_topic_light_spectra = TopicSpec(key="light_spectra",
                                       prompt="List light spectra/modalities USED by the INCLUDED STUDIES (e.g., RGB/visible, infrared/NIR, thermal, multispectral, hyperspectral).")
review_topic_comptuer_vision_task = TopicSpec(key="computer_vision_task", prompt=(
    "List CV tasks reported for the INCLUDED STUDIES (e.g., detection, classification, segmentation, tracking, counting, re-identification, pose estimation). Map synonyms to these task names."),
                                              allowed_vocab=["Classification", "Detection", "Segmentation",
                                                             "Localization", "Tracking", "Counting",
                                                             "Re-identification", "Pose Estimation"])
review_topic_computer_vision_algorithm = TopicSpec(key="computer_vision_algorithm",
                                                   prompt="List CV or image-processing algorithms/architectures reported for the INCLUDED STUDIES (e.g., YOLO, Faster R-CNN, Mask R-CNN, SSD, ResNet, EfficientNet, U-Net, thresholding, optical flow, SVM).")

review_HABITAT_PROMPT = (
    "You will return a JSON object for the {human_label} group of the IUCN Habitats Classification. "
    "Mark a label True only if the review states that AT LEAST ONE INCLUDED STUDY analyzed that habitat. "
    "Exclude mentions in background/related work or future work. "
    "If unsure, keep False. Use only evidence from this review PDF."
)
review_DATASET_PROMPT = (
    "Extract datasets that the review reports were USED by the INCLUDED STUDIES. "
    "If a dataset is public, include its name and the URL only if the URL is explicitly written in the review. "
    "If the review states a dataset is private/author-collected, set value='private' and omit URL.\n\n"
    f"{REVIEW_ONLY_GUARD}\n\n"
    "Return JSON as DatasetEvidenceList with per-item evidence (page, short quote)."
)