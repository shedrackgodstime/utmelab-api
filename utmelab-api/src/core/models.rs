use serde::Serialize;

#[derive(Serialize)]
pub struct TableRef {
    pub name: String,
}

#[derive(Serialize)]
pub struct ServiceStatus {
    pub service: &'static str,
    pub has_sync: bool,
    pub contract_ok: bool,
    pub gate_rejections: u64,
    pub pulls_applied: u64,
    pub pulls_empty: u64,
    /// Unix seconds of the last pull attempt (0 = none yet).
    pub last_pull_unix: u64,
}

#[derive(Serialize)]
pub struct RowPage {
    pub cols: Vec<String>,
    pub rows: Vec<Vec<String>>,
}

#[derive(serde::Deserialize)]
pub struct PrefixBody {
    pub prefix: String,
}

/// The caller's own key, as the key itself may see it. No hashes,
/// no secrets, no other keys — safe to hand to whoever presented it.
#[derive(Clone, Debug, serde::Serialize)]
pub struct KeyInfo {
    pub prefix: String,
    pub admin: bool,
    pub scopes: Vec<String>,
}

/// Page of questions as served. Counts describe the filtered set, not
/// the bank — a consumer pages `total_pages`, never guesses.
#[derive(Clone, Debug, serde::Serialize)]
pub struct QuestionPageResponse {
    pub questions: Vec<RenderedQuestion>,
    pub page: u32,
    pub per_page: u32,
    pub total_pages: u32,
    pub total_records: usize,
    pub includes_explanation: bool,
}

/// Plain text plus offset marks. `text` stays searchable as characters;
/// structure rides in `inline` as Unicode-scalar offsets, never bytes.
#[derive(Clone, Debug, PartialEq, serde::Serialize, serde::Deserialize)]
pub struct RichText {
    pub text: String,
    pub inline: Vec<Inline>,
}

/// One offset mark. Serialised flat with an adjacent `kind` tag, e.g.
/// `{"start":24,"len":6,"kind":"underline"}`.
#[derive(Clone, Debug, PartialEq, serde::Serialize, serde::Deserialize)]
pub struct Inline {
    /// Offset in Unicode scalar values from the start of `text`.
    pub start: u32,
    /// Length in Unicode scalar values. Zero for an image anchor, which
    /// marks an attachment point rather than a span.
    pub len: u32,
    #[serde(flatten)]
    pub kind: InlineKind,
}

#[derive(Clone, Debug, PartialEq, serde::Serialize, serde::Deserialize)]
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
#[derive(Clone, Copy, Debug, PartialEq, serde::Serialize, serde::Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum ImagePosition {
    Above,
    Below,
}

#[derive(Clone, Debug, PartialEq, serde::Serialize, serde::Deserialize)]
pub struct Choice {
    pub id: String,
    pub text: RichText,
}

/// Why the answer is what it is: teaser, working, and the distractor
/// that catches people.
#[derive(Clone, Debug, PartialEq, serde::Serialize, serde::Deserialize)]
pub struct Explanation {
    pub key_point: RichText,
    pub body: RichText,
    #[serde(default)]
    pub trap: Option<RichText>,
}

/// One question as stored. Answer always present here — withholding
/// happens in [`crate::core::catalog::render`], never in storage.
#[derive(Clone, Debug, PartialEq, serde::Serialize, serde::Deserialize)]
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
/// optional — a row states only what was measured, never a filled-in
/// zero. Empty result where no rows exist is honest absence, not 404.
#[derive(Clone, Debug, PartialEq, serde::Serialize)]
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

/// A prescribed text. One row per (exam, cycle) — the set text rotates,
/// so the prescription years are load-bearing, not decorative.
#[derive(Clone, Debug, PartialEq, serde::Serialize, serde::Deserialize)]
pub struct Novel {
    pub id: String,
    pub title: String,
    pub author: String,
    /// Unknown for older set texts — absent, not zero.
    pub year_published: Option<u16>,
    pub exam: String,
    /// Every cycle this is (or was) the set text for.
    pub year_prescribed: Vec<u16>,
    /// Which paper sets it: reading text or prescribed literature.
    pub category: String,
    /// At most one per exam — the current set text.
    pub featured: bool,
    pub synopsis: String,
    pub setting_place: String,
    pub setting_period: String,
    pub cover_image: Option<String>,
}

/// One novel with everything: book, chapters, characters, themes, quiz.
/// Matches the established detail shape exactly, answers included —
/// callers already read quiz rows here, so withholding would silently
/// change the contract rather than improve it.
#[derive(Clone, Debug, PartialEq, serde::Serialize, serde::Deserialize)]
pub struct NovelDoc {
    #[serde(flatten)]
    pub novel: Novel,
    pub chapters: Vec<NovelChapter>,
    pub characters: Vec<NovelCharacter>,
    pub themes: Vec<NovelTheme>,
    pub questions: Vec<NovelQuestion>,
}

#[derive(Clone, Debug, PartialEq, serde::Serialize, serde::Deserialize)]
pub struct NovelChapter {
    pub number: u8,
    pub title: String,
    /// Null means not yet written — absence is the signal.
    pub summary: Option<String>,
    pub key_events: Vec<String>,
}

#[derive(Clone, Debug, PartialEq, serde::Serialize, serde::Deserialize)]
pub struct NovelCharacter {
    pub name: String,
    pub role: String,
    pub character_type: String,
    pub description: String,
}

#[derive(Clone, Debug, PartialEq, serde::Serialize, serde::Deserialize)]
pub struct NovelTheme {
    pub name: String,
    pub description: String,
    pub evidence: Vec<String>,
}

/// A quiz item about the book. Points at a chapter, not a subtopic;
/// the novel is the passage, so there is no passage id.
#[derive(Clone, Debug, PartialEq, serde::Serialize, serde::Deserialize)]
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

/// One novel quiz row as served. `novel_id` is stamped by the caller —
/// the stored row does not carry it.
#[derive(Clone, Debug, PartialEq, serde::Serialize)]
pub struct RenderedNovelQuestion {
    pub id: String,
    pub novel_id: String,
    pub chapter_number: Option<u8>,
    pub text: RichText,
    pub options: Vec<Choice>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub answer: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub explanation: Option<Explanation>,
    pub verified: bool,
}

/// One page of novel quiz rows. Counts describe the chapter-filtered
/// set, same envelope rule as questions.
#[derive(Clone, Debug, PartialEq, serde::Serialize)]
pub struct NovelQuestionPage {
    pub questions: Vec<RenderedNovelQuestion>,
    pub page: u32,
    pub per_page: u32,
    pub total_pages: u32,
    pub total_records: usize,
    pub includes_explanation: bool,
}

/// A stimulus shared by many questions — one comprehension passage
/// serving five questions, one cloze serving ten. Questions carry only
/// the id; consumers resolve it here, never ignore it.
#[derive(Clone, Debug, serde::Serialize)]
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

/// One question as served. Identical to storage except the answer and
/// working, which are present only when explicitly requested — an answer
/// in a default payload gets rendered by somebody, eventually, by
/// accident. `verified` comes from the verification log, never a stored flag.
#[derive(Clone, Debug, PartialEq, serde::Serialize)]
pub struct RenderedQuestion {
    pub id: String,
    pub exam: String,
    pub subject: String,
    pub year: u16,
    pub source: String,
    pub text: RichText,
    pub options: Vec<Choice>,
    pub section: Option<String>,
    /// A stimulus this row belongs to — fetch it, never ignore it: the
    /// stem may be unanswerable without it.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub passage_id: Option<String>,
    pub marks: f32,
    pub difficulty: u8,
    pub verified: bool,
    /// Present only when explanations were requested.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub answer: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub explanation: Option<Explanation>,
}

/// One exam as stored. Facts live here, not scattered across call sites.
///
/// `status` is a passthrough string (`live` | `planned` | `retired`
/// today): a new board status must keep serving, never break
/// deserialization of every row. Nullable columns stay `Option` for the
/// same honesty — unstated is null, never invented.
#[derive(Clone, Debug, PartialEq, serde::Serialize)]
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
/// exam carrying that board's own name — not one row with an alias.
#[derive(Clone, Debug, PartialEq, serde::Serialize)]
pub struct Subject {
    pub slug: String,
    pub exam: String,
    pub name: String,
    pub is_compulsory: bool,
    /// MCQs the objective paper holds. Null where unverified — absence
    /// is data, never a zero masquerading as a fact.
    pub objective_paper_questions: Option<u32>,
}

/// A topic within one exam's syllabus.
#[derive(Clone, Debug, PartialEq, serde::Serialize)]
pub struct Topic {
    pub slug: String,
    pub subject: String,
    pub exam: String,
    pub name: String,
    pub order: u32,
    /// Marks the board gives this topic. Zero means "not published",
    /// never "worth nothing" — a fabricated weight would reach
    /// consumers as a fact.
    pub weight: u32,
    /// Examinable statements attached at topic level. Empty where the
    /// board states none — never invented.
    pub objectives: Vec<String>,
}

/// One board rule about which subjects a paper needs. An empty `subjects`
/// means "every exam subject not named by another group"; `min_select` is
/// how many of that pool must be ready before the paper is real.
#[derive(Clone, Debug, PartialEq, serde::Serialize)]
pub struct Requirement {
    pub group: String,
    pub min_select: u32,
    pub subjects: Vec<String>,
}

/// One subject's slot in an exam scheme. `questions` is the stated paper
/// size (null where unverified), and `marks_per_question` is stated only
/// where the bank supports it — both are absences, never zeros.
#[derive(Clone, Debug, PartialEq, serde::Serialize)]
pub struct SubjectSlot {
    pub slug: String,
    pub name: String,
    pub compulsory: bool,
    pub questions: Option<u32>,
    pub marks_per_question: Option<f32>,
}

/// How an exam's paper is shaped, restated from the bank (D19). This is a
/// constant over our content, so it moves only when the bank does.
#[derive(Clone, Debug, PartialEq, serde::Serialize)]
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
#[derive(Clone, Debug, PartialEq, serde::Serialize)]
pub struct PaperReadiness {
    pub exam: String,
    pub scheme: Scheme,
    /// True when every requirement group for this scope holds enough
    /// verified questions to fill its `min_select` slots.
    pub complete: bool,
}
