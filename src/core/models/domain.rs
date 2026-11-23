//! The bank as stored.
//!
//! One Rust type per production shape: this is the Rust half of the
//! contract whose SQL half is `store::schema::READ_SHAPES`. A type here
//! mirrors a row (or a JSON column within one) rather than an answer, so
//! the store builds it and the wire layer renders from it. If a column
//! moves, the type moves with it, in the same change.

/// Plain text plus offset marks. `text` stays searchable as characters;
/// structure rides in `inline` as Unicode-scalar offsets, never bytes.
#[derive(
    Clone, Debug, Default, PartialEq, serde::Serialize, serde::Deserialize, utoipa::ToSchema,
)]
pub struct RichText {
    pub text: String,
    pub inline: Vec<Inline>,
}

/// One offset mark. Serialised flat with an adjacent `kind` tag, e.g.
/// `{"start":24,"len":6,"kind":"underline"}`.
#[derive(Clone, Debug, PartialEq, serde::Serialize, serde::Deserialize, utoipa::ToSchema)]
pub struct Inline {
    /// Offset in Unicode scalar values from the start of `text`.
    pub start: u32,
    /// Length in Unicode scalar values. Zero for an image anchor, which
    /// marks an attachment point rather than a span.
    pub len: u32,
    #[serde(flatten)]
    pub kind: InlineKind,
}

#[derive(Clone, Debug, PartialEq, serde::Serialize, serde::Deserialize, utoipa::ToSchema)]
#[serde(tag = "kind", rename_all = "lowercase")]
pub enum InlineKind {
    Bold,
    Italic,
    Underline,
    Strike,
    Subscript,
    Superscript,
    Image {
        url: String,
        position: ImagePosition,
        #[serde(default, skip_serializing_if = "Option::is_none")]
        alt: Option<String>,
    },
}

/// Where the figure renders relative to the stem. Data, never inferred.
#[derive(Clone, Copy, Debug, PartialEq, serde::Serialize, serde::Deserialize, utoipa::ToSchema)]
#[serde(rename_all = "lowercase")]
pub enum ImagePosition {
    Above,
    Below,
}

#[derive(Clone, Debug, PartialEq, serde::Serialize, serde::Deserialize, utoipa::ToSchema)]
pub struct Choice {
    pub id: String,
    pub text: RichText,
}

/// Why the answer is what it is: teaser, working, and the distractor
/// that catches people.
#[derive(Clone, Debug, PartialEq, serde::Serialize, serde::Deserialize, utoipa::ToSchema)]
pub struct Explanation {
    pub key_point: RichText,
    pub body: RichText,
    #[serde(default)]
    pub trap: Option<RichText>,
}

/// One question as stored. Answer always present here: withholding
/// happens in [`crate::core::catalog::render`], never in storage.
#[derive(Clone, Debug, PartialEq, serde::Serialize, serde::Deserialize, utoipa::ToSchema)]
pub struct Question {
    pub id: String,
    pub exam: String,
    pub subject: String,
    /// The cohort this question is prepared for. Required on every row:
    /// a consumer filtering by year cannot use a field empty for a
    /// fifth of the bank.
    pub year: u16,
    /// Where the row came from: `past_paper`, `authored`, and the like.
    pub source: String,
    pub text: RichText,
    pub options: Vec<Choice>,
    /// An **option id**, never a label or an index.
    pub answer: String,
    #[serde(default)]
    pub subtopic_id: Option<String>,
    #[serde(default)]
    pub section: Option<String>,
    #[serde(default)]
    pub passage_id: Option<String>,
    #[serde(default)]
    pub explanation: Option<Explanation>,
    pub marks: f32,
    pub difficulty: u8,
    /// Derived from the verification log (the latest human pass covering
    /// answer+explanation against the content we hold now), never authored.
    #[serde(skip, default)]
    pub verified: bool,
}

/// Measured expectations for one exam subject. Every measurement is
/// optional: a row states only what was measured, never a filled-in
/// zero. Empty result where no rows exist is honest absence, not 404.
#[derive(Clone, Debug, PartialEq, serde::Serialize, utoipa::ToSchema)]
pub struct Blueprint {
    pub exam: String,
    pub subject: String,
    pub level: String,
    pub topic: Option<String>,
    pub section: Option<String>,
    pub members: Vec<String>,
    pub paper_size: u32,
    pub pct: Option<f64>,
    pub pct_low: Option<f64>,
    pub pct_high: Option<f64>,
    pub expected: Option<f64>,
    pub expected_low: Option<f64>,
    pub expected_high: Option<f64>,
    pub source: Option<String>,
    pub sample: Option<String>,
    pub method: String,
    pub confidence: Option<String>,
    pub status: String,
    pub note: String,
}

/// A prescribed text. One row per (exam, cycle): the set text rotates,
/// so the prescription years are load-bearing, not decorative.
#[derive(Clone, Debug, PartialEq, serde::Serialize, serde::Deserialize, utoipa::ToSchema)]
pub struct Novel {
    pub id: String,
    pub title: String,
    pub author: String,
    /// Unknown for older set texts: absent, not zero.
    pub year_published: Option<u16>,
    pub exam: String,
    /// Every cycle this is (or was) the set text for.
    pub year_prescribed: Vec<u16>,
    /// Which paper sets it: reading text or prescribed literature.
    pub category: String,
    /// At most one per exam: the current set text.
    pub featured: bool,
    pub synopsis: String,
    pub setting_place: String,
    pub setting_period: String,
    pub cover_image: Option<String>,
}

/// One novel with everything: book, chapters, characters, themes, quiz.
/// Matches the established detail shape exactly, answers included:
/// callers already read quiz rows here, so withholding would silently
/// change the contract rather than improve it.
#[derive(Clone, Debug, PartialEq, serde::Serialize, serde::Deserialize, utoipa::ToSchema)]
pub struct NovelDoc {
    #[serde(flatten)]
    pub novel: Novel,
    pub chapters: Vec<NovelChapter>,
    pub characters: Vec<NovelCharacter>,
    pub themes: Vec<NovelTheme>,
    pub questions: Vec<NovelQuestion>,
}

#[derive(Clone, Debug, PartialEq, serde::Serialize, serde::Deserialize, utoipa::ToSchema)]
pub struct NovelChapter {
    pub number: u8,
    pub title: String,
    /// Null means not yet written: absence is the signal.
    pub summary: Option<String>,
    pub key_events: Vec<String>,
}

#[derive(Clone, Debug, PartialEq, serde::Serialize, serde::Deserialize, utoipa::ToSchema)]
pub struct NovelCharacter {
    pub name: String,
    pub role: String,
    pub character_type: String,
    pub description: String,
}

#[derive(Clone, Debug, PartialEq, serde::Serialize, serde::Deserialize, utoipa::ToSchema)]
pub struct NovelTheme {
    pub name: String,
    pub description: String,
    pub evidence: Vec<String>,
}

/// A quiz item about the book. Points at a chapter, not a subtopic;
/// the novel is the passage, so there is no passage id.
#[derive(Clone, Debug, PartialEq, serde::Serialize, serde::Deserialize, utoipa::ToSchema)]
pub struct NovelQuestion {
    pub id: String,
    pub chapter_number: Option<u8>,
    pub text: RichText,
    pub options: Vec<Choice>,
    /// An option id, same contract as `Question.answer`.
    pub answer: String,
    pub explanation: Option<Explanation>,
    /// Derived from the verification log, never authored. Skipped in
    /// serde: stored rows carry no `verified` key.
    #[serde(skip, default)]
    pub verified: bool,
}

/// A stimulus shared by many questions: one comprehension passage
/// serving five questions, one cloze serving ten. Questions carry only
/// the id; consumers resolve it here, never ignore it.
#[derive(Clone, Debug, PartialEq, serde::Serialize, utoipa::ToSchema)]
pub struct Passage {
    pub id: String,
    pub exam: String,
    pub subject: String,
    pub year: u16,
    pub kind: String,
    pub title: Option<String>,
    pub author: Option<String>,
    pub text: RichText,
}

/// One exam as stored. Facts live here, not scattered across call sites.
///
/// `status` is a passthrough string (`live` | `planned` | `retired`
/// today): a new board status must keep serving, never break
/// deserialization of every row. Nullable columns stay `Option` for the
/// same honesty: unstated is null, never invented.
#[derive(Clone, Debug, PartialEq, serde::Serialize, utoipa::ToSchema)]
pub struct Exam {
    /// Exam code, e.g. `JAMB`.
    pub code: String,
    pub name: String,
    /// Member countries running this exam. Empty where unstated.
    pub countries: Vec<String>,
    pub status: String,
    /// Whether a full paper can be assembled at all. Null where it
    /// cannot be stated.
    pub has_full_paper: Option<bool>,
    /// Subjects in a full paper (JAMB: 4). Null where unstated.
    pub subjects_required: Option<u32>,
    /// Minutes for a full sitting, verified only. Null where unverified.
    pub duration_minutes: Option<u32>,
    /// Board-stated rules a consumer must know. Empty where unstated.
    pub rules: Vec<String>,
}

/// One exam's offering of a subject. The same concept appears once per
/// exam carrying that board's own name, not one row with an alias.
#[derive(Clone, Debug, PartialEq, serde::Serialize, utoipa::ToSchema)]
pub struct Subject {
    pub slug: String,
    pub exam: String,
    pub name: String,
    pub is_compulsory: bool,
    /// MCQs the objective paper holds. Null where unverified: absence
    /// is data, never a zero masquerading as a fact.
    pub objective_paper_questions: Option<u32>,
    /// Countries this exam offers the subject in. Empty means every country
    /// the exam runs in.
    pub countries: Vec<String>,
    /// If this subject uses another exam's syllabus, the exam code (e.g., "WAEC").
    /// Null means this exam's own syllabus.
    pub syllabus_exam: Option<String>,
    /// If this subject uses another exam's syllabus, the subject slug (e.g., "biology").
    /// Null means this exam's own syllabus.
    pub syllabus_subject: Option<String>,
}

/// A topic within one exam's syllabus.
#[derive(Clone, Debug, PartialEq, serde::Serialize, utoipa::ToSchema)]
pub struct Topic {
    pub slug: String,
    pub subject: String,
    pub exam: String,
    pub name: String,
    pub order: u32,
    /// Marks the board gives this topic. Zero means "not published",
    /// never "worth nothing". A fabricated weight would reach
    /// consumers as a fact.
    pub weight: u32,
    /// Examinable statements attached at topic level. Empty where the
    /// board states none, never invented.
    pub objectives: Vec<String>,
    #[serde(default)]
    pub lesson_refs: Vec<ContentReference>,
}

/// One board rule about which subjects a paper needs. An empty `subjects`
/// means "every exam subject not named by another group"; `min_select` is
/// how many of that pool must be ready before the paper is real.
#[derive(Clone, Debug, PartialEq, serde::Serialize, utoipa::ToSchema)]
pub struct Requirement {
    pub group: String,
    pub min_select: u32,
    pub subjects: Vec<String>,
}

/// One subject's slot in an exam scheme. `questions` is the stated paper
/// size (null where unverified), and `marks_per_question` is stated only
/// where the bank supports it: both are absences, never zeros.
#[derive(Clone, Debug, PartialEq, serde::Serialize, utoipa::ToSchema)]
pub struct SubjectSlot {
    pub slug: String,
    pub name: String,
    pub compulsory: bool,
    pub questions: Option<u32>,
    pub marks_per_question: Option<f32>,
}

/// How an exam's paper is shaped, restated from the bank (D19). This is a
/// constant over our content, so it moves only when the bank does.
#[derive(Clone, Debug, PartialEq, serde::Serialize, utoipa::ToSchema)]
pub struct Scheme {
    pub exam: String,
    /// Minutes for a full sitting, verified only. Null where unverified.
    pub duration_minutes: Option<u32>,
    pub subjects: Vec<SubjectSlot>,
    /// Board-stated rules a consumer must know. Empty where unstated.
    pub rules: Vec<String>,
    /// Questions a full paper holds, summed from subjects we can fill.
    /// A lower bound for any exam whose bank is incomplete.
    pub questions_available: u32,
    /// Which subjects can fill a slot today, by slug.
    pub subjects_ready: Vec<String>,
    /// Country scope this scheme was computed for. Absent means the full
    /// honest view, and completeness is only ever claimed for a scope.
    pub country: Option<String>,
    /// The paper-assembly rules evaluated for this scope, copied from the
    /// exam's requirement rows so a consumer sees what `complete` meant.
    pub requirements: Vec<Requirement>,
}

/// The scheme plus whether the bank can fill it. Readiness sits beside the
/// scheme rather than inside it, so the validated shape does not move as
/// our content grows.
#[derive(Clone, Debug, PartialEq, serde::Serialize, utoipa::ToSchema)]
pub struct PaperReadiness {
    pub exam: String,
    pub scheme: Scheme,
    /// True when every requirement group for this scope holds enough
    /// verified questions to fill its `min_select` slots.
    pub complete: bool,
}

/// A reusable, exam-neutral teaching unit served by the Content API.
///
/// Exam syllabus topics and exam questions may reference a lesson, but a
/// lesson never carries exam identity.
#[derive(Clone, Debug, PartialEq, serde::Serialize, serde::Deserialize, utoipa::ToSchema)]
pub struct Lesson {
    pub id: String,
    /// Consumer-visible lifecycle. Only `published` lessons are returned by
    /// normal catalog reads.
    #[serde(default = "default_lesson_status")]
    pub status: String,
    pub title: String,
    #[serde(default)]
    pub description: RichText,
    pub subject: String,
    #[serde(default)]
    pub level: String,
    #[serde(default)]
    pub estimated_minutes: u32,
    #[serde(default)]
    pub objectives: Vec<LearningObjective>,
    #[serde(default)]
    pub content: Vec<ContentBlock>,
    #[serde(default)]
    pub checks: Vec<StudyCheck>,
    #[serde(default)]
    pub misconceptions: Vec<SectionMisconception>,
    #[serde(default)]
    pub summary: Vec<RichText>,
    #[serde(default)]
    pub example_question_refs: Vec<ContentReference>,
    #[serde(default)]
    pub provenance: Provenance,
    #[serde(default)]
    pub content_hash: String,
}

#[derive(Clone, Debug, PartialEq, serde::Serialize, serde::Deserialize, utoipa::ToSchema)]
pub struct ContentReference {
    pub id: String,
    #[serde(default)]
    pub title: String,
}

fn default_lesson_status() -> String {
    "published".to_string()
}

#[derive(
    Clone, Debug, Default, PartialEq, serde::Serialize, serde::Deserialize, utoipa::ToSchema,
)]
pub struct Provenance {
    #[serde(default)]
    pub publisher: String,
    #[serde(default)]
    pub title: String,
    #[serde(default)]
    pub url: String,
    #[serde(default)]
    pub locator: String,
    #[serde(default)]
    pub licence: String,
}

#[derive(Clone, Debug, PartialEq, serde::Serialize, serde::Deserialize, utoipa::ToSchema)]
pub struct ExamPaper {
    pub question_id: String,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub year: Option<i64>,
    #[serde(default)]
    pub source: String,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub url: Option<String>,
}

#[derive(
    Clone, Debug, Default, PartialEq, serde::Serialize, serde::Deserialize, utoipa::ToSchema,
)]
pub struct PaperEvidence {
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub question_id: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub section_id: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub exam: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub year: Option<u16>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub source: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub url: Option<String>,
}

const fn default_heading_level() -> u8 {
    1
}

const fn default_step_number() -> u32 {
    1
}

/// Title for an example block, supporting either plain text or RichText.
#[derive(Clone, Debug, PartialEq, serde::Serialize, serde::Deserialize, utoipa::ToSchema)]
#[serde(untagged)]
pub enum ExampleTitle {
    Plain(String),
    Rich(RichText),
}

/// Single table cell supporting either plain string or RichText.
#[derive(Clone, Debug, PartialEq, serde::Serialize, serde::Deserialize, utoipa::ToSchema)]
#[serde(untagged)]
pub enum TableCell {
    Text(String),
    Rich(RichText),
}

/// A step in a worked example.
#[derive(Clone, Debug, PartialEq, serde::Serialize, serde::Deserialize, utoipa::ToSchema)]
pub struct WorkedStep {
    #[serde(default = "default_step_number")]
    pub step_number: u32,
    #[serde(default)]
    pub expression: String,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub description: Option<String>,
}

/// Discriminated content block in section teaching text.
#[derive(Clone, Debug, PartialEq, serde::Serialize, serde::Deserialize, utoipa::ToSchema)]
#[serde(tag = "type", rename_all = "snake_case")]
pub enum ContentBlock {
    /// The single concrete anchor that starts every lesson.
    Opening {
        id: String,
        anchor: OpeningAnchor,
        heading: String,
        text: RichText,
    },
    Paragraph {
        id: String,
        #[serde(alias = "content")]
        text: RichText,
    },
    Heading {
        id: String,
        #[serde(default = "default_heading_level")]
        level: u8,
        text: RichText,
    },
    Definition {
        id: String,
        term: RichText,
        definition: RichText,
    },
    Rule {
        id: String,
        statement: RichText,
        #[serde(default, skip_serializing_if = "Option::is_none")]
        conditions: Option<RichText>,
        #[serde(default, skip_serializing_if = "Option::is_none")]
        note: Option<RichText>,
    },
    Formula {
        id: String,
        expression: String,
        #[serde(default, skip_serializing_if = "Option::is_none")]
        caption: Option<RichText>,
        #[serde(default, skip_serializing_if = "Option::is_none")]
        conditions: Option<RichText>,
    },
    Example {
        id: String,
        #[serde(default, skip_serializing_if = "Option::is_none")]
        title: Option<ExampleTitle>,
        #[serde(alias = "statement", alias = "problem")]
        prompt: RichText,
        #[serde(default)]
        steps: Vec<WorkedStep>,
        #[serde(default, skip_serializing_if = "Option::is_none")]
        answer: Option<RichText>,
    },
    Figure {
        id: String,
        #[serde(alias = "url")]
        asset_url: String,
        #[serde(default, skip_serializing_if = "Option::is_none")]
        caption: Option<RichText>,
        #[serde(default, skip_serializing_if = "Option::is_none")]
        alt: Option<String>,
        #[serde(default, skip_serializing_if = "Option::is_none")]
        licence: Option<String>,
    },
    Table {
        id: String,
        #[serde(default, skip_serializing_if = "Option::is_none")]
        title: Option<RichText>,
        rows: Vec<Vec<TableCell>>,
        #[serde(default, skip_serializing_if = "Option::is_none")]
        alt: Option<String>,
    },
    List {
        id: String,
        #[serde(default)]
        ordered: bool,
        items: Vec<RichText>,
    },
    Callout {
        id: String,
        kind: String,
        #[serde(alias = "body")]
        text: RichText,
    },
    Summary {
        id: String,
        points: Vec<RichText>,
    },
    ExerciseRef {
        id: String,
        exercise_id: String,
        #[serde(default, skip_serializing_if = "Option::is_none")]
        prompt: Option<RichText>,
    },
    GlossaryEntry {
        id: String,
        term: RichText,
        definition: RichText,
    },
    Image {
        id: String,
        url: String,
        #[serde(default, skip_serializing_if = "Option::is_none")]
        caption: Option<RichText>,
        #[serde(default, skip_serializing_if = "Option::is_none")]
        alt: Option<String>,
        #[serde(default, skip_serializing_if = "Option::is_none")]
        position: Option<ImagePosition>,
    },
    Question {
        id: String,
        question: RichText,
        options: Vec<Choice>,
        answer: String,
    },
}

/// The kind of concrete anchor used to begin a lesson. The wording shown to
/// learners is carried by the opening's heading; this keeps the contract
/// useful across subjects without forcing every lesson to say "The situation".
#[derive(Clone, Debug, PartialEq, serde::Serialize, serde::Deserialize, utoipa::ToSchema)]
#[serde(rename_all = "snake_case")]
pub enum OpeningAnchor {
    Scenario,
    Sentence,
    Problem,
    Observation,
    Passage,
    Event,
    Case,
}

/// A worked example in a chapter section.
#[derive(Clone, Debug, PartialEq, serde::Serialize, serde::Deserialize, utoipa::ToSchema)]
pub struct SectionWorkedExample {
    pub id: String,
    pub statement: RichText,
    pub steps: Vec<WorkedStep>,
    pub answer: RichText,
    #[serde(default)]
    pub provenance: Provenance,
}

/// A misconception with its correction and provenance.
#[derive(Clone, Debug, PartialEq, serde::Serialize, serde::Deserialize, utoipa::ToSchema)]
pub struct SectionMisconception {
    pub id: String,
    pub claim: RichText,
    pub correction: RichText,
    #[serde(default)]
    pub provenance: Provenance,
}

/// One thing the reader will be able to do.
#[derive(Clone, Debug, PartialEq, serde::Serialize, serde::Deserialize, utoipa::ToSchema)]
pub struct LearningObjective {
    pub id: String,
    pub statement: String,
    #[serde(default)]
    pub bloom_level: String,
}

/// A short formative check authored for a teaching section, not drawn from
/// an exam-practice bank.
#[derive(Clone, Debug, PartialEq, serde::Serialize, serde::Deserialize, utoipa::ToSchema)]
#[serde(rename_all = "snake_case")]
pub enum StudyCheckKind {
    MultipleChoice,
}

#[derive(Clone, Debug, PartialEq, serde::Serialize, serde::Deserialize, utoipa::ToSchema)]
pub struct StudyCheckOption {
    pub id: String,
    pub content: RichText,
}

#[derive(Clone, Debug, PartialEq, serde::Serialize, serde::Deserialize, utoipa::ToSchema)]
pub struct StudyCheckAnswer {
    pub option_id: String,
}

#[derive(Clone, Debug, PartialEq, serde::Serialize, serde::Deserialize, utoipa::ToSchema)]
pub struct StudyCheck {
    /// Stable identity within the owning section.
    pub id: String,
    /// One-based authored order within the section.
    pub order: i64,
    /// Insert the check immediately after this teaching block when present.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub position_after_block_id: Option<String>,
    /// Learning objective this check supports when the relation is known.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub objective_id: Option<String>,
    pub kind: StudyCheckKind,
    pub prompt: RichText,
    pub options: Vec<StudyCheckOption>,
    /// Correct option; clients must withhold it until the learner responds.
    pub answer: StudyCheckAnswer,
    /// Source-authored feedback to show after an attempt or explicit reveal.
    pub feedback: RichText,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub hint: Option<RichText>,
    pub provenance: Provenance,
}

/// A WAEC or NECO Paper 2 theory question with step-by-step marking scheme.
#[derive(Clone, Debug, PartialEq, serde::Serialize, serde::Deserialize, utoipa::ToSchema)]
pub struct TheoryQuestion {
    pub id: String,
    pub exam: String,
    pub subject: String,
    pub year: u32,
    pub paper: u8,
    pub section: String,
    pub question_number: String,
    pub topic_slug: String,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub subtopic_slug: Option<String>,
    pub total_marks: u32,
    pub stem: RichText,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub diagram_url: Option<String>,
    #[serde(default)]
    pub sub_parts: Vec<TheorySubPart>,
    #[serde(default)]
    pub formulation_bridge: Vec<FormulationClause>,
    #[serde(default)]
    pub marking_methods: Vec<MarkingMethod>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub diagram_rubric: Option<DiagramRubric>,
    #[serde(default)]
    pub penalties: Vec<ExaminerPenalty>,
    pub examiner_report: TheoryExaminerReport,
}

#[derive(Clone, Debug, PartialEq, serde::Serialize, serde::Deserialize, utoipa::ToSchema)]
pub struct TheorySubPart {
    pub part_label: String,
    pub prompt: String,
    pub allocated_marks: u32,
}

#[derive(Clone, Debug, PartialEq, serde::Serialize, serde::Deserialize, utoipa::ToSchema)]
pub struct FormulationClause {
    pub clause: String,
    pub variable_mapping: String,
    pub derived_equation: String,
}

#[derive(Clone, Debug, PartialEq, serde::Serialize, serde::Deserialize, utoipa::ToSchema)]
pub struct MarkingMethod {
    pub method_id: String,
    pub method_name: String,
    pub is_primary: bool,
    pub steps: Vec<MarkingStep>,
}

#[derive(Clone, Debug, PartialEq, serde::Serialize, serde::Deserialize, utoipa::ToSchema)]
pub struct MarkingStep {
    pub step_id: String,
    pub part_label: String,
    pub description: String,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub expression: Option<String>,
    pub mark_type: String,
    pub mark_value: u32,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub notes: Option<String>,
}

#[derive(Clone, Debug, PartialEq, serde::Serialize, serde::Deserialize, utoipa::ToSchema)]
pub struct DiagramRubric {
    pub title_marks: u32,
    pub line_quality_marks: u32,
    pub proportion_marks: u32,
    pub label_marks: u32,
    #[serde(default)]
    pub guidelines: Vec<String>,
}

#[derive(Clone, Debug, PartialEq, serde::Serialize, serde::Deserialize, utoipa::ToSchema)]
pub struct ExaminerPenalty {
    pub penalty_type: String,
    pub deduction: u32,
    pub description: String,
}

#[derive(Clone, Debug, PartialEq, serde::Serialize, serde::Deserialize, utoipa::ToSchema)]
pub struct TheoryExaminerReport {
    pub general_performance: String,
    #[serde(default)]
    pub common_errors: Vec<String>,
    pub remedies: String,
}
