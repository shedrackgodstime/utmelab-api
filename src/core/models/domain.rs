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

/// A textbook. The textbook owns the teaching, so it never names an exam.
#[derive(Clone, Debug, PartialEq, serde::Serialize, serde::Deserialize, utoipa::ToSchema)]
pub struct Book {
    pub id: String,
    pub title: String,
    pub subject_area: String,
    pub level: String,
    pub edition: String,
    #[serde(default)]
    pub description: String,
    #[serde(default)]
    pub parts: Vec<BookPart>,
    #[serde(default)]
    pub sources: Vec<Provenance>,
}

/// Provenance metadata indicating where content originated.
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

/// A named part of a book, the way a school textbook divides itself.
#[derive(Clone, Debug, PartialEq, serde::Serialize, serde::Deserialize, utoipa::ToSchema)]
pub struct BookPart {
    pub id: String,
    pub order: i64,
    pub title: String,
}

/// A chapter of a book.
#[derive(Clone, Debug, PartialEq, serde::Serialize, serde::Deserialize, utoipa::ToSchema)]
pub struct Chapter {
    pub chapter_id: String,
    pub schema_version: u32,
    pub updated_at: String,
    pub title: String,
    pub book_id: String,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub part_id: Option<String>,
    #[serde(default)]
    pub order: i64,
    #[serde(default)]
    pub facts_inherited: bool,
    #[serde(default)]
    pub learning_objectives: Vec<LearningObjective>,
    #[serde(default)]
    pub prerequisites: Vec<String>,
    #[serde(default)]
    pub formula_sheet: Vec<FormulaSheetEntry>,
    #[serde(default)]
    pub glossary: Vec<GlossaryEntry>,
    #[serde(default)]
    pub sections: Vec<ChapterSection>,
    #[serde(default)]
    pub exercises: Vec<ChapterExercise>,
    #[serde(default)]
    pub exam_traps: Vec<ExamTrap>,
    #[serde(default)]
    pub exam_recall_checks: Vec<ExamRecallCheck>,
    #[serde(default)]
    pub sources: Vec<Provenance>,
}

/// A gathered formula in a chapter formula sheet.
#[derive(Clone, Debug, PartialEq, serde::Serialize, serde::Deserialize, utoipa::ToSchema)]
pub struct FormulaSheetEntry {
    #[serde(default)]
    pub id: String,
    pub expression: String,
    pub caption: RichText,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub conditions: Option<RichText>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub provenance: Option<Provenance>,
}

/// A glossary term introduced in a chapter.
#[derive(Clone, Debug, PartialEq, serde::Serialize, serde::Deserialize, utoipa::ToSchema)]
pub struct GlossaryEntry {
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub id: Option<String>,
    pub term: RichText,
    pub definition: RichText,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub provenance: Option<Provenance>,
}

/// Container for section teaching blocks accepting either `{"blocks": [...]}` or `[...]`.
#[derive(Clone, Debug, PartialEq, serde::Serialize, serde::Deserialize, utoipa::ToSchema)]
#[serde(untagged)]
pub enum TeachingTextContainer {
    Wrapped { blocks: Vec<ContentBlock> },
    Raw(Vec<ContentBlock>),
}

impl Default for TeachingTextContainer {
    fn default() -> Self {
        Self::Wrapped { blocks: Vec::new() }
    }
}

impl TeachingTextContainer {
    pub fn blocks(&self) -> &[ContentBlock] {
        match self {
            Self::Wrapped { blocks } => blocks,
            Self::Raw(blocks) => blocks,
        }
    }

    pub fn into_blocks(self) -> Vec<ContentBlock> {
        match self {
            Self::Wrapped { blocks } => blocks,
            Self::Raw(blocks) => blocks,
        }
    }
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

/// The teaching unit of a chapter.
#[derive(Clone, Debug, PartialEq, serde::Serialize, serde::Deserialize, utoipa::ToSchema)]
pub struct ChapterSection {
    pub id: String,
    pub order: i64,
    pub slug: String,
    pub title: String,
    pub est_minutes: i64,
    #[serde(default)]
    pub facts_inherited: bool,
    #[serde(default)]
    pub learning_objectives: Vec<LearningObjective>,
    #[serde(default)]
    pub teaching_text: TeachingTextContainer,
    #[serde(default)]
    pub worked_examples: Vec<SectionWorkedExample>,
    #[serde(default)]
    pub misconceptions: Vec<SectionMisconception>,
    #[serde(default)]
    pub summary_points: Vec<RichText>,
    #[serde(default)]
    pub exercise_ids: Vec<String>,
    #[serde(default)]
    pub exam_links: Vec<ExamLink>,
    #[serde(default)]
    pub provenance: Provenance,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub no_worked_example_reason: Option<String>,
}

/// Option for a chapter exercise.
#[derive(Clone, Debug, PartialEq, serde::Serialize, serde::Deserialize, utoipa::ToSchema)]
pub struct ExerciseOption {
    pub id: String,
    pub text: String,
}

/// Solution step for a chapter exercise.
#[derive(Clone, Debug, PartialEq, serde::Serialize, serde::Deserialize, utoipa::ToSchema)]
pub struct ExerciseSolutionStep {
    pub step_number: u32,
    pub expression: String,
}

/// Hint for a chapter exercise.
#[derive(Clone, Debug, PartialEq, serde::Serialize, serde::Deserialize, utoipa::ToSchema)]
pub struct ExerciseHint {
    pub hint_number: u32,
    pub text: RichText,
}

/// A practice item with its answer and its solution.
#[derive(Clone, Debug, PartialEq, serde::Serialize, serde::Deserialize, utoipa::ToSchema)]
pub struct ChapterExercise {
    pub id: String,
    pub section_id: String,
    pub tier: String,
    pub kind: String,
    pub difficulty: i64,
    pub marks: f64,
    pub stem: RichText,
    #[serde(default)]
    pub options: Vec<ExerciseOption>,
    pub answer: RichText,
    pub answer_kind: String,
    #[serde(default)]
    pub solution: Vec<ExerciseSolutionStep>,
    #[serde(default)]
    pub hints: Vec<ExerciseHint>,
    #[serde(default)]
    pub tags: Vec<String>,
    #[serde(default)]
    pub provenance: Provenance,
    pub solution_provenance: String,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub answer_note: Option<String>,
}

/// How an exam examines a chapter section.
#[derive(Clone, Debug, PartialEq, serde::Serialize, serde::Deserialize, utoipa::ToSchema)]
pub struct ExamLink {
    pub exam: String,
    pub subject: String,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub topic_slug: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub subtopic_slug: Option<String>,
    #[serde(default)]
    pub status: String,
    #[serde(default)]
    pub weight_pct: Option<f64>,
    #[serde(default)]
    pub expected_count: Option<f64>,
    #[serde(default)]
    pub source_locator: String,
    #[serde(default)]
    pub papers: Vec<ExamPaper>,
}

/// A past paper the exam used, with the provenance it carries.
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

/// Evidence from past papers backing an examiner trap.
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

/// A mistake candidates make, with the evidence behind it.
#[derive(Clone, Debug, PartialEq, serde::Serialize, serde::Deserialize, utoipa::ToSchema)]
pub struct ExamTrap {
    pub id: String,
    pub exam: String,
    pub subject: String,
    pub section_id: String,
    pub misconception: RichText,
    pub correction: RichText,
    #[serde(default)]
    pub signal: RichText,
    #[serde(default)]
    pub status: String,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub paper_evidence: Option<PaperEvidence>,
    #[serde(default)]
    pub frequency: String,
    #[serde(default)]
    pub provenance: Provenance,
}

/// A practice item written in the exam's own wording.
#[derive(Clone, Debug, PartialEq, serde::Serialize, serde::Deserialize, utoipa::ToSchema)]
pub struct ExamRecallCheck {
    pub id: String,
    pub exam: String,
    pub subject: String,
    pub section_id: String,
    pub stem: RichText,
    #[serde(default)]
    pub options: Vec<ExerciseOption>,
    pub answer: String,
    pub explanation: RichText,
    #[serde(default)]
    pub difficulty: i64,
    #[serde(default)]
    pub source: String,
}

/// A high-yield study note mapped to a syllabus topic or subtopic.
#[derive(Clone, Debug, PartialEq, serde::Serialize, serde::Deserialize, utoipa::ToSchema)]
pub struct TopicNote {
    pub id: String,
    pub exam: String,
    pub subject: String,
    pub topic_slug: String,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub subtopic_slug: Option<String>,
    pub title: String,
    pub read_time_minutes: u8,
    pub key_takeaway: RichText,
    pub sections: Vec<NoteSection>,
    #[serde(default)]
    pub worked_examples: Vec<WorkedExample>,
    #[serde(default)]
    pub formulas: Vec<NoteFormula>,
    #[serde(default)]
    pub active_recall_checks: Vec<ActiveRecallCheck>,
    #[serde(default)]
    pub examiner_traps: Vec<ExaminerTrap>,
    #[serde(default)]
    pub sources: Vec<NoteSource>,
    #[serde(default)]
    pub linked_question_ids: Vec<String>,
}

#[derive(Clone, Debug, PartialEq, serde::Serialize, serde::Deserialize, utoipa::ToSchema)]
pub struct NoteSection {
    pub section_number: u8,
    pub heading: String,
    pub content: RichText,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub callout: Option<NoteCallout>,
}

#[derive(Clone, Debug, PartialEq, serde::Serialize, serde::Deserialize, utoipa::ToSchema)]
pub struct NoteCallout {
    pub kind: String,
    pub text: RichText,
}

#[derive(Clone, Debug, PartialEq, serde::Serialize, serde::Deserialize, utoipa::ToSchema)]
pub struct WorkedExample {
    pub title: String,
    pub problem_statement: RichText,
    pub steps: Vec<SolutionStep>,
    pub final_answer: RichText,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub method_tip: Option<String>,
}

#[derive(Clone, Debug, PartialEq, serde::Serialize, serde::Deserialize, utoipa::ToSchema)]
pub struct SolutionStep {
    pub step_number: u8,
    pub description: String,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub expression: Option<String>,
}

#[derive(Clone, Debug, PartialEq, serde::Serialize, serde::Deserialize, utoipa::ToSchema)]
pub struct NoteFormula {
    pub name: String,
    pub latex: String,
    pub variables: Vec<FormulaVariable>,
    #[serde(default)]
    pub conditions: Vec<String>,
}

#[derive(Clone, Debug, PartialEq, serde::Serialize, serde::Deserialize, utoipa::ToSchema)]
pub struct FormulaVariable {
    pub symbol: String,
    pub name: String,
    pub unit: String,
}

#[derive(Clone, Debug, PartialEq, serde::Serialize, serde::Deserialize, utoipa::ToSchema)]
pub struct ActiveRecallCheck {
    pub check_number: u8,
    pub prompt: String,
    pub options: Vec<String>,
    pub correct_index: u8,
    pub explanation: String,
}

#[derive(Clone, Debug, PartialEq, serde::Serialize, serde::Deserialize, utoipa::ToSchema)]
pub struct ExaminerTrap {
    pub misconception: String,
    pub correction: String,
}

/// A citation for the claims in a study note. `locator` names the exact
/// section, page, or heading so a reviewer can check the source without
/// searching the whole document.
#[derive(Clone, Debug, PartialEq, serde::Serialize, serde::Deserialize, utoipa::ToSchema)]
pub struct NoteSource {
    pub title: String,
    pub url: String,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub locator: Option<String>,
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
