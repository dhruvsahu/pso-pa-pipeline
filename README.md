# Decision Log — Parameter Extraction Architecture

## Hybrid Extraction Architecture for Policy Parameters

Initial experimentation with direct global regex extraction for the `Age` parameter revealed a critical limitation in payer policy documents: a single policy may contain multiple brands and multiple conditional eligibility branches. 

For example:
- Enbrel → 4+ years
- Stelara → 6+ years
- Tremfya → 18+ years

A naive document-wide regex approach incorrectly returned the minimum age across all brands instead of resolving the age specific to the target brand. This exposed the need for entity-scoped reasoning rather than simple document-level extraction.

To address this, we adopted a hybrid extraction architecture:

### Step 1 — Candidate Statement Extraction
Instead of directly extracting a final answer, the system first identifies all candidate age-related statements using deterministic pattern matching (regex + keyword rules).

Examples of extracted candidate statements:
- "The individual is 18 years of age or older"
- "The individual is 4 years of age or older and the request is for Enbrel"
- "The individual is 6 years of age or older and the request is for Stelara"

This stage prioritizes high recall.

### Step 2 — Brand-Aware LLM Resolution
The extracted candidate statements, along with the target brand name, are passed to a local LLM (Qwen2.5 7B via Ollama). 

The LLM is instructed to:
- ignore unrelated brands
- resolve conditional branches
- select the correct brand-specific rule
- fallback to general/default rules if no brand-specific rule exists
- return only the normalized numeric age

This architecture combines:
- deterministic retrieval
- contextual reasoning
- controlled normalization

and is expected to generalize well across other complex parameters such as:
- Step Therapy
- Branded Step Counts
- Generic Step Counts
- Phototherapy Logic
- Reauthorization Rules

## Key Learning

Healthcare prior authorization policies are not simple extraction problems. They require conditional rule resolution based on:
- target brand
- indication
- universal criteria
- exception logic
- AND/OR branching

Therefore, parameter extraction must be:
1. parameter-specific
2. context-aware
3. entity-scoped
4. normalization-driven

rather than relying on generic document-wide prompting.

---

# Age Extraction Pipeline — Architecture Notes

## Problem Statement

The `Age` parameter in healthcare prior authorization policies is not a simple scalar extraction task. Policies frequently contain:

* multiple brands within a single document
* conditional eligibility rules
* shared and brand-specific criteria
* varying document structures
* absence-based rules (e.g., no age restriction)

A naive global regex extraction approach initially failed because it incorrectly extracted the minimum age across unrelated brands in the same policy document.

Example:

* Enbrel → 4 years
* Stelara → 6 years
* Tremfya → 18 years

A document-wide extraction incorrectly returned `4` for all brands.

---

# Key Architectural Learnings

## 1. Retrieval Quality Matters More Than Prompt Complexity

Initial failures were not caused by LLM reasoning limitations but by poor retrieval quality. Passing noisy or irrelevant policy sections caused hallucinations and incorrect age resolution.

This led to a major architectural shift:

### From:

* global document extraction
* broad regex scanning
* full-document prompting

### To:

* retrieval-first architecture
* target-brand-aware page filtering
* context-focused prompting

---

# Final Age Extraction Architecture

```text
PDF
 ↓
Page Extraction
 ↓
Target Brand Filtering
 ↓
Page Relevance Scoring
 ↓
Top Relevant Page Retrieval
 ↓
Context Construction
 ↓
LLM-Based Age Resolution
 ↓
Structured JSON Output
```

---

# Retrieval Strategy

## Hard Brand Filtering

Only pages explicitly containing the target brand are considered for retrieval. This significantly improved precision and reduced hallucinations caused by unrelated policy sections.

Example:

* Pages without `STELARA` are ignored when extracting age for Stelara.

---

## Relevance Scoring

Pages are scored using:

* target brand frequency
* age-related keywords
* authorization terminology
* explicit age patterns

Example scoring signals:

* `age restrictions`
* `years of age`
* `pediatric`
* `initial criteria`

This allows the system to prioritize policy sections most likely to contain relevant age criteria.

---

# LLM Reasoning Layer

The local LLM (`Qwen2.5:7B` via Ollama) is used only after retrieval refinement.

The model is responsible for:

* resolving conditional logic
* ignoring unrelated brands
* handling fallback/default rules
* detecting absence of age restrictions
* normalizing outputs

Example outputs:

* `>=18`
* `>=6`
* `No Age Restriction`

The LLM is intentionally constrained to:

* retrieved context only
* strict JSON output
* normalized formatting

---

# Important Failure Modes Identified

## 1. Cross-Brand Contamination

Policies often contain multiple brands and multiple age rules in the same document.

Solution:

* hard brand filtering
* context-limited prompting

---

## 2. Absence-Based Criteria

Some policies explicitly state:

* `Age Restrictions -`
* `No age restrictions`

These required special handling because absence itself represents valid information.

---

## 3. Long Policy Documents

Some payer PDFs exceed 150 pages.

Full-document prompting caused:

* noisy retrieval
* degraded reasoning
* hallucinations

This led to adoption of:

* page-level relevance retrieval
* context truncation
* retrieval-first architecture

---

# Engineering Decisions

## Why Local LLM?

The project uses a local LLM stack:

* Ollama
* Qwen2.5:7B

Advantages:

* fully offline
* no API limits
* faster iteration
* easier experimentation
* scalable batch processing

---

## Why Hybrid Extraction?

The final design intentionally combines:

* deterministic retrieval
* rule-based filtering
* LLM reasoning

instead of relying entirely on either:

* regex
* or pure prompting

This hybrid approach improved:

* explainability
* debugging
* consistency
* extraction accuracy

---

# Future Improvements

Planned improvements include:

* neighboring page expansion
* synonym/generic drug matching
* confidence calibration
* section-aware retrieval
* retrieval evaluation metrics
* reusable shared retrieval engine for all parameters


# Step Therapy Requirements Extraction — Architecture Notes

## Problem Statement

The parameter:

```text id="n4x8qp"
Step Therapy Requirements Documented in Policy
```

is significantly more complex than scalar parameters such as:

* Age
* TB Test Required
* Authorization Duration

This parameter contains:

* multi-condition therapy requirements
* biologic treatment rules
* contraindication/intolerance clauses
* phototherapy requirements
* systemic therapy requirements
* universal + brand-specific criteria
* narrative-heavy policy language

The extracted output also acts as a foundational evidence layer for downstream parameters such as:

* Number of Steps through Brands
* Number of Steps through Generic
* Step-through Phototherapy

Because of this dependency, the extraction strategy prioritizes:

# high recall and evidence preservation

instead of aggressive normalization.

---

# Core Architectural Decision

## Separation of Concerns

The pipeline intentionally separates:

### 1. Therapy Narrative Extraction

FROM

### 2. Therapy Step Counting / Logical Resolution

This is a critical design choice.

The current extractor is responsible only for:

* retrieving relevant therapy-related evidence
* preserving important policy wording
* extracting structured therapy requirements

The extractor intentionally does NOT:

* count therapy steps
* resolve OR/AND logic
* compute least restrictive paths
* classify branded vs generic steps

These downstream reasoning tasks are deferred to later specialized logic layers.

---

# Step Therapy Extraction Architecture

```text id="g7m2vk"
PDF
 ↓
Page Extraction
 ↓
Brand-Aware Retrieval
 ↓
Therapy-Focused Page Scoring
 ↓
Top Relevant Page Retrieval
 ↓
Context Construction
 ↓
LLM Narrative Extraction
 ↓
Structured JSON Output
```

---

# Page-Level Retrieval Strategy

## Why Page-Level Retrieval?

Many payer policies:

* exceed 150+ pages
* contain multiple brands
* contain multiple indications
* include unrelated therapy sections
* mix formulary and clinical content

Full-document prompting produced:

* hallucinations
* cross-brand contamination
* noisy extraction
* degraded reasoning quality

Page-level retrieval was introduced to:

* improve precision
* reduce irrelevant context
* scale to large PDFs
* preserve explainability

---

# Brand-Aware Filtering

The extractor uses:

# hard brand filtering

Meaning:
only pages explicitly containing the target brand are considered for retrieval.

Example:

```python id="r9x4tp"
if brand.lower() not in text_lower:
    continue
```

This prevents:

* therapy leakage from unrelated drugs
* incorrect biologic requirements
* false step-therapy associations

This was one of the largest improvements in extraction quality.

---

# Therapy-Focused Retrieval

Unlike the `AgeExtractor`,
this extractor prioritizes:

# recall over precision

Therapy-related policy language may appear:

* across multiple sections
* in narrative paragraphs
* within tables
* inside continuation pages

The retrieval engine therefore scores pages using therapy-related terminology such as:

* inadequate response
* intolerance
* contraindication
* phototherapy
* biologic
* methotrexate
* cyclosporine
* acitretin
* UVB / PUVA
* preferred/non-preferred agents

This broader retrieval strategy improves preservation of therapy evidence.

---

# Multi-Page Context Retrieval

The extractor retrieves:

```python id="v3m8qr"
top_k = 6
```

rather than the smaller context windows used for scalar extraction tasks.

Reason:
therapy requirements are often distributed across:

* adjacent pages
* continuation sections
* criteria tables
* appendices

The larger retrieval window reduces risk of missing clinically important requirements.

---

# LLM Role in the Pipeline

The local LLM (`Qwen2.5:7B` via Ollama) is used only after retrieval refinement.

The LLM is responsible for:

* extracting therapy-related narrative
* preserving clinically relevant wording
* consolidating fragmented therapy requirements
* returning structured JSON output

The model is intentionally NOT responsible for:

* numerical step counting
* OR/AND resolution
* graph reasoning
* least restrictive path determination

This separation significantly improves maintainability and debugging.

---

# Structured Output Format

The extractor returns structured JSON:

```json id="x5q2mt"
{
  "parameter": "Step Therapy Requirements Documented in Policy",
  "brand": "YESINTEK",
  "value": [
    "...therapy requirement..."
  ],
  "confidence": 0.91,
  "retrieved_pages": [12, 13, 14]
}
```

Benefits:

* traceability
* debugging visibility
* downstream reasoning support
* evaluation consistency

---

# Major Engineering Insight

The most important realization during development was:

```text id="m8v4xp"
retrieval quality matters more than prompt complexity
```

Early failures were primarily caused by:

* noisy retrieval
* unrelated therapy sections
* poor context selection
* cross-brand contamination

rather than limitations of the LLM itself.

This led to adoption of:

# retrieval-first extraction architecture

which significantly improved extraction quality and reduced hallucinations.

---

# Future Improvements

Planned enhancements include:

* neighboring page expansion
* therapy synonym dictionaries
* section-aware retrieval
* table-aware extraction
* phototherapy tagging
* branded vs generic therapy classification
* logical graph resolution for step counting
* confidence calibration
* retrieval evaluation metrics

## Step Therapy Extraction & Therapy Step Counting Approach

We designed the Step Therapy extraction pipeline using a hybrid retrieval + symbolic reasoning architecture instead of relying purely on LLM-generated outputs. Early experimentation showed that directly asking the LLM to count therapy steps led to inconsistent reasoning, hallucinated counts, and loss of important therapy mentions due to summarization. To improve reliability, we separated the workflow into independent stages: retrieval, raw evidence extraction, ontology normalization, and deterministic counting.

The pipeline first retrieves the most relevant pages from the PDF using a weighted scoring mechanism based on the target brand name and step-therapy-related keywords such as “inadequate response”, “contraindication”, “phototherapy”, and “trial and failure”. A hard brand filter is also applied to avoid retrieving unrelated policy sections. After retrieval, noisy sections such as “Related Policies” and “References” are removed to prevent false therapy detections.

Instead of using the LLM as the primary extraction engine, the system now extracts raw therapy evidence directly from the retrieved context. We preserve therapy-containing sentences and raw therapy mentions before any summarization occurs. Regex-based biomedical patterns are used to detect biologics, kinase inhibitors, phototherapy terms, and common systemic therapies. This approach preserves the original evidence and prevents downstream ontology failures caused by LLM paraphrasing.

To support therapy normalization and consistent counting across different policies, we built an ontology enrichment workflow. A separate script scans multiple PDFs and creates a therapy dictionary containing raw therapy mentions, source context, and occurrence metadata. Another normalization pipeline uses the LLM only for canonical entity resolution, where therapies such as “ustekinumab” and “Stelara” are mapped to a single normalized therapy identity. This prevents overcounting caused by generic-brand duplicates and allows the reasoning engine to work on canonical therapy entities instead of raw strings.

The therapy counting engine is fully deterministic. After ontology mapping, therapies are classified into:

* Brand therapies
* Generic/systemic therapies
* Phototherapy

Logical reasoning is then applied to determine the final counts. The system currently supports AND/OR pathway interpretation with least-restrictive-path logic for OR conditions. Brand steps, generic steps, and phototherapy steps are all computed using the same reusable reasoning engine, making the architecture scalable and extensible for future parameters.

This architecture evolved iteratively through debugging multiple real-world payer policies and gradually moved from prompt-heavy extraction toward a structured document intelligence system with ontology-aware symbolic reasoning.
