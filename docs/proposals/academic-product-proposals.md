# Academic Product Proposals: UTME Lab Expansion

This proposal outlines six academic data products designed to expand UTME Lab beyond objective questions and set texts.

---

## 1. Course & Institution Subject Matcher (JAMB Brochure & IBASS Intelligence)

### Problem
A large percentage of university candidates in Nigeria forfeit admission each year before taking their exam because they select invalid UTME subject combinations or miss specific O-Level credit prerequisites for their target faculty. JAMB publishes these rules inside massive, fragmented PDF brochures that are difficult for students to search.

### Domain Schema & Entities
* **`Institution`**:
  * `id`: Slug (`unilag`, `ui`, `oau`, `abu`, `covenant`).
  * `name`: Official title (e.g. University of Lagos).
  * `ownership`: `federal`, `state`, or `private`.
  * `category`: `university`, `polytechnic`, or `college_of_education`.
  * `state`: Nigerian state location.
* **`Course`**:
  * `id`: Slug (`medicine-and-surgery`, `computer-science`, `law`, `accounting`).
  * `name`: Course title.
  * `faculty`: Faculty group (`medical_sciences`, `engineering`, `law`, `social_sciences`, `arts`, `sciences`).
  * `degree_awarded`: `MBBS`, `BSc`, `BEng`, `LLB`.
* **`AdmissionRequirement`**:
  * `institution_id`: Reference to institution.
  * `course_id`: Reference to course.
  * `utme_subjects`: Four required subjects (e.g. English, Biology, Chemistry, Physics).
  * `olevel_subjects`: Required O-Level credits (e.g. 5 credits including English, Mathematics, Biology, Chemistry, Physics in no more than 2 sittings).
  * `direct_entry_requirements`: A-Level, JUPEB, IJMB, or ND requirements for year-two entry.
  * `special_waivers`: Institution-specific exemptions or substitutions recorded by JAMB.

### Proposed API Surface
* `GET /api/v1/admissions/institutions`: Filter by category, ownership, and state.
* `GET /api/v1/admissions/courses`: Filter by faculty and institution offerings.
* `GET /api/v1/admissions/requirements/{institution}/{course}`: Retrieve full UTME, O-Level, and waiver data.
* `POST /api/v1/admissions/check-eligibility`: Takes candidate UTME subjects and O-Level grades, returning all qualified courses across institutions.

---

## 2. Syllabus Topic Study Notes & Formula Sheets

### Problem
Students currently practice questions on UTME Lab but must switch to third-party textbooks or disorganized websites to study the underlying theory. Providing concise, authoritative study notes and formula cheat-sheets mapped directly to syllabus topic slugs bridges the gap between learning and testing.

### Domain Schema & Entities
* **`TopicNote`**:
  * `exam`: `JAMB`, `WAEC`, or `NECO`.
  * `subject`: Subject slug (`physics`, `chemistry`, `biology`).
  * `topic_slug`: Linked to the existing catalog topic.
  * `summary`: Core revision brief written in structured rich text.
  * `key_concepts`: Array of numbered pedagogical takeaways.
  * `common_misconceptions`: Examiner-reported errors candidates frequently make.
* **`FormulaSheet`**:
  * `id`: Formula identifier.
  * `subject`: Subject slug (`mathematics`, `physics`, `chemistry`, `further-mathematics`).
  * `topic_slug`: Linked topic.
  * `name`: Standard theorem or law name (e.g. Hooke's Law, Lens Equation, Ideal Gas Law).
  * `latex`: Standard LaTeX expression (e.g. `F = k \Delta x`).
  * `variables`: Mapping of variable symbols to descriptions and standard SI units.
  * `conditions`: Constraints where the law holds or fails.

### Proposed API Surface
* `GET /api/v1/subjects/{exam}/{subject}/topics/{topic}/notes`: Fetch structured revision notes.
* `GET /api/v1/subjects/{exam}/{subject}/formulas`: Fetch all formula cards for a subject or topic.

---

## 3. WAEC & NECO Theory Questions with Step-by-Step Marking Schemes (Paper 2)

### Problem
WAEC and NECO are not purely objective tests. Paper 2 determines up to 60 percent of a candidate's final grade and requires structured essays, derivations, and problem-solving steps. Candidates struggle because they do not know how examiners award marks across intermediate lines of work.

### Domain Schema & Entities
* **`TheoryQuestion`**:
  * `id`: Unique identifier (`wq_2024_phys_p2_q3`).
  * `exam`: `WAEC` or `NECO`.
  * `subject`: Subject slug.
  * `year`: Examination year.
  * `section`: Section name (e.g. Section A: Short Answer, Section B: Long Theory).
  * `question_number`: Stated paper numbering (e.g. `3(a)`, `3(b)`).
  * `stem`: Rich text describing the problem, stimulus, or prompt.
  * `total_marks`: Total points allocated to the item.
* **`MarkingRubric`**:
  * `question_id`: Linked theory question.
  * `steps`: Ordered list of expected solution steps.
  * Each step carries:
    * `step_number`: Sequence index.
    * `content`: Mathematical working or descriptive sentence.
    * `mark_type`:
      * `M` (Method mark): Awarded for applying the correct formula or process.
      * `A` (Accuracy mark): Awarded for getting the correct numerical value following a valid method.
      * `B` (Independent mark): Awarded for independent facts, statements, or diagrams.
    * `mark_value`: Points for this step (e.g. `M1`, `A1`, `B2`).
  * `penalties`: Explicit deduction rules (e.g. minus 1 mark for missing SI unit, minus 1 mark for premature rounding).

### Proposed API Surface
* `GET /api/v1/theory/{exam}/{subject}`: Paged list of theory questions filtered by year, section, or topic.
* `GET /api/v1/theory/{id}`: Full question details.
* `GET /api/v1/theory/{id}/rubric`: Detailed examiner marking breakdown with step allocations.

---

## 4. Science Practical Lab Guides & Specimen Identification (Paper 3)

### Problem
Science candidates in West Africa face Paper 3 practical exams. Candidates from schools without well-funded laboratories often fail because they have never seen the actual specimens or conducted qualitative chemical analysis.

### Domain Schema & Entities
* **`PracticalSpecimen`** (Biology & Agricultural Science):
  * `exam`: `WAEC` or `NECO`.
  * `subject`: `biology` or `agricultural-science`.
  * `specimen_label`: Official exam label (e.g. Specimen A, Specimen B).
  * `common_name`: Everyday name (e.g. Toad, Earthworm, Hibiscus flower).
  * `scientific_name`: Binomial nomenclature in italics.
  * `classification`: Phylum, class, and family.
  * `observable_features`: External structural points examiners ask for.
  * `economic_importance`: Agricultural or medical benefits and hazards.
* **`QualitativeAnalysisCard`** (Chemistry Practical):
  * `reagent`: Test reagent (e.g. Sodium hydroxide solution, Barium chloride, Dilute hydrochloric acid).
  * `test`: Physical laboratory action performed.
  * `observation`: Visual result (e.g. White gelatinous precipitate soluble in excess).
  * `inference`: Chemical conclusion (e.g. `Al3+`, `Pb2+`, or `Zn2+` present).

### Proposed API Surface
* `GET /api/v1/practicals/{exam}/{subject}/specimens`: List specimens by year or category.
* `GET /api/v1/practicals/chemistry/qualitative`: Search qualitative test matrices by reagent, observation, or ion.

---

## 5. Micro-Learning Spaced-Repetition Flashcards

### Problem
CBT questions measure application, but rapid recall requires memorizing hundreds of vocabulary words, idioms, literary figures of speech, historical treaties, and mathematical constants.

### Domain Schema & Entities
* **`Flashcard`**:
  * `id`: Unique identifier.
  * `exam`: `JAMB`, `WAEC`, or `NECO`.
  * `subject`: Subject slug.
  * `topic_slug`: Linked syllabus topic.
  * `card_type`: `vocabulary`, `antonym`, `synonym`, `formula`, `definition`, or `literary_device`.
  * `front`: Front prompt (e.g. *"What is a zeugma?"* or *"Define specific latent heat of vaporization"*).
  * `back`: Back answer with definition and a contextual example.
  * `difficulty`: Rated 1 to 5.

### Proposed API Surface
* `GET /api/v1/flashcards/sample`: Retrieve random or seeded decks filtered by subject and topic for daily practice streaks.

---

## 6. University Historical Cut-Off Benchmarks

### Problem
Students finishing mock exams do not understand what their numerical score means in practice. Knowing whether a score of 275 is competitive for Mechanical Engineering at Obafemi Awolowo University or Ahmadu Bello University helps students adjust their study targets.

### Domain Schema & Entities
* **`CutOffBenchmark`**:
  * `institution_id`: Linked institution.
  * `course_id`: Linked course.
  * `year`: Academic session (e.g. `2024`, `2025`).
  * `merit_score`: Aggregate or UTME cut-off score.
  * `catchment_score`: Concessionary score for local catchment candidates.
  * `notes`: Additional screening criteria (e.g. Post-UTME weighting formula).

### Proposed API Surface
* `GET /api/v1/admissions/cutoffs`: Search historical cut-offs by course, institution, and minimum score.
