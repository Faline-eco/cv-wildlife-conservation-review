# Hallucination check, independent AI rating

You check values that an extraction model coded for scientific papers on computer vision for wild animal monitoring.
Items: `items.jsonl` (1519 items, 250 papers), one JSON object per line with
`id`, `doi`, `title`, `field`, `value` (the coded value), `extracted` (the raw extracted item(s) behind the value,
each with the extractor's quote and page), `pdf` (local PDF) and `text` (the paper's text as JSON, `pages[].text`,
one-based page numbers).

Read each paper in full (text file, or the PDF where the text is garbled) and rate every item of that paper.
Do not use any other verdicts; rate independently.

Question for every item: does the paper support that THE STUDY ITSELF has this value for the field, as the coding protocol defines the field? Use the whole paper (methods, data, results), not only the quote; the quote and page only show where the extractor found it.
- supported: the paper states or clearly shows it.
- partly: close but not exact (too broad or too narrow, applies to only part of the study, or a role that is clearly wrong).
- unsupported: the paper does not support it, or it belongs only to cited or related work (a hallucination).
- unclear: cannot be decided from the paper.
Fields:
- platform: the imaging platform that recorded the study's own analysed images (mapped to the manual vocabulary, e.g. 'Stationary Camera')
- habitat: the habitat of the analysed images (manual vocabulary, e.g. 'Marine')
- spectrum: a light spectrum of the analysed images (RGB, thermal infrared, ...)
- country: a country where the analysed images were recorded
- task: a primary computer-vision task of the study (manual vocabulary)
- algorithm: an algorithm (family) the study actually uses in its experiments; new, existing, pre-trained or a processing step all count; the role counts against it only if clearly wrong
- taxon_species: a target species whose images are analysed (GBIF backbone name)
- taxon_genus: the genus of a target taxon whose images are analysed
- taxon_class: the class of a target taxon whose images are analysed
- own_data: 'yes' = the authors collected (part of) the analysed images themselves
- public_dataset: 'yes' = the study uses a public dataset (wildlife dataset or generic benchmark)

Output: one CSV `ai_<tool>.csv` in this folder with the header
`id,verdict,reason,evidence_page,evidence_excerpt`
- verdict: one of supported, partly, unsupported, unclear
- reason: at most 25 words
- evidence_page / evidence_excerpt: the page and a short verbatim excerpt (at most 30 words) of the passage that
  decides the verdict (for unsupported: the passage closest to it, or empty)
One row per item, all 1519 items.

## Coding protocol given to the extractor

You code one research paper for the systematic mapping study "Computer Vision in Wildlife Conservation". You receive the paper text with page markers `<<page N>>`. The reference list has been removed. You use only this text, never outside knowledge about the paper, its datasets or its authors. If the paper does not state something, the value is "Not reported". Never guess a likely value.

# Step 1: eligibility
The review covers primary studies that develop, apply or evaluate computer vision on images or video of **wild, free-ranging, non-domestic animals** or their direct signs (tracks, nests, burrows).
- `include` is true only if all hold: computer vision method on image/video data; animals are the subject; at least part of the data shows wild or free-ranging animals; primary research.
- Otherwise `include` is false with exactly one criterion: E-PLANT (plants, habitat or land cover only), E-AGRI (livestock, poultry, pets, aquaculture, crop pests in production, beekeeping), E-LAB (laboratory animals or set-ups, microscopy, biomedical), E-CAPTIVE (zoo, aquarium or enclosure animals only; museum specimens), E-HUMAN (people, poachers, vehicles), E-NOCV (no image analysis), E-AUDIO (sound or sonar only), E-REVIEW (review, survey, perspective), E-GENERIC (generic vision paper; animals appear only as classes of a general benchmark and wildlife is not the stated subject or application).
- `subject_type` describes the animals in the data the paper itself analyses. Use "mixed" when wild animals appear together with captive or domestic ones.
- Code all remaining steps in the same way for excluded papers: a laboratory, zoo or farm study still has a setting, species, datasets, tasks and algorithms. Use empty lists only where the paper has nothing to code (for example a review).

# Step 2: study settings
A study setting is one combination of imaging platform, place and habitat from which analysed images come. A paper that uses camera traps in a Kenyan savanna and drone footage from a Norwegian coast has two settings. A paper that only uses a public or web dataset has one setting with what the paper states about that dataset. Every paper that analyses images has at least one setting. Indoor laboratory, zoo and farm set-ups are settings with habitat "Artificial Terrestrial" (tanks and ponds: "Artificial Aquatic").
- `platform`: where the camera was carried or mounted. "Non-specialized Camera" only if the paper states a handheld, tripod, fixed or smartphone camera. "Web / citizen-science images" for images collected from the internet or from platforms such as iNaturalist, Flickr, eBird. If the paper does not say how images were taken: "Not reported".
- `spectra`: the kind of image signal, each with `source`: "text" if the paper states it in the body text or a table (colour, RGB, grayscale, infrared, thermal, ...); "caption" if only a figure caption states it; "implied" if the paper does not state it but names an ordinary colour camera or colour image source (smartphone, DSLR, GoPro, webcam, a named consumer camera model, colour video, web photographs), in which case the value is "RGB (visible)" and the quote is the sentence naming the camera or image source. Camera-trap night images are "Near Infrared (NIR)" only if the paper says infrared. Code what the sensor records, not preprocessing: colour images converted to grayscale for an algorithm are "RGB (visible)"; "Grayscale" only for monochrome sensors or monochrome source images. Empty list if none of this applies.
- `habitat`: IUCN habitat class of the place where the animals were recorded. "Artificial Terrestrial" covers cities, farmland, plantations, roads, buildings; "Artificial Aquatic" covers reservoirs, canals, ponds, fish passages. "Not reported" if the paper does not describe the place.
- `countries`: English short country names where the images were taken; ["Global / web"] for web-collected data without location; empty list if not stated. Oceans and seas without a country go to `location_detail`.
- `species` and `datasets`: names exactly as in the `species` and `datasets` lists below that belong to this setting.

# Step 3: species
List the animal taxa the paper works on, at the rank the paper uses (species, genus, family, or a group such as "birds").
- `role`: "target" = animals the study is about and whose images are analysed; "benchmark_class" = classes inside a generic benchmark (ImageNet, COCO, CIFAR) or a fine-grained benchmark used only to test a general method; "mentioned" = named in the text but not in the analysed data. Never list taxa that appear only in the introduction or related work.
- `scientific_name` only if the paper gives it; otherwise empty string.
- If one dataset contributes more than 25 taxa, do not list them one by one: give one entry at the lowest common group (for example "birds", rank "group") and put the number of classes in `n_taxa`. Otherwise `n_taxa` is 1.
- `domestic` is true for livestock, pets and farmed or laboratory animals.

# Step 4: datasets
One entry per dataset used for training or evaluation.
- `name`: the dataset's name as written; "Unnamed (collected by authors)" for data the authors collected without naming it.
- `role`: "collected_by_authors", "public_wildlife_dataset", "generic_benchmark" (ImageNet, COCO, CIFAR, Places, ...), "pretraining_only".
- `availability`: "public" only if the paper gives a link, repository or DOI for this dataset or the dataset is a named public dataset; "on_request"; "not_stated".
- `origin`: "field_deployment", "citizen_science", "web_scraped", "captive_or_lab", "synthetic", "mixed", "not_stated".

# Step 5: computer vision tasks
Tasks the paper performs on animal images, from the closed list. "Classification" = assigning a species or class label to an image or crop; "Detection" = locating animals with boxes or points; "Counting" = number of animals as an output; "Re-Identification" = recognising individual animals; "Activity Recognition" = behaviour or action; "Reconstruction" = 3D shape or scene; "Synthesis" = generating images. `role`: "primary" for the task the paper is about, "auxiliary" for a processing step that serves another task.

# Step 6: algorithms
Methods actually used in the experiments, by the name the paper uses (for example "YOLOv5", "ResNet-50", "background subtraction", "SVM"). `role`: "proposed" (the paper's own method or the model it builds on), "backbone", "baseline" (compared against). `type` from the closed list. At most 15 entries; prefer proposed methods and backbones over baselines.

# Step 7: flags
- `cost_reported`: the paper gives a monetary cost of equipment, deployment or annotation.
- `ethics_statement`: the paper has an ethics, permit or animal-welfare statement.
- `explainability`: the paper applies an explainability method (Grad-CAM, saliency maps, SHAP, attention visualisation) to its model.

# Evidence
Every item carries `quote` and `page`. The quote is copied character by character from the text, 5 to 30 words, from one page, and it must state the coded fact. Take quotes from the methods, data, experiments or results part, not from the introduction or related work. If the coded value is "Not reported" or a flag is false, the quote is an empty string and the page is 0.

