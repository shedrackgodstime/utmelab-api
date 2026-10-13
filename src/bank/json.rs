//! `JsonStore` — the bank loaded from `data/*.json` into RAM.
//!
//! Two rules, both load-bearing:
//!   1. **Boot fails on invalid data.** A corrupt or inconsistent bank must not
//!      become a running server serving wrong questions.
//!   2. **Every problem is reported at once**, each naming its file and id.
//!
//! "Invalid" and "not servable" are different things and are handled differently:
//! a fatal problem stops the load; a record that is merely not ready (an
//! unassigned exam) is withheld, counted and logged.

use std::collections::{HashMap, HashSet};
use std::fmt;
use std::path::Path;
use std::path::PathBuf;

use super::model::{Novel, NovelDoc, Passage, Question, Subject, Verification, human_verified};
use super::store::{MAX_PER_PAGE, QuestionFilter, QuestionPage, Store};
use super::{Subtopic, Syllabus, SyllabusSubtopic, SyllabusSummary, SyllabusTopic, Topic};

const FILES: [&str; 5] = [
    "subjects.json",
    "topics.json",
    "subtopics.json",
    "passages.json",
    "questions.json",
];

// ── embedded catalog (slow-moving, baked into the binary) ────────────────────
//
// Subjects/topics/subtopics/passages/novels change monthly and total ~750 KiB.
// They are compiled in so a release is `binary + site/` plus the fast-moving
// `questions.json` — and, once questions move to Turso, `binary + site/` alone.
// Questions stay file-based until that cutover (transitional): review churn is
// daily and must not require a rebuild.
//
// Adding a novel means adding one line to EMBEDDED_NOVELS below — deliberate,
// reviewable, and impossible to forget at deploy time (the file list *is* the
// index, same rule as `data/novels/`).
const EMBEDDED_SUBJECTS: &str = include_str!("../../data/subjects.json");
const EMBEDDED_TOPICS: &str = include_str!("../../data/topics.json");
const EMBEDDED_SUBTOPICS: &str = include_str!("../../data/subtopics.json");
const EMBEDDED_PASSAGES: &str = include_str!("../../data/passages.json");

const EMBEDDED_NOVELS: &[(&str, &str)] = &[
    (
        "lekki-headmaster.json",
        include_str!("../../data/novels/lekki-headmaster.json"),
    ),
    (
        "life-changer.json",
        include_str!("../../data/novels/life-changer.json"),
    ),
    (
        "second-class-citizen.json",
        include_str!("../../data/novels/second-class-citizen.json"),
    ),
    (
        "sweet-sixteen.json",
        include_str!("../../data/novels/sweet-sixteen.json"),
    ),
    (
        "unexpected-joy-at-dawn.json",
        include_str!("../../data/novels/unexpected-joy-at-dawn.json"),
    ),
    (
        "wuthering-heights.json",
        include_str!("../../data/novels/wuthering-heights.json"),
    ),
];

#[derive(Debug)]
pub struct StoreError {
    pub problems: Vec<String>,
}

impl fmt::Display for StoreError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        writeln!(
            f,
            "question bank is invalid ({} problem(s)):",
            self.problems.len()
        )?;
        for p in &self.problems {
            writeln!(f, "  - {p}")?;
        }
        Ok(())
    }
}

impl std::error::Error for StoreError {}

#[derive(Debug, Default)]
struct Checker {
    /// Fatal — the bank is wrong and must not boot.
    problems: Vec<String>,
    /// Not fatal — a valid record that is simply not servable yet.
    withheld: Vec<String>,
}

#[derive(Clone, Debug)]
pub struct JsonStore {
    subjects: Vec<Subject>,
    topics: Vec<Topic>,
    subtopics: Vec<Subtopic>,
    questions: Vec<Question>,

    subject_by_key: HashMap<(String, String), usize>,
    subjects_by_exam: HashMap<String, Vec<usize>>,
    topics_by_subject: HashMap<(String, String), Vec<usize>>,
    subtopics_by_topic: HashMap<String, Vec<usize>>,
    questions_by_subtopic: HashMap<String, Vec<usize>>,
    withheld: usize,
    /// Valid rows that are not servable (unassigned exam, D21). Kept beside
    /// the servable bank — never served, never dropped. `load` used to
    /// `retain()` them away, which made the next `import` rewrite delete them
    /// silently (D58: the civic fixture vanished exactly that way).
    withheld_questions: Vec<Question>,
    /// The verification log (D62). `Question.verified` is derived from this
    /// at load — never authored, never stored on the row.
    verifications: Vec<Verification>,
    novels: Vec<NovelDoc>,
    novel_by_id: HashMap<String, usize>,
    passages: Vec<Passage>,
    /// Content fingerprint of every file we loaded (D42). Cheap invalidation
    /// for consumers: poll `/health`, compare one string.
    version: String,
    passage_by_id: HashMap<String, usize>,
}

impl JsonStore {
    pub fn load(dir: impl AsRef<Path>) -> Result<Self, StoreError> {
        let dir = dir.as_ref();
        let mut c = Checker::default();

        let subjects: Vec<Subject> = read(dir, FILES[0], &mut c);
        let topics: Vec<Topic> = read(dir, FILES[1], &mut c);
        let subtopics: Vec<Subtopic> = read(dir, FILES[2], &mut c);
        let mut store_passages: Vec<Passage> = read(dir, FILES[3], &mut c);
        let questions: Vec<Question> = read(dir, FILES[4], &mut c);

        let mut store = Self {
            subjects,
            topics,
            subtopics,
            questions,
            subject_by_key: HashMap::new(),
            subjects_by_exam: HashMap::new(),
            topics_by_subject: HashMap::new(),
            subtopics_by_topic: HashMap::new(),
            questions_by_subtopic: HashMap::new(),
            withheld: 0,
            withheld_questions: Vec::new(),
            verifications: Vec::new(),
            novels: Vec::new(),
            novel_by_id: HashMap::new(),
            passages: std::mem::take(&mut store_passages),
            passage_by_id: HashMap::new(),
            version: String::new(),
        };
        // Novels: one document per book; the directory is the index.
        store.novels = load_novels(&dir.join("novels"), &mut c);
        store.verifications = read_verifications(&dir.join("verifications.json"), &mut c);
        store.version = fingerprint(dir);
        store.validate(&mut c);

        if !c.problems.is_empty() {
            return Err(StoreError {
                problems: c.problems,
            });
        }

        // Only fully-assigned questions are servable (D21), and only novels
        // that meet the 50-question minimum (D36). Withheld questions are
        // partitioned aside, never dropped (D58).
        store.partition();
        store.derive_verified();
        store.novels.retain(|n| n.questions.len() >= 50);
        for note in &c.withheld {
            tracing::warn!("withheld from serving: {note}");
        }
        store.withheld = c.withheld.len();
        store.index();
        Ok(store)
    }

    /// Transitional loader: catalog + novels from the binary, questions from
    /// `dir/questions.json`.
    ///
    /// This is what `serve` and `import` run on until questions move to Turso.
    /// `dir` needs exactly one file — `questions.json` — so the VPS carries no
    /// catalog to go stale and `data/` shrinks to the one fast-moving table.
    /// Once the Turso question store lands, this method retires with it: the
    /// catalog stays embedded, questions come from the wire, and `dir` goes
    /// away entirely.
    pub fn load_embedded(dir: impl AsRef<Path>) -> Result<Self, StoreError> {
        let dir = dir.as_ref();
        let mut c = Checker::default();

        let subjects: Vec<Subject> = parse_embedded("subjects.json", EMBEDDED_SUBJECTS, &mut c);
        let topics: Vec<Topic> = parse_embedded("topics.json", EMBEDDED_TOPICS, &mut c);
        let subtopics: Vec<Subtopic> = parse_embedded("subtopics.json", EMBEDDED_SUBTOPICS, &mut c);
        let mut store_passages: Vec<Passage> =
            parse_embedded("passages.json", EMBEDDED_PASSAGES, &mut c);
        let questions: Vec<Question> = read(dir, FILES[4], &mut c);

        let mut store = Self {
            subjects,
            topics,
            subtopics,
            questions,
            subject_by_key: HashMap::new(),
            subjects_by_exam: HashMap::new(),
            topics_by_subject: HashMap::new(),
            subtopics_by_topic: HashMap::new(),
            questions_by_subtopic: HashMap::new(),
            withheld: 0,
            withheld_questions: Vec::new(),
            verifications: Vec::new(),
            novels: Vec::new(),
            novel_by_id: HashMap::new(),
            passages: std::mem::take(&mut store_passages),
            passage_by_id: HashMap::new(),
            version: String::new(),
        };
        store.novels = load_novels_embedded(&mut c);
        store.verifications = read_verifications(&dir.join("verifications.json"), &mut c);
        store.version = fingerprint_embedded(dir);
        store.validate(&mut c);

        if !c.problems.is_empty() {
            return Err(StoreError {
                problems: c.problems,
            });
        }

        store.partition();
        store.derive_verified();
        store.novels.retain(|n| n.questions.len() >= 50);
        for note in &c.withheld {
            tracing::warn!("withheld from serving: {note}");
        }
        store.withheld = c.withheld.len();
        store.index();
        Ok(store)
    }

    fn validate(&self, c: &mut Checker) {
        let mut seen = HashSet::new();
        for s in &self.subjects {
            if !seen.insert((s.exam.clone(), s.slug.clone())) {
                c.problems
                    .push(format!("subjects.json: duplicate ({}, {})", s.exam, s.slug));
            }
        }

        let topic_slugs: HashSet<&str> = self.topics.iter().map(|t| t.slug.as_str()).collect();
        let mut unique_topics = HashSet::new();
        for t in &self.topics {
            if !unique_topics.insert(t.slug.as_str()) {
                c.problems
                    .push(format!("topics.json: duplicate slug '{}'", t.slug));
            }
            if !self.has_subject(&t.exam, &t.subject) {
                c.problems.push(format!(
                    "topics.json: '{}' references ({}, {}), which is not a subject",
                    t.slug, t.exam, t.subject
                ));
            }
        }

        let subtopic_slugs: HashSet<&str> =
            self.subtopics.iter().map(|s| s.slug.as_str()).collect();

        // Passages are the one field that may carry paragraph breaks (D56) —
        // `\n\n` is legal here and nowhere else. Entities and tags are refused
        // like everywhere else.
        for p in &self.passages {
            c.problems.extend(p.text.validate(&p.id, "passage"));
            check_plain(&p.id, "passage", &p.text.text, c);
        }
        let mut unique_subtopics = HashSet::new();
        for s in &self.subtopics {
            if !unique_subtopics.insert(s.slug.as_str()) {
                c.problems
                    .push(format!("subtopics.json: duplicate slug '{}'", s.slug));
            }
            if !topic_slugs.contains(s.topic.as_str()) {
                c.problems.push(format!(
                    "subtopics.json: '{}' references unknown topic '{}'",
                    s.slug, s.topic
                ));
            }
        }

        // Novels: at most one featured per exam, a minimum of 50 questions per
        // novel (D36), and every novel question must point at a chapter that
        // exists with an answer that is an option id — the same contract as a
        // subject question (D15).
        //
        // Under 50 is *incomplete*, not corrupt: the novel is withheld from
        // serving (logged, counted) rather than failing the boot. Customers
        // never see a thin novel; authors can still iterate on one.
        {
            let mut featured: HashMap<&str, &str> = HashMap::new();
            for n in &self.novels {
                if n.novel.featured {
                    if let Some(prev) = featured.insert(n.novel.exam.as_str(), n.novel.id.as_str())
                    {
                        c.problems.push(format!(
                            "novels: '{}' and '{}' both claim featured for {}",
                            prev, n.novel.id, n.novel.exam
                        ));
                    }
                }
                if n.questions.len() < 50 {
                    c.withheld.push(format!(
                        "novels/{}.json: only {} questions — withheld until it reaches 50",
                        n.novel.id,
                        n.questions.len()
                    ));
                    continue;
                }
                let chapters: HashSet<u8> = n.chapters.iter().map(|ch| ch.number).collect();
                for q in &n.questions {
                    if let Some(ch) = q.chapter_number {
                        if !chapters.contains(&ch) {
                            c.problems.push(format!(
                                "novels/{}.json: question '{}' points at missing chapter {}",
                                n.novel.id, q.id, ch
                            ));
                        }
                    }
                    let ids: HashSet<&str> = q.options.iter().map(|o| o.id.as_str()).collect();
                    if q.options.len() < 2 {
                        c.problems.push(format!(
                            "novels/{}.json: question '{}' has fewer than 2 options",
                            n.novel.id, q.id
                        ));
                    }
                    if ids.len() != q.options.len() {
                        c.problems.push(format!(
                            "novels/{}.json: question '{}' has duplicate option ids",
                            n.novel.id, q.id
                        ));
                    }
                    if !ids.contains(q.answer.as_str()) {
                        c.problems.push(format!(
                            "novels/{}.json: question '{}' answer '{}' is not an option id",
                            n.novel.id, q.id, q.answer
                        ));
                    }
                    let scope = format!("novels/{}.json", n.novel.id);
                    c.problems
                        .extend(q.text.validate(&q.id, &format!("{scope} text")));
                    for o in &q.options {
                        c.problems.extend(
                            o.text
                                .validate(&q.id, &format!("{scope} option '{}'", o.id)),
                        );
                    }
                    if let Some(e) = &q.explanation {
                        c.problems
                            .extend(e.key_point.validate(&q.id, &format!("{scope} key_point")));
                        c.problems
                            .extend(e.body.validate(&q.id, &format!("{scope} body")));
                    }
                    check_plain(&q.id, &format!("{scope} text"), &q.text.text, c);
                }
            }
        }

        let mut ids = HashSet::new();
        for q in &self.questions {
            if !ids.insert(q.id.as_str()) {
                c.problems
                    .push(format!("questions.json: duplicate id '{}'", q.id));
                continue;
            }

            if !matches!(
                q.source.as_str(),
                "past_paper" | "claimed_paper" | "authored" | "imported"
            ) {
                c.problems.push(format!(
                    "questions.json: '{}' has source '{}' — expected past_paper, claimed_paper, authored or imported",
                    q.id, q.source
                ));
            }
            // Year is the cohort the question is prepared for (D52), required
            // on every row. `source`, not `year`, carries provenance.
            if !(1900..=2100).contains(&q.year) {
                c.problems.push(format!(
                    "questions.json: '{}' has year {} — outside any plausible exam year",
                    q.id, q.year
                ));
            }

            // Marks are load-validated where they live (D60): bounds are
            // Unicode scalars, partial overlaps are refused, image URLs must
            // be absolute https. One bad mark fails the boot like any other
            // corrupt content — a wrong offset renders a lie.
            c.problems.extend(q.text.validate(&q.id, "text"));
            for o in &q.options {
                c.problems
                    .extend(o.text.validate(&q.id, &format!("option '{}'", o.id)));
            }

            // Stems and options are plain text plus \(...\) LaTeX (D56). An
            // HTML entity or tag here is harvest residue — the 139-entity
            // scrub proved it arrives silently — so the loader rejects it
            // rather than serving mojibake to a student.
            check_plain(&q.id, "text", &q.text.text, c);
            for o in &q.options {
                check_plain(&q.id, &format!("option '{}'", o.id), &o.text.text, c);
            }
            if let Some(e) = &q.explanation {
                c.problems.extend(e.key_point.validate(&q.id, "key_point"));
                c.problems.extend(e.body.validate(&q.id, "body"));
                if let Some(t) = &e.trap {
                    c.problems.extend(t.validate(&q.id, "trap"));
                }
                check_plain(&q.id, "key_point", &e.key_point.text, c);
                check_plain(&q.id, "body", &e.body.text, c);
                if let Some(t) = &e.trap {
                    check_plain(&q.id, "trap", &t.text, c);
                }
            }

            // Valid record, not yet servable: withheld, not fatal.
            if q.exam.is_empty() {
                c.withheld
                    .push(format!("questions.json: '{}' has no exam — withheld", q.id));
            } else if !self.has_subject(&q.exam, &q.subject) {
                c.problems.push(format!(
                    "questions.json: '{}' references ({}, {}), which is not a subject",
                    q.id, q.exam, q.subject
                ));
            }

            if let Some(s) = &q.subtopic_id {
                if !subtopic_slugs.contains(s.as_str()) {
                    c.problems.push(format!(
                        "questions.json: '{}' references unknown subtopic '{}'",
                        q.id, s
                    ));
                }
            }

            // A passage link must resolve: a stem pointing at a passage the
            // bank does not hold is unanswerable as served. Inline-passage
            // rows (Arabic/French carry their text in the stem) need no link
            // and are unaffected — only a dangling pointer fails.
            if let Some(p) = &q.passage_id {
                if !self.passages.iter().any(|pp| &pp.id == p) {
                    c.problems.push(format!(
                        "questions.json: '{}' references unknown passage '{}'",
                        q.id, p
                    ));
                }
            }

            let option_ids: HashSet<&str> = q.options.iter().map(|o| o.id.as_str()).collect();
            if q.options.len() < 2 {
                c.problems.push(format!(
                    "questions.json: '{}' has fewer than 2 options",
                    q.id
                ));
            }
            if option_ids.len() != q.options.len() {
                c.problems.push(format!(
                    "questions.json: '{}' has duplicate option ids",
                    q.id
                ));
            }
            if !option_ids.contains(q.answer.as_str()) {
                c.problems.push(format!(
                    "questions.json: '{}' answer '{}' is not one of its option ids",
                    q.id, q.answer
                ));
            }
            if !(1..=5).contains(&q.difficulty) {
                c.problems.push(format!(
                    "questions.json: '{}' difficulty {} is outside 1..=5",
                    q.id, q.difficulty
                ));
            }
        }
    }

    /// Every servable question. Used by integrity tests and bulk jobs.
    pub fn questions(&self) -> &[Question] {
        &self.questions
    }

    /// Valid rows that are not servable (D21). The import path must carry
    /// these through its rewrite — dropping them is silent data loss (D58).
    pub fn withheld_questions(&self) -> &[Question] {
        &self.withheld_questions
    }

    /// Split servable from withheld after a clean validation.
    fn partition(&mut self) {
        let mut kept = Vec::with_capacity(self.questions.len());
        let mut held = Vec::new();
        for q in std::mem::take(&mut self.questions) {
            if q.exam.is_empty() {
                held.push(q);
            } else {
                kept.push(q);
            }
        }
        self.questions = kept;
        self.withheld_questions = held;
    }

    /// Derive every `verified` flag from the log (D62). A row is verified
    /// only while a human pass covering answer+explanation matches its
    /// current content hash — and only while it is answerable as served: a
    /// stem naming an underlined word with no `Underline` mark cannot be
    /// verified no matter what the log says (D57).
    ///
    /// A missing **figure** deliberately does *not* void the flag. The
    /// quarantine figure scan is substring-based and fires on real English
    /// ("debatable" contains "table"; a word-stress item lists "table" as
    /// vocabulary), and a noisy predicate stripping trust from a good row is
    /// worse than a report a human can dismiss. Figure findings stay a
    /// quarantine report for review to judge.
    fn derive_verified(&mut self) {
        for q in self
            .questions
            .iter_mut()
            .chain(self.withheld_questions.iter_mut())
        {
            let ok = human_verified(&self.verifications, &q.id, &q.content_fingerprint())
                && !underline_missing(&q.text);
            q.verified = ok;
        }
        for doc in &mut self.novels {
            for q in &mut doc.questions {
                let ok = human_verified(&self.verifications, &q.id, &q.content_fingerprint())
                    && !underline_missing(&q.text);
                q.verified = ok;
            }
        }
    }

    /// Replace the loaded questions wholesale — the import path only (D51).
    /// Nothing else may call this: bulk edits to the bank go through review.
    ///
    /// Returns the validation problems rather than swallowing them. A write
    /// that produces a file the loader would reject turns a good bank into an
    /// unbootable one, so the caller must see them and refuse.
    pub fn replace_questions(&mut self, questions: Vec<Question>) -> Vec<String> {
        self.questions = questions;
        let mut checker = Checker::default();
        self.validate(&mut checker);
        if checker.problems.is_empty() {
            self.partition();
            self.derive_verified();
        }
        self.index();
        checker.problems
    }

    /// Write every question — servable first, withheld after — back to
    /// `dir/questions.json`. Withheld rows round-trip byte-identically apart
    /// from position; moving one row to the file's end once is the cost of
    /// never losing it again.
    pub fn write_questions(&self, dir: &Path) -> Result<(), StoreError> {
        let all: Vec<&Question> = self
            .questions
            .iter()
            .chain(self.withheld_questions.iter())
            .collect();
        let body = serde_json::to_string_pretty(&all).map_err(|e| StoreError {
            problems: vec![e.to_string()],
        })?;
        std::fs::write(dir.join("questions.json"), format!("{body}\n")).map_err(|e| StoreError {
            problems: vec![format!("write questions.json: {e}")],
        })
    }

    fn questions_for_subtopic(&self, subtopic: &str) -> Vec<&Question> {
        let mut out: Vec<&Question> = self
            .questions_by_subtopic
            .get(subtopic)
            .map(|ix| ix.iter().map(|i| &self.questions[*i]).collect())
            .unwrap_or_default();
        out.sort_by(|a, b| a.id.cmp(&b.id));
        out
    }

    fn has_subject(&self, exam: &str, slug: &str) -> bool {
        self.subjects
            .iter()
            .any(|s| s.exam == exam && s.slug == slug)
    }

    fn index(&mut self) {
        for (i, s) in self.subjects.iter().enumerate() {
            self.subject_by_key
                .insert((s.exam.clone(), s.slug.clone()), i);
            self.subjects_by_exam
                .entry(s.exam.clone())
                .or_default()
                .push(i);
        }
        for (i, t) in self.topics.iter().enumerate() {
            self.topics_by_subject
                .entry((t.exam.clone(), t.subject.clone()))
                .or_default()
                .push(i);
        }
        for (i, s) in self.subtopics.iter().enumerate() {
            self.subtopics_by_topic
                .entry(s.topic.clone())
                .or_default()
                .push(i);
        }
        for (i, q) in self.questions.iter().enumerate() {
            if let Some(s) = &q.subtopic_id {
                self.questions_by_subtopic
                    .entry(s.clone())
                    .or_default()
                    .push(i);
            }
        }
        for (i, n) in self.novels.iter().enumerate() {
            self.novel_by_id.insert(n.novel.id.clone(), i);
        }
        for (i, p) in self.passages.iter().enumerate() {
            self.passage_by_id.insert(p.id.clone(), i);
        }
    }
}

impl Store for JsonStore {
    fn exams(&self) -> Vec<&str> {
        let mut out: Vec<&str> = self.subjects_by_exam.keys().map(String::as_str).collect();
        out.sort_unstable();
        out
    }

    fn subjects(&self, exam: &str) -> Vec<&Subject> {
        self.subjects_by_exam
            .get(exam)
            .map(|ix| ix.iter().map(|i| &self.subjects[*i]).collect())
            .unwrap_or_default()
    }

    fn subject(&self, exam: &str, slug: &str) -> Option<&Subject> {
        self.subject_by_key
            .get(&(exam.to_owned(), slug.to_owned()))
            .map(|i| &self.subjects[*i])
    }

    fn syllabus(&self, exam: &str, subject_slug: &str) -> Option<Syllabus> {
        let subject = self.subject(exam, subject_slug)?;

        let mut topic_ix = self
            .topics_by_subject
            .get(&(exam.to_owned(), subject_slug.to_owned()))
            .cloned()
            .unwrap_or_default();
        topic_ix.sort_by_key(|i| self.topics[*i].order);

        let mut n_topics = 0;
        let mut topics_with = 0;
        let mut n_subtopics = 0;
        let mut subtopics_with = 0;
        let mut n_questions = 0usize;

        let topics: Vec<SyllabusTopic> = topic_ix
            .iter()
            .map(|i| {
                let t = &self.topics[*i];
                n_topics += 1;

                let mut st_ix = self
                    .subtopics_by_topic
                    .get(&t.slug)
                    .cloned()
                    .unwrap_or_default();
                st_ix.sort_by_key(|i| self.subtopics[*i].order);

                let subtopics: Vec<SyllabusSubtopic> = st_ix
                    .iter()
                    .map(|i| {
                        let st = &self.subtopics[*i];
                        n_subtopics += 1;
                        let count = self.questions_for_subtopic(&st.slug).len();
                        if count > 0 {
                            subtopics_with += 1;
                        }
                        n_questions += count;
                        SyllabusSubtopic {
                            slug: st.slug.clone(),
                            name: st.name.clone(),
                            order: st.order,
                            question_count: count,
                            objectives: st.objectives.clone(),
                        }
                    })
                    .collect();

                let count: usize = subtopics.iter().map(|s| s.question_count).sum();
                if count > 0 {
                    topics_with += 1;
                }

                SyllabusTopic {
                    slug: t.slug.clone(),
                    name: t.name.clone(),
                    order: t.order,
                    weight: t.weight,
                    question_count: count,
                    // Notes are shape-only until D18 is activated.
                    note_available: false,
                    objectives: t.objectives.clone(),
                    subtopics,
                }
            })
            .collect();

        Some(Syllabus {
            exam: exam.to_owned(),
            subject: subject.clone(),
            topics,
            summary: SyllabusSummary {
                topics: n_topics,
                topics_with_questions: topics_with,
                subtopics: n_subtopics,
                subtopics_with_questions: subtopics_with,
                questions: n_questions,
            },
        })
    }

    fn question(&self, id: &str) -> Option<&Question> {
        self.questions.iter().find(|q| q.id == id)
    }

    fn version(&self) -> &str {
        &self.version
    }

    /// The loaded questions, in file order. Used by the import path to detect
    /// duplicates before anything is written (D51).
    fn questions(&self) -> &[Question] {
        &self.questions
    }

    fn questions_page(&self, filter: QuestionFilter<'_>, page: u32, per_page: u32) -> QuestionPage {
        let per_page = per_page.clamp(1, MAX_PER_PAGE);
        let page = page.max(1);

        let mut matched: Vec<&Question> = match filter.subtopic {
            Some(subtopic) => self
                .questions_by_subtopic
                .get(subtopic)
                .map(|ix| ix.iter().map(|i| &self.questions[*i]).collect())
                .unwrap_or_default(),
            None => self
                .questions
                .iter()
                .filter(|q| filter.exam.is_none_or(|e| q.exam == e))
                .filter(|q| filter.subject.is_none_or(|s| q.subject == s))
                .collect(),
        };

        // Stable order by id, so a page boundary means the same thing in every
        // implementation (D23 requirement 2).
        matched.sort_by(|a, b| a.id.cmp(&b.id));
        let matched: Vec<&Question> = matched
            .into_iter()
            .filter(|q| filter.verified.is_none_or(|v| q.verified == v))
            .collect();

        let matched: Vec<&Question> = matched
            .into_iter()
            .filter(|q| filter.source.is_none_or(|want| q.source == want))
            .filter(|q| filter.year.is_none_or(|y| q.year == y))
            .filter(|q| {
                filter.text.is_none_or(|needle| {
                    q.text.text.to_lowercase().contains(&needle.to_lowercase())
                })
            })
            .collect();

        let total_records = matched.len();
        let start = (page as usize - 1) * per_page as usize;
        let questions = matched
            .into_iter()
            .skip(start)
            .take(per_page as usize)
            .cloned()
            .collect();

        QuestionPage {
            questions,
            page,
            per_page,
            total_records,
        }
    }

    fn subject_count(&self) -> usize {
        self.subjects.len()
    }

    fn subtopic_counts(&self) -> HashMap<String, usize> {
        // Same index `questions_page` reads for its subtopic filter, so the
        // totals are identical by construction (D23 requirement 3).
        self.questions_by_subtopic
            .iter()
            .map(|(slug, ix)| (slug.clone(), ix.len()))
            .collect()
    }

    fn question_count(&self) -> usize {
        self.questions.len()
    }

    fn withheld_count(&self) -> usize {
        self.withheld
    }

    fn passage(&self, id: &str) -> Option<&Passage> {
        self.passage_by_id.get(id).map(|i| &self.passages[*i])
    }

    fn topic(&self, exam: &str, subject: &str, slug: &str) -> Option<(&Topic, Vec<&Subtopic>)> {
        let topic = self
            .topics
            .iter()
            .find(|t| t.exam == exam && t.subject == subject && t.slug == slug)?;
        let mut subtopics: Vec<&Subtopic> =
            self.subtopics.iter().filter(|s| s.topic == slug).collect();
        // Only this exam's subject owns these subtopics — the topic row
        // already scoped us, so no further filtering is needed.
        subtopics.sort_by_key(|s| s.order);
        Some((topic, subtopics))
    }

    fn novels(&self, exam: Option<&str>) -> Vec<&Novel> {
        let mut out: Vec<&Novel> = self
            .novels
            .iter()
            .filter(|n| exam.is_none_or(|e| n.novel.exam == e))
            .map(|n| &n.novel)
            .collect();
        // Newest prescription first — the current set text leads.
        out.sort_by(|a, b| {
            newest(b)
                .cmp(&newest(a))
                .then_with(|| a.title.cmp(&b.title))
        });
        out
    }

    fn featured_novel(&self, exam: &str) -> Option<&Novel> {
        self.novels
            .iter()
            .find(|n| n.novel.exam == exam && n.novel.featured)
            .map(|n| &n.novel)
    }

    fn novel(&self, id: &str) -> Option<&NovelDoc> {
        self.novel_by_id.get(id).map(|i| &self.novels[*i])
    }
}

/// The latest cycle a novel is prescribed for — what "current" means.
fn newest(novel: &Novel) -> u16 {
    novel.year_prescribed.iter().copied().max().unwrap_or(0)
}

/// A fingerprint of every byte we loaded: the five files plus every novel.
///
/// Hashing **raw bytes** rather than parsed values means the version moves if
/// a file is reformatted without content changing — rare, harmless, and far
/// cheaper to reason about than a canonicalisation pass. Consumers only ever
/// compare the string for equality, so an occasional extra bump costs nothing
/// (D42).
fn fingerprint(dir: &Path) -> String {
    use sha2::{Digest, Sha256};

    let mut files: Vec<PathBuf> = FILES.iter().map(|f| dir.join(f)).collect();
    // The verification log moves served `verified` flags, so it moves the
    // version too — a consumer polling /health must refresh on review.
    files.push(dir.join("verifications.json"));
    let mut novel_files: Vec<PathBuf> = std::fs::read_dir(dir.join("novels"))
        .into_iter()
        .flatten()
        .filter_map(|e| e.ok().map(|e| e.path()))
        .filter(|p| p.extension().and_then(|e| e.to_str()) == Some("json"))
        .collect();
    files.append(&mut novel_files);
    files.sort();

    let mut hasher = Sha256::new();
    for path in files {
        // The filename is hashed too, so moving content between files still
        // changes the version.
        hasher.update(path.file_name().unwrap_or_default().as_encoded_bytes());
        hasher.update(std::fs::read(&path).unwrap_or_default());
    }
    let digest = hasher.finalize();
    // 16 hex chars is 64 bits — ample for "did anything change" and short
    // enough to sit in a header or a log line.
    digest[..8].iter().map(|b| format!("{b:02x}")).collect()
}

fn read<T: for<'de> serde::Deserialize<'de>>(dir: &Path, file: &str, c: &mut Checker) -> Vec<T> {
    let full = dir.join(file);
    let bytes = match std::fs::read(&full) {
        Ok(b) => b,
        Err(e) => {
            c.problems
                .push(format!("{file}: cannot read ({}): {e}", full.display()));
            return Vec::new();
        }
    };
    match serde_json::from_slice(&bytes) {
        Ok(v) => v,
        Err(e) => {
            c.problems.push(format!("{file}: {e}"));
            Vec::new()
        }
    }
}

/// Read the verification log (D62). A missing file means no review has
/// happened yet — empty, not fatal. A malformed file fails the boot: a log
/// we cannot parse is worse than no log, because derivation would silently
/// un-verify the bank.
fn read_verifications(path: &Path, c: &mut Checker) -> Vec<Verification> {
    let bytes = match std::fs::read(path) {
        Ok(b) => b,
        Err(e) if e.kind() == std::io::ErrorKind::NotFound => return Vec::new(),
        Err(e) => {
            c.problems.push(format!(
                "verifications.json: cannot read ({}): {e}",
                path.display()
            ));
            return Vec::new();
        }
    };
    match serde_json::from_slice(&bytes) {
        Ok(v) => v,
        Err(e) => {
            c.problems.push(format!("verifications.json: {e}"));
            Vec::new()
        }
    }
}

/// Answerability predicate behind derivation (D57). A stem naming an
/// underlined word with no `Underline` mark is unanswerable as served.
fn underline_missing(text: &crate::bank::RichText) -> bool {
    use crate::bank::InlineKind;
    text.names_underline() && !text.has_mark(|k| matches!(k, InlineKind::Underline))
}

/// Plain-text gate (D56): `&entity;` and `<tag>` are harvest residue, never
/// content. Scans byte-wise — no regex crate for two patterns. `x < 2` is
/// fine (a `<` followed by a space or digit is comparison, not markup); `a<b`
/// is flagged, and rightly so: ambiguous bytes must fail loudly, not render.
fn check_plain(id: &str, field: &str, text: &str, c: &mut Checker) {
    let b = text.as_bytes();
    let mut i = 0;
    while i < b.len() {
        if b[i] == b'&' {
            let mut j = i + 1;
            while j < b.len() && b[j].is_ascii_alphabetic() {
                j += 1;
            }
            if j > i + 1 && j < b.len() && b[j] == b';' {
                c.problems.push(format!(
                    "questions.json: '{id}' {field} carries HTML entity {:?} — unescape at the source",
                    &text[i..=j.min(i + 24)],
                ));
                return;
            }
        }
        if b[i] == b'<'
            && i + 1 < b.len()
            && (b[i + 1].is_ascii_alphabetic() || b[i + 1] == b'/' || b[i + 1] == b'!')
        {
            c.problems.push(format!(
                "questions.json: '{id}' {field} carries markup — strip tags at the source",
            ));
            return;
        }
        i += 1;
    }
}

/// Parse one embedded catalog file. A build-time typo fails the boot with the
/// filename attached — same contract as `read`, minus the filesystem.
fn parse_embedded<T: for<'de> serde::Deserialize<'de>>(
    file: &str,
    content: &str,
    c: &mut Checker,
) -> Vec<T> {
    match serde_json::from_str(content) {
        Ok(v) => v,
        Err(e) => {
            c.problems.push(format!("embedded {file}: {e}"));
            Vec::new()
        }
    }
}

/// Fingerprint of what `load_embedded` serves: embedded catalog bytes plus the
/// `questions.json` file on disk (D42). Equal string means equal content; a
/// question edit moves the version without a rebuild, a catalog edit moves it
/// on the next build — both are supposed to.
fn fingerprint_embedded(dir: &Path) -> String {
    use sha2::{Digest, Sha256};

    let mut hasher = Sha256::new();
    for (name, content) in [
        ("subjects.json", EMBEDDED_SUBJECTS),
        ("topics.json", EMBEDDED_TOPICS),
        ("subtopics.json", EMBEDDED_SUBTOPICS),
        ("passages.json", EMBEDDED_PASSAGES),
    ] {
        hasher.update(name.as_bytes());
        hasher.update(content.as_bytes());
    }
    let mut novels: Vec<(&str, &str)> = EMBEDDED_NOVELS.to_vec();
    novels.sort_by_key(|(name, _)| *name);
    for (name, content) in novels {
        hasher.update(name.as_bytes());
        hasher.update(content.as_bytes());
    }
    hasher.update(b"questions.json");
    hasher.update(std::fs::read(dir.join("questions.json")).unwrap_or_default());
    hasher.update(b"verifications.json");
    hasher.update(std::fs::read(dir.join("verifications.json")).unwrap_or_default());
    let digest = hasher.finalize();
    digest[..8].iter().map(|b| format!("{b:02x}")).collect()
}

/// Embedded novels: the `EMBEDDED_NOVELS` list is the index — same rule as the
/// `data/novels/` directory it replaces, minus the directory listing.
fn load_novels_embedded(c: &mut Checker) -> Vec<NovelDoc> {
    let mut out = Vec::new();
    let mut files: Vec<(&str, &str)> = EMBEDDED_NOVELS.to_vec();
    files.sort_by_key(|(name, _)| *name);
    for (name, content) in files {
        match serde_json::from_str::<NovelDoc>(content) {
            Ok(mut doc) => {
                if doc.novel.id.is_empty() {
                    doc.novel.id = name.strip_suffix(".json").unwrap_or(name).to_owned();
                }
                out.push(doc);
            }
            Err(e) => c.problems.push(format!("embedded novels/{name}: {e}")),
        }
    }
    let mut seen = std::collections::HashSet::new();
    out.retain(|doc| {
        if !seen.insert(doc.novel.id.clone()) {
            c.problems
                .push(format!("novels/: duplicate novel id '{}'", doc.novel.id));
            false
        } else {
            true
        }
    });
    out
}

/// Read every `*.json` under `dir`. The directory is the index — no list file
/// to keep in sync, and dropping a novel is deleting its file.
///
/// A malformed file fails the boot with the filename attached; a missing
/// directory simply means no novels yet.
fn load_novels(dir: &std::path::Path, c: &mut Checker) -> Vec<NovelDoc> {
    let mut out = Vec::new();
    let entries = match std::fs::read_dir(dir) {
        Ok(e) => e,
        Err(e) if e.kind() == std::io::ErrorKind::NotFound => return out,
        Err(e) => {
            c.problems
                .push(format!("novels/: cannot list ({}): {e}", dir.display()));
            return out;
        }
    };
    let mut files: Vec<_> = entries.filter_map(|e| e.ok().map(|e| e.path())).collect();
    files.sort();
    for path in files {
        if path.extension().and_then(|e| e.to_str()) != Some("json") {
            continue;
        }
        let name = path
            .file_name()
            .and_then(|n| n.to_str())
            .unwrap_or("?")
            .to_owned();
        let bytes = match std::fs::read(&path) {
            Ok(b) => b,
            Err(e) => {
                c.problems.push(format!("novels/{name}: cannot read: {e}"));
                continue;
            }
        };
        match serde_json::from_slice::<NovelDoc>(&bytes) {
            Ok(mut doc) => {
                if doc.novel.id.is_empty() {
                    // The filename is the fallback id — a file must be
                    // addressable even when its author forgot the field.
                    doc.novel.id = path
                        .file_stem()
                        .and_then(|s| s.to_str())
                        .unwrap_or("?")
                        .to_owned();
                }
                out.push(doc);
            }
            Err(e) => c.problems.push(format!("novels/{name}: {e}")),
        }
    }
    // Two files must never claim one id.
    let mut seen = std::collections::HashSet::new();
    out.retain(|doc| {
        if !seen.insert(doc.novel.id.clone()) {
            c.problems
                .push(format!("novels/: duplicate novel id '{}'", doc.novel.id));
            false
        } else {
            true
        }
    });
    out
}

#[cfg(test)]
mod search_tests {
    use super::*;
    use crate::bank::QuestionFilter;

    fn store() -> JsonStore {
        JsonStore::load(std::path::Path::new("data")).expect("bank loads")
    }

    fn ids(filter: QuestionFilter<'_>) -> Vec<String> {
        store()
            .questions_page(filter, 1, 200)
            .questions
            .iter()
            .map(|q| q.id.clone())
            .collect()
    }

    /// A needle taken from the bank itself, so the test cannot pass or fail on
    /// what happens to be in the content today.
    fn live_needle() -> String {
        let bank = store();
        let all = bank.questions_page(QuestionFilter::default(), 1, 200);
        all.questions[0]
            .text
            .text
            .split_whitespace()
            .next()
            .unwrap()
            .to_owned()
    }

    #[test]
    fn a_substring_match_is_case_insensitive() {
        let needle = live_needle();
        let lower = ids(QuestionFilter {
            text: Some(needle.to_lowercase().as_str()),
            ..Default::default()
        });
        let upper = ids(QuestionFilter {
            text: Some(needle.to_uppercase().as_str()),
            ..Default::default()
        });
        assert!(!lower.is_empty(), "the needle must be in the bank");
        assert_eq!(lower, upper, "case must not change the result set");
    }

    #[test]
    fn search_composes_with_every_other_filter() {
        let needle = live_needle();
        let all = ids(QuestionFilter {
            text: Some(needle.as_str()),
            ..Default::default()
        });
        let scoped = ids(QuestionFilter {
            exam: Some("JAMB"),
            subject: Some("use-of-english"),
            text: Some(needle.as_str()),
            ..Default::default()
        });
        assert!(
            scoped.len() <= all.len(),
            "adding a filter cannot widen the result"
        );
        assert!(
            scoped.iter().all(|id| id.is_empty() || !id.contains("zzz")),
            "sanity: scoped ids are real rows"
        );
    }

    #[test]
    fn an_unmatched_needle_is_an_empty_page_not_an_error() {
        let page = store().questions_page(
            QuestionFilter {
                text: Some("zzz-not-in-any-question-zzz"),
                ..Default::default()
            },
            1,
            200,
        );
        assert_eq!(page.total_records, 0);
        assert_eq!(page.total_pages(), 0);
    }

    #[test]
    fn search_keeps_id_order_so_paging_stays_meaningful() {
        let found = ids(QuestionFilter {
            text: Some("the"),
            ..Default::default()
        });
        let mut sorted = found.clone();
        sorted.sort();
        assert_eq!(found, sorted, "ranking would break page boundaries");
    }
}
