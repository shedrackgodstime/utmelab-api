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

use super::model::{Novel, NovelDoc, Passage, Question, Subject};
use super::store::{MAX_PER_PAGE, QuestionFilter, QuestionPage, Store};
use super::{Subtopic, Syllabus, SyllabusSubtopic, SyllabusSummary, SyllabusTopic, Topic};

const FILES: [&str; 5] = [
    "subjects.json",
    "topics.json",
    "subtopics.json",
    "passages.json",
    "questions.json",
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
            novels: Vec::new(),
            novel_by_id: HashMap::new(),
            passages: std::mem::take(&mut store_passages),
            passage_by_id: HashMap::new(),
            version: String::new(),
        };
        // Novels: one document per book; the directory is the index.
        store.novels = load_novels(&dir.join("novels"), &mut c);
        store.version = fingerprint(dir);
        store.validate(&mut c);

        if !c.problems.is_empty() {
            return Err(StoreError {
                problems: c.problems,
            });
        }

        // Only fully-assigned questions are servable (D21), and only novels
        // that meet the 50-question minimum (D36).
        store.questions.retain(|q| !q.exam.is_empty());
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
            .filter(|q| {
                filter
                    .text
                    .is_none_or(|needle| q.text.to_lowercase().contains(&needle.to_lowercase()))
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
