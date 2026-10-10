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

use super::model::{Question, Subject};
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
}

impl JsonStore {
    pub fn load(dir: impl AsRef<Path>) -> Result<Self, StoreError> {
        let dir = dir.as_ref();
        let mut c = Checker::default();

        let subjects: Vec<Subject> = read(dir, FILES[0], &mut c);
        let topics: Vec<Topic> = read(dir, FILES[1], &mut c);
        let subtopics: Vec<Subtopic> = read(dir, FILES[2], &mut c);
        // Passages are read only so a malformed file still fails the boot.
        let _: Vec<super::model::Passage> = read(dir, FILES[3], &mut c);
        let questions: Vec<Question> = read(dir, FILES[4], &mut c);

        if !c.problems.is_empty() {
            return Err(StoreError {
                problems: c.problems,
            });
        }

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
        };
        store.validate(&mut c);

        if !c.problems.is_empty() {
            return Err(StoreError {
                problems: c.problems,
            });
        }

        // Only fully-assigned questions are servable (D21).
        store.questions.retain(|q| !q.exam.is_empty());
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
