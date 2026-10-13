//! The bank's domain types — the D11 constant, as stored.
//!
//! No HTTP, no storage, no serde renames: this is what a question *is*. Both
//! surfaces (`api/`, `app/`) read these, so neither gets to reshape them.

use serde::{Deserialize, Serialize};
use utoipa::ToSchema;

// ── catalog ──────────────────────────────────────────────────────────────────

/// One exam as a data record (D66). Facts about an exam live here, not
/// scattered across subject rows and hardcoded comparisons — `duration` was
/// `(exam == "JAMB").then_some(120)` and the paper shape rode in a function
/// argument until this record existed.
#[derive(Clone, Debug, Serialize, Deserialize, ToSchema)]
pub struct Exam {
    /// Exam code, e.g. `JAMB`.
    pub code: String,
    pub name: String,
    /// Member countries running this exam, e.g. WAEC's five.
    #[serde(default)]
    pub countries: Vec<String>,
    /// `live` serves, `planned` is announced, `retired` is history.
    pub status: ExamStatus,
    /// Whether a full paper can be assembled at all. Null where it cannot
    /// be stated — same honesty rule as every other Option here.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub has_full_paper: Option<bool>,
    /// Subjects in a full paper (JAMB: 4). Null where unstated.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub subjects_required: Option<u32>,
    /// Minutes for a full sitting, verified only. Null where unverified.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub duration_minutes: Option<u32>,
    /// Board-stated rules a consumer must know (N-of-M, paper numbering).
    /// Un-hardcodes the literals that used to live in `scheme::rules_for`.
    #[serde(default)]
    pub rules: Vec<String>,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize, ToSchema)]
#[serde(rename_all = "lowercase")]
pub enum ExamStatus {
    Live,
    Planned,
    Retired,
}

/// One exam's offering of a subject (D21). The same concept can appear once per
/// exam, carrying that board's own name — `Use of English` and
/// `English Language` are two true rows, not one row with an alias.
#[derive(Clone, Debug, Serialize, Deserialize, ToSchema)]
pub struct Subject {
    pub slug: String,
    pub exam: String,
    pub name: String,
    pub is_compulsory: bool,
    /// MCQs the objective paper holds — or null where unverified (D66).
    /// A bare integer here once asserted board fact for nine rows that had
    /// no source; D50's rule is absence, and absence is what null carries.
    /// (It also covers "three papers, one count" — in both cases no single
    /// number can be stated, so one value serves honestly.)
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub objective_paper_questions: Option<u32>,
}

/// A topic within one exam's syllabus.
#[derive(Clone, Debug, Serialize, Deserialize, ToSchema)]
pub struct Topic {
    pub slug: String,
    pub subject: String,
    pub exam: String,
    pub name: String,
    pub order: u32,
    /// Marks JAMB gives this topic. **0 means "not published"**, never "worth
    /// nothing" — JAMB states weights for some subjects and not others, and a
    /// fabricated weight would reach consumers as a fact.
    pub weight: u32,
    /// The examinable statements JAMB attaches to this topic. Objectives sit
    /// here because that is the level JAMB states them at; subtopics inherit
    /// none of their own rather than being given invented ones.
    #[serde(default)]
    pub objectives: Vec<String>,
}

/// A drill-granular unit. Only exists for topics that hold enough questions to
/// practise (D16).
#[derive(Clone, Debug, Serialize, Deserialize, ToSchema)]
pub struct Subtopic {
    pub slug: String,
    pub topic: String,
    pub name: String,
    pub order: u32,
    #[serde(default)]
    pub objectives: Vec<String>,
}

// ── rich text (D60) ────────────────────────────────────────────────────────────
//
// Every text-bearing field is `RichText { text, inline }`. `text` stays plain
// (LaTeX `\(…\)` passes through as characters) so grep, diff, equality and
// search keep working; structure rides in `inline` as offset marks. Offsets
// are Unicode scalar values (Rust `char`s), never bytes, and a mark running
// past the end of its text is refused at load — D54's integrity bar, moved
// from substring-matching to bounds-checking.

/// Plain text plus offset marks (D60).
#[derive(Clone, Debug, Serialize, Deserialize, ToSchema)]
pub struct RichText {
    pub text: String,
    /// Empty for unmarked prose — the common case, and what the harvester
    /// produces before review adds marks.
    #[serde(default)]
    pub inline: Vec<Inline>,
}

impl RichText {
    /// Unmarked text.
    pub fn plain(text: impl Into<String>) -> Self {
        Self {
            text: text.into(),
            inline: Vec::new(),
        }
    }

    /// The stem names an underlined word or portion ("the underlined word").
    pub fn names_underline(&self) -> bool {
        self.text.to_lowercase().contains("underlin")
    }

    /// True when any mark satisfies the predicate.
    pub fn has_mark(&self, pred: impl Fn(&InlineKind) -> bool) -> bool {
        self.inline.iter().any(|m| pred(&m.kind))
    }

    /// Load-time problems for this value. Empty means clean.
    pub fn validate(&self, id: &str, field: &str) -> Vec<String> {
        let mut problems = Vec::new();
        let n = self.text.chars().count() as u64;
        for (i, m) in self.inline.iter().enumerate() {
            let end = m.start as u64 + m.len as u64;
            if end > n {
                problems.push(format!(
                    "{field} of '{id}': mark {i} (start {}, len {}, kind {}) runs past the end of {n} chars",
                    m.start,
                    m.len,
                    m.kind.name(),
                ));
            }
            if let InlineKind::Image { url, .. } = &m.kind {
                if !url.starts_with("https://") {
                    problems.push(format!(
                        "{field} of '{id}': mark {i} has image URL {url:?} — must be absolute https",
                    ));
                }
            }
        }
        // Marks may share an identical range (bold+underline) but never
        // partially overlap — one checkable invariant (D60). Sorted by
        // (start, len), any overlapping set has an overlapping adjacent pair.
        let mut order: Vec<usize> = (0..self.inline.len()).collect();
        order.sort_by_key(|&i| (self.inline[i].start, self.inline[i].len));
        for pair in order.windows(2) {
            let (a, b) = (&self.inline[pair[0]], &self.inline[pair[1]]);
            let a_end = a.start as u64 + a.len as u64;
            let identical = b.start == a.start && b.len == a.len;
            if (b.start as u64) < a_end && !identical {
                problems.push(format!(
                    "{field} of '{id}': mark (start {}, len {}) partially overlaps (start {}, len {})",
                    a.start, a.len, b.start, b.len,
                ));
            }
        }
        problems
    }
}

/// One mark: where it applies and what it means.
#[derive(Clone, Debug, Serialize, Deserialize, ToSchema)]
pub struct Inline {
    /// Offset in Unicode scalar values from the start of `text`.
    pub start: u32,
    /// Length in Unicode scalar values. Zero for an image anchor, which marks
    /// an attachment point rather than a span.
    pub len: u32,
    #[serde(flatten)]
    pub kind: InlineKind,
}

/// The mark vocabulary (D60). Serialised with an adjacent `kind` tag so every
/// mark is one flat object: `{"start":24,"len":6,"kind":"underline"}` or
/// `{"start":37,"len":0,"kind":"image","url":"…","position":"below"}`.
#[derive(Clone, Debug, Serialize, Deserialize, ToSchema)]
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

impl InlineKind {
    pub fn name(&self) -> &'static str {
        match self {
            Self::Bold => "bold",
            Self::Italic => "italic",
            Self::Underline => "underline",
            Self::Strike => "strike",
            Self::Subscript => "subscript",
            Self::Superscript => "superscript",
            Self::Image { .. } => "image",
        }
    }
}

// ── verification log (D62) ───────────────────────────────────────────────────
//
// `verified` on the wire is one bool; the store keeps the history. Only a
// human pass covering answer+explanation counts, and only while the content
// it covered is identical to what we hold now. AI writes signal rows, never
// the sell flag.

/// One verification event on one question (D62).
#[derive(Clone, Debug, Serialize, Deserialize, ToSchema)]
pub struct Verification {
    pub id: String,
    pub question_id: String,
    pub kind: VerifyKind,
    pub verdict: Verdict,
    /// What was actually checked. A human pass counts only when it covers
    /// answer *and* explanation.
    #[serde(default)]
    pub scope: Vec<VerifyCheck>,
    /// Who/what checked: a human label, a model run id, or a rule name.
    pub verifier: String,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub detail: Option<String>,
    /// [`Question::content_fingerprint`] (or the novel equivalent) at check
    /// time. Any content edit voids the pass.
    pub content_hash: String,
    pub created_at: String,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize, ToSchema)]
#[serde(rename_all = "snake_case")]
pub enum VerifyKind {
    AutoRule,
    AiBulk,
    AiSingle,
    Human,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize, ToSchema)]
#[serde(rename_all = "lowercase")]
pub enum Verdict {
    Pass,
    Fail,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize, ToSchema)]
#[serde(rename_all = "snake_case")]
pub enum VerifyCheck {
    Answer,
    Explanation,
    TopicLink,
    Marks,
    Bounds,
    Dupe,
}

/// D62: the latest human row covering answer+explanation decides. A later
/// fail voids an earlier pass; AI rows never count.
pub fn human_verified(
    verifications: &[Verification],
    question_id: &str,
    content_hash: &str,
) -> bool {
    let mut rows: Vec<&Verification> = verifications
        .iter()
        .filter(|v| {
            v.question_id == question_id
                && v.kind == VerifyKind::Human
                && v.scope.contains(&VerifyCheck::Answer)
                && v.scope.contains(&VerifyCheck::Explanation)
        })
        .collect();
    rows.sort_by(|a, b| {
        a.created_at
            .cmp(&b.created_at)
            .then_with(|| a.id.cmp(&b.id))
    });
    match rows.last() {
        Some(v) => v.verdict == Verdict::Pass && v.content_hash == content_hash,
        None => false,
    }
}

// ── content ──────────────────────────────────────────────────────────────────

/// One answer choice. Named `Choice` because `Option` is Rust's, not ours.
///
/// `id` is stable identity; the **label** the student sees (A, B, C…) is
/// assigned from array position at render time and is never stored (D15).
#[derive(Clone, Debug, Serialize, Deserialize, ToSchema)]
pub struct Choice {
    pub id: String,
    pub text: RichText,
}

/// Where the figure renders relative to the stem. Data, never inferred: the
/// parent DB carries both ("the diagram above" ×1400, "the diagram below"
/// ×144), so assuming one placement misrenders one row in eleven. A question
/// with an image always knows its placement; a question without one carries
/// none — the struct makes the nonsense state (placement without a figure)
/// unrepresentable.
#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize, ToSchema)]
#[serde(rename_all = "lowercase")]
pub enum ImagePosition {
    Above,
    Below,
}

impl ImagePosition {
    pub fn as_str(self) -> &'static str {
        match self {
            Self::Above => "above",
            Self::Below => "below",
        }
    }
}

/// Why the answer is what it is (D17). `key_point` is the flashcard teaser,
/// `body` the working, `trap` the distractor that catches people.
#[derive(Clone, Debug, Serialize, Deserialize, ToSchema)]
pub struct Explanation {
    pub key_point: RichText,
    pub body: RichText,
    #[serde(default)]
    pub trap: Option<RichText>,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct Question {
    pub id: String,
    pub exam: String,
    pub subject: String,
    /// The exam cohort this question is **prepared for** (D52).
    ///
    /// This is not "the year of the paper it was lifted from" — `source` says
    /// that. A row with `year: 2025, source: "authored"` means *written against
    /// the 2025 syllabus*; `claimed_paper` means *a third party attributes it to
    /// a 2025 paper, unverified*. Required on every row, because a consumer
    /// filtering by year cannot use a field that is empty for a fifth of the
    /// bank.
    pub year: u16,
    /// Where the row came from: `past_paper` or `authored`. Consumers can
    /// therefore tell an exam item from one we wrote, and never assume.
    pub source: String,
    pub text: RichText,
    pub options: Vec<Choice>,
    /// An **option id**, never a label or an index (D15).
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
    /// Derived at load from the verification log (D62) — never authored.
    /// Skipped in serde: files carry no `verified` key.
    #[serde(skip)]
    pub verified: bool,
}

impl Question {
    /// Identity of the content review covers (D62): stem, options, answer and
    /// explanation, including marks. Any edit changes this; the loader voids
    /// `verified` when it no longer matches the last human pass. The
    /// construction is deliberately boring so tooling in any language can
    /// replicate it byte-for-byte (see the migration check; U+001F separates
    /// fields, U+001E separates option ids from their text).
    pub fn content_fingerprint(&self) -> String {
        let mut parts = vec![self.text.text.clone()];
        for o in &self.options {
            parts.push(format!("{}\u{1e}{}", o.id, o.text.text));
        }
        parts.push(self.answer.clone());
        let mut marks: Vec<String> = self.text.inline.iter().map(mark_key).collect();
        for o in &self.options {
            marks.extend(o.text.inline.iter().map(mark_key));
        }
        parts.push(marks.join("|"));
        match &self.explanation {
            Some(e) => {
                parts.push(e.key_point.text.clone());
                parts.push(
                    e.key_point
                        .inline
                        .iter()
                        .map(mark_key)
                        .collect::<Vec<_>>()
                        .join("|"),
                );
                parts.push(e.body.text.clone());
                parts.push(
                    e.body
                        .inline
                        .iter()
                        .map(mark_key)
                        .collect::<Vec<_>>()
                        .join("|"),
                );
                match &e.trap {
                    Some(t) => {
                        parts.push(t.text.clone());
                        parts.push(t.inline.iter().map(mark_key).collect::<Vec<_>>().join("|"));
                    }
                    None => parts.push(String::new()),
                }
            }
            None => parts.push(String::new()),
        }
        fingerprint_parts(&parts)
    }
}

/// One mark encoded for fingerprinting.
fn mark_key(m: &Inline) -> String {
    let kind = match &m.kind {
        InlineKind::Bold => "bold".to_owned(),
        InlineKind::Italic => "italic".to_owned(),
        InlineKind::Underline => "underline".to_owned(),
        InlineKind::Strike => "strike".to_owned(),
        InlineKind::Subscript => "subscript".to_owned(),
        InlineKind::Superscript => "superscript".to_owned(),
        InlineKind::Image { url, position, alt } => format!(
            "image:{url}:{}:{}",
            position.as_str(),
            alt.as_deref().unwrap_or("")
        ),
    };
    format!("{},{},{}", m.start, m.len, kind)
}

fn fingerprint_parts(parts: &[String]) -> String {
    use sha2::Digest;
    let joined = parts.join("\u{1f}");
    let digest = sha2::Sha256::digest(joined.as_bytes());
    digest.iter().map(|b| format!("{b:02x}")).collect()
}

/// A stimulus shared by many questions — one comprehension passage serving five
/// questions, one cloze serving ten.
#[derive(Clone, Debug, Serialize, Deserialize, ToSchema)]
pub struct Passage {
    pub id: String,
    pub exam: String,
    pub subject: String,
    pub year: u16,
    pub kind: String,
    #[serde(default)]
    pub title: Option<String>,
    #[serde(default)]
    pub author: Option<String>,
    pub text: RichText,
}

// ── novels (D35) ─────────────────────────────────────────────────────────────

/// The default category. English reading texts are the primary use; Literature
/// texts opt in explicitly.
fn default_novel_category() -> String {
    "english".to_owned()
}

/// A prescribed text. One row per (exam, cycle) — the novel rotates yearly, so
/// `year_prescribed` is load-bearing, not decorative.
#[derive(Clone, Debug, Serialize, Deserialize, ToSchema)]
pub struct Novel {
    pub id: String,
    pub title: String,
    pub author: String,
    /// May be unknown for older set texts — absent, not zero.
    #[serde(default)]
    pub year_published: Option<u16>,
    pub exam: String,
    /// Every cycle this is (or was) the set text for. A novel routinely spans
    /// more than one UTME — *The Lekki Headmaster* covers 2025 and 2026.
    #[serde(default)]
    pub year_prescribed: Vec<u16>,
    /// Which paper sets it: the Use-of-English reading text, or a
    /// Literature-in-English prescribed text. Consumers filter on this.
    #[serde(default = "default_novel_category")]
    pub category: String,
    /// At most one per exam — enforced at load. The current set text.
    #[serde(default)]
    pub featured: bool,
    pub synopsis: String,
    pub setting_place: String,
    pub setting_period: String,
    #[serde(default)]
    pub cover_image: Option<String>,
}

/// One file in `data/novels/`. The directory is the index — no separate list
/// to keep in sync. Dropping a novel is deleting its file.
#[derive(Clone, Debug, Serialize, Deserialize, ToSchema)]
pub struct NovelDoc {
    #[serde(flatten)]
    pub novel: Novel,
    #[serde(default)]
    pub chapters: Vec<NovelChapter>,
    #[serde(default)]
    pub characters: Vec<NovelCharacter>,
    #[serde(default)]
    pub themes: Vec<NovelTheme>,
    #[serde(default)]
    pub questions: Vec<NovelQuestion>,
}

#[derive(Clone, Debug, Serialize, Deserialize, ToSchema)]
pub struct NovelChapter {
    pub number: u8,
    pub title: String,
    /// Null means not yet written — absence is the signal (D16).
    #[serde(default)]
    pub summary: Option<String>,
    #[serde(default)]
    pub key_events: Vec<String>,
}

/// Character types use JAMB's own vocabulary (round/flat/foil/hero/antihero/
/// villain/heroine) because that is literally what the syllabus tests.
#[derive(Clone, Debug, Serialize, Deserialize, ToSchema)]
pub struct NovelCharacter {
    pub name: String,
    pub role: String,
    pub character_type: String,
    pub description: String,
}

#[derive(Clone, Debug, Serialize, Deserialize, ToSchema)]
pub struct NovelTheme {
    pub name: String,
    pub description: String,
    #[serde(default)]
    pub evidence: Vec<String>,
}

/// A quiz item about the book. Reuses Option/answer/Explanation machinery —
/// a novel question is answered, shuffled and explained exactly like a subject
/// question. It points at a chapter, not a subtopic, and the novel is the
/// passage, so there is no passage_id.
#[derive(Clone, Debug, Serialize, Deserialize, ToSchema)]
pub struct NovelQuestion {
    pub id: String,
    #[serde(default)]
    pub chapter_number: Option<u8>,
    pub text: RichText,
    pub options: Vec<Choice>,
    /// An option id, same contract as Question.answer (D15).
    pub answer: String,
    #[serde(default)]
    pub explanation: Option<Explanation>,
    /// Derived at load from the verification log (D62) — never authored.
    #[serde(skip)]
    pub verified: bool,
}

impl NovelQuestion {
    /// Same content identity as [`Question::content_fingerprint`], minus the
    /// fields a novel question does not carry (no exam, no explanation trap
    /// split — the whole explanation counts).
    pub fn content_fingerprint(&self) -> String {
        let mut parts = vec![self.text.text.clone()];
        for o in &self.options {
            parts.push(format!("{}\u{1e}{}", o.id, o.text.text));
        }
        parts.push(self.answer.clone());
        let mut marks: Vec<String> = self.text.inline.iter().map(mark_key).collect();
        for o in &self.options {
            marks.extend(o.text.inline.iter().map(mark_key));
        }
        parts.push(marks.join("|"));
        match &self.explanation {
            Some(e) => {
                parts.push(e.key_point.text.clone());
                parts.push(
                    e.key_point
                        .inline
                        .iter()
                        .map(mark_key)
                        .collect::<Vec<_>>()
                        .join("|"),
                );
                parts.push(e.body.text.clone());
                parts.push(
                    e.body
                        .inline
                        .iter()
                        .map(mark_key)
                        .collect::<Vec<_>>()
                        .join("|"),
                );
                match &e.trap {
                    Some(t) => {
                        parts.push(t.text.clone());
                        parts.push(t.inline.iter().map(mark_key).collect::<Vec<_>>().join("|"));
                    }
                    None => parts.push(String::new()),
                }
            }
            None => parts.push(String::new()),
        }
        fingerprint_parts(&parts)
    }
}

#[cfg(test)]
mod rich_text_tests {
    use super::*;

    fn marked(text: &str, marks: Vec<(u32, u32, InlineKind)>) -> RichText {
        RichText {
            text: text.to_owned(),
            inline: marks
                .into_iter()
                .map(|(start, len, kind)| Inline { start, len, kind })
                .collect(),
        }
    }

    #[test]
    fn plain_text_with_no_marks_is_clean() {
        let rt = RichText::plain("What is two plus two?");
        assert!(rt.validate("q", "text").is_empty());
    }

    #[test]
    fn a_mark_past_the_end_is_refused() {
        let rt = marked("cogent matters", vec![(0, 60, InlineKind::Underline)]);
        let problems = rt.validate("q", "text");
        assert_eq!(problems.len(), 1);
        assert!(
            problems[0].contains("runs past the end of 14 chars"),
            "got: {problems:?}"
        );
    }

    #[test]
    fn a_mark_ending_exactly_at_the_end_is_fine() {
        let rt = marked("cogent", vec![(0, 6, InlineKind::Underline)]);
        assert!(rt.validate("q", "text").is_empty());
    }

    #[test]
    fn offsets_are_unicode_scalars_not_bytes() {
        // "café" is 4 chars but 5 bytes; the mark on é ends at char 4.
        let rt = marked("café", vec![(3, 1, InlineKind::Underline)]);
        assert!(rt.validate("q", "text").is_empty());
        let byte_counted = marked("café", vec![(3, 2, InlineKind::Underline)]);
        assert_eq!(byte_counted.validate("q", "text").len(), 1);
    }

    #[test]
    fn identical_ranges_may_share_but_partial_overlap_is_refused() {
        let shared = marked(
            "cogent matters",
            vec![(0, 6, InlineKind::Bold), (0, 6, InlineKind::Underline)],
        );
        assert!(shared.validate("q", "text").is_empty());
        let overlap = marked(
            "cogent matters",
            vec![(0, 6, InlineKind::Bold), (4, 6, InlineKind::Underline)],
        );
        let problems = overlap.validate("q", "text");
        assert_eq!(problems.len(), 1);
        assert!(
            problems[0].contains("partially overlaps"),
            "got: {problems:?}"
        );
    }

    #[test]
    fn an_image_anchor_at_a_boundary_is_fine_but_inside_a_mark_is_not() {
        let img = |start| Inline {
            start,
            len: 0,
            kind: InlineKind::Image {
                url: "https://cdn.example/x.png".into(),
                position: ImagePosition::Below,
                alt: None,
            },
        };
        let boundary = RichText {
            text: "motion".into(),
            inline: vec![
                img(6),
                Inline {
                    start: 0,
                    len: 6,
                    kind: InlineKind::Bold,
                },
            ],
        };
        assert!(boundary.validate("q", "text").is_empty());
        let inside = RichText {
            text: "motion".into(),
            inline: vec![
                img(3),
                Inline {
                    start: 0,
                    len: 6,
                    kind: InlineKind::Bold,
                },
            ],
        };
        assert_eq!(inside.validate("q", "text").len(), 1);
    }

    #[test]
    fn a_relative_image_url_is_refused() {
        let rt = RichText {
            text: "motion".into(),
            inline: vec![Inline {
                start: 6,
                len: 0,
                kind: InlineKind::Image {
                    url: "diagrams/x.svg".into(),
                    position: ImagePosition::Above,
                    alt: None,
                },
            }],
        };
        let problems = rt.validate("q", "text");
        assert_eq!(problems.len(), 1);
        assert!(
            problems[0].contains("must be absolute https"),
            "got: {problems:?}"
        );
    }

    fn question() -> Question {
        Question {
            id: "q".into(),
            exam: "JAMB".into(),
            subject: "physics".into(),
            year: 2025,
            source: "authored".into(),
            text: RichText::plain("What is two plus two?"),
            options: vec![
                Choice {
                    id: "a".into(),
                    text: RichText::plain("3"),
                },
                Choice {
                    id: "b".into(),
                    text: RichText::plain("4"),
                },
            ],
            answer: "b".into(),
            subtopic_id: None,
            section: None,
            passage_id: None,
            explanation: None,
            marks: 2.5,
            difficulty: 2,
            verified: false,
        }
    }

    #[test]
    fn the_fingerprint_is_stable_and_sensitive() {
        let a = question();
        assert_eq!(a.content_fingerprint(), question().content_fingerprint());
        let mut b = question();
        b.answer = "a".into();
        assert_ne!(a.content_fingerprint(), b.content_fingerprint());
        let mut c = question();
        c.text.inline.push(Inline {
            start: 0,
            len: 4,
            kind: InlineKind::Bold,
        });
        assert_ne!(a.content_fingerprint(), c.content_fingerprint());
    }

    fn verification(
        id: &str,
        kind: VerifyKind,
        verdict: Verdict,
        hash: &str,
        at: &str,
    ) -> Verification {
        Verification {
            id: id.into(),
            question_id: "q".into(),
            kind,
            verdict,
            scope: vec![VerifyCheck::Answer, VerifyCheck::Explanation],
            verifier: "review".into(),
            detail: None,
            content_hash: hash.into(),
            created_at: at.into(),
        }
    }

    #[test]
    fn only_a_matching_human_pass_counts() {
        let q = question();
        let hash = q.content_fingerprint();
        let passes = vec![verification(
            "v1",
            VerifyKind::Human,
            Verdict::Pass,
            &hash,
            "2026-10-13T00:00:00Z",
        )];
        assert!(human_verified(&passes, "q", &hash));
        // AI applause is signal, not review.
        let ai = vec![verification(
            "v1",
            VerifyKind::AiSingle,
            Verdict::Pass,
            &hash,
            "2026-10-13T00:00:00Z",
        )];
        assert!(!human_verified(&ai, "q", &hash));
        // A later fail voids the pass.
        let fail_after = vec![
            verification(
                "v1",
                VerifyKind::Human,
                Verdict::Pass,
                &hash,
                "2026-10-13T00:00:00Z",
            ),
            verification(
                "v2",
                VerifyKind::Human,
                Verdict::Fail,
                &hash,
                "2026-10-14T00:00:00Z",
            ),
        ];
        assert!(!human_verified(&fail_after, "q", &hash));
        // An edit voids the pass.
        assert!(!human_verified(&passes, "q", "some other hash"));
        // A pass that only checked the answer is not review.
        let mut narrow = verification(
            "v1",
            VerifyKind::Human,
            Verdict::Pass,
            &hash,
            "2026-10-13T00:00:00Z",
        );
        narrow.scope = vec![VerifyCheck::Answer];
        assert!(!human_verified(std::slice::from_ref(&narrow), "q", &hash));
    }
}
