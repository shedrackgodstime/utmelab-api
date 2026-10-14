//! The bank's storage seam (D23).
//!
//! Routes and the dashboard talk to `dyn Store`. `JsonStore` is the only
//! implementation today; when Turso arrives it becomes a second one and the swap
//! is a constructor change — no route, no domain type and no response shape
//! moves.

use crate::bank::model::{Exam, Question, Requirement, Subject, Subtopic, Topic};
use crate::bank::readiness::Blueprint;
use crate::bank::{Novel, NovelDoc, Passage, Syllabus};

/// Default page size when a caller does not ask for one (D30).
pub const DEFAULT_PER_PAGE: u32 = 50;

/// Hard ceiling. A caller must not be able to request the whole bank in one
/// response — that is what makes `/questions` safe to expose.
pub const MAX_PER_PAGE: u32 = 200;

/// What to select. Paging is deliberately **not** here: it belongs to the store
/// so a Turso impl can push `LIMIT/OFFSET` down (D30).
#[derive(Clone, Copy, Debug, Default)]
pub struct QuestionFilter<'a> {
    pub exam: Option<&'a str>,
    pub subject: Option<&'a str>,
    pub subtopic: Option<&'a str>,
    pub verified: Option<bool>,
    /// Substring of `text`, matched case-insensitively (D44). A Turso impl
    /// pushes this down as `LIKE '%q%'` — the seam, not the route, owns it.
    pub text: Option<&'a str>,
    /// Provenance: `past_paper`, `claimed_paper`, `authored` or `imported`.
    /// Lets a consumer ask for only the questions whose origin they can stand
    /// behind.
    pub source: Option<&'a str>,
    /// The exam cohort the question is prepared for (D52).
    pub year: Option<u16>,
    /// Country code, e.g. `GH`. Filters through subtopic → topic scope;
    /// untagged questions are unscoped and always included. Absent means
    /// the full honest view, never an assumed country.
    pub country: Option<&'a str>,
}

/// One page plus the totals (D3). Every implementation must produce identical
/// numbers — that is D23 requirement 3.
#[derive(Clone, Debug)]
pub struct QuestionPage {
    pub questions: Vec<Question>,
    pub page: u32,
    pub per_page: u32,
    pub total_records: usize,
}

impl QuestionPage {
    pub fn total_pages(&self) -> u32 {
        if self.total_records == 0 {
            return 0;
        }
        self.total_records.div_ceil(self.per_page as usize) as u32
    }
}

/// Read-only access to the bank.
///
/// **Every implementation must agree on all six** or the swap is not free:
/// 1. identical types (the D11 constant);
/// 2. identical ordering (stable, by id);
/// 3. identical paging totals;
/// 4. identical *absence* — a topic with no questions does not appear (D16);
/// 5. identical validation — invalid data fails to load, not to serve;
/// 6. an identical `version()` for identical content (D42). A Turso impl
///    fingerprints the rows it would serve, so a consumer's cached copy is
///    invalidated by a content change rather than by a deploy.
pub trait Store: Send + Sync {
    /// Every servable question, in file order. Used by the importer to spot
    /// duplicates before writing (D51); routes never need it.
    fn questions(&self) -> &[Question];

    /// Fingerprint of the content being served. Equal string means equal
    /// content; anything else means a consumer should refresh (D42).
    fn version(&self) -> &str;

    /// Distinct exams that have at least one subject, sorted.
    fn exams(&self) -> Vec<&str>;

    /// One exam's record (D66) — name, countries, paper shape, rules.
    fn exam(&self, code: &str) -> Option<&Exam>;

    /// Countries a topic is scoped to, sorted. Empty means universal — the
    /// topic belongs to every member country of its exam (D66-scope). The
    /// common case (all 582 JAMB topics today) carries no rows at all.
    fn topic_scope(&self, topic: &str) -> Vec<String>;

    /// Paper-assembly rules for an exam in a country, in file order.
    fn requirements(&self, exam: &str, country: &str) -> Vec<&Requirement>;

    fn subjects(&self, exam: &str) -> Vec<&Subject>;
    fn subject(&self, exam: &str, slug: &str) -> Option<&Subject>;

    fn syllabus(&self, exam: &str, subject_slug: &str, country: Option<&str>) -> Option<Syllabus>;

    /// Select and page in one call. Implementations must clamp `per_page` to
    /// [`MAX_PER_PAGE`] and treat `page < 1` as page 1.
    /// One question by id, for routes that address a single row.
    fn question(&self, id: &str) -> Option<&Question>;

    fn questions_page(&self, filter: QuestionFilter<'_>, page: u32, per_page: u32) -> QuestionPage;

    fn subject_count(&self) -> usize;
    fn question_count(&self) -> usize;

    /// Servable questions per subtopic slug, in one call. The topic route
    /// needs every child's count; one batched map beats one `questions_page`
    /// per subtopic (which scans and sorts just to read a total). A Turso
    /// impl answers with a single `GROUP BY` — the seam, not the route, owns
    /// the query (D23/D30).
    fn subtopic_counts(&self) -> std::collections::HashMap<String, usize>;

    /// Records present but not servable (e.g. an unassigned exam, D21). Exposed
    /// on `/health` so a withheld record is never silent.
    fn withheld_count(&self) -> usize;

    fn passage(&self, id: &str) -> Option<&Passage>;

    fn topic(&self, exam: &str, subject: &str, slug: &str) -> Option<(&Topic, Vec<&Subtopic>)>;

    // ── novels (D35) ─────────────────────────────────────────────────────
    //
    // Novels live as one document per book under `data/novels/` and never move
    // to a database. The directory is the index.

    /// All novels, optionally scoped to an exam, newest prescription first.
    fn novels(&self, exam: Option<&str>) -> Vec<&Novel>;

    /// The featured novel for an exam — the current set text.
    fn featured_novel(&self, exam: &str) -> Option<&Novel>;

    /// A whole novel document: book, chapters, characters, themes.
    fn novel(&self, id: &str) -> Option<&NovelDoc>;

    /// Measured expectations for one exam subject (D63, provisional,
    /// opt-in). Empty where no blueprint rows exist — absence is honest.
    fn blueprints(&self, exam: &str, subject: &str) -> Vec<Blueprint>;
}
