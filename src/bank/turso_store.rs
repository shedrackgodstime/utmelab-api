//! Turso-backed `Store` (read path, R5/R8).
//!
//! Single source of truth is Turso; JSON is dev-only. This store loads every
//! table once in [`TursoStore::open`] and builds the exact same in-memory
//! representation `JsonStore` uses, through the shared
//! [`JsonStore::from_parts`] pipeline — validation, partition, verified
//! derivation, indices. One pipeline means the two stores cannot diverge in
//! behavior, only in where the bytes came from.
//!
//! Every `Store` method below delegates to the inner `JsonStore`, so serving
//! semantics (paging, absence rules, D16/D21/D57) are identical by
//! construction. `verified` is derived at read by the shared
//! `human_verified()` (R5) — never a stored flag. No per-request DB hits:
//! the tables are read once at startup (the cache the roadmap asks for).
//!
//! Known gaps until later phases: withheld rows stay file-side (Phase 2
//! record — `withheld_count` reads 0 here); `version()` is a count-hash,
//! not the full R7 row-hash (contract is string equality).

use crate::bank::StoreParts;
use crate::bank::Syllabus;
use crate::bank::json::JsonStore;
use crate::bank::model::{
    Choice, Country, Exam, Explanation, Novel, NovelChapter, NovelCharacter, NovelDoc,
    NovelQuestion, NovelTheme, Passage, Question, Requirement, RichText, Subject, Subtopic, Topic,
};
use crate::bank::store::{QuestionFilter, QuestionPage, Store};
use crate::db::Db;
use crate::error::ApiError;
use sha2::{Digest, Sha256};

pub struct TursoStore {
    inner: JsonStore,
}

fn internal(ctx: &str, e: impl std::fmt::Display) -> ApiError {
    ApiError::Internal(format!("turso store {ctx}: {e}"))
}

async fn all<T, F>(db: &Db, sql: &str, ctx: &str, mut f: F) -> Result<Vec<T>, ApiError>
where
    F: FnMut(&turso_serverless::Row) -> Result<T, ApiError>,
{
    let mut q = db
        .conn()
        .query(sql, ())
        .await
        .map_err(|e| internal(ctx, e))?;
    let mut out = Vec::new();
    while let Some(r) = q.next().await.map_err(|e| internal(ctx, e))? {
        out.push(f(&r)?);
    }
    Ok(out)
}

fn get<T>(r: &turso_serverless::Row, i: usize, ctx: &str) -> Result<T, ApiError>
where
    T: turso_serverless::value::FromValue,
{
    r.get(i).map_err(|e| internal(ctx, e))
}

fn opt_string(r: &turso_serverless::Row, i: usize, ctx: &str) -> Result<Option<String>, ApiError> {
    r.get::<Option<String>>(i).map_err(|e| internal(ctx, e))
}

fn json_col<T>(r: &turso_serverless::Row, i: usize, ctx: &str) -> Result<T, ApiError>
where
    T: serde::de::DeserializeOwned,
{
    let s: String = get(r, i, ctx)?;
    serde_json::from_str(&s).map_err(|e| internal(ctx, e))
}

impl TursoStore {
    /// Load every table, validate through the shared pipeline, index.
    /// Fail-closed: any validation problem aborts startup, same as files.
    pub async fn open(db: Db) -> Result<Self, ApiError> {
        let exams = all(&db, "SELECT code,name,countries,status,has_full_paper,subjects_required,duration_minutes,rules FROM exams", "exams", |r| {
            let status: String = get(r, 3, "exam.status")?;
            Ok(Exam {
                code: get(r, 0, "exam.code")?,
                name: get(r, 1, "exam.name")?,
                countries: json_col(r, 2, "exam.countries")?,
                status: serde_json::from_str(&format!("\"{status}\""))
                    .map_err(|e| internal("exam.status", e))?,
                has_full_paper: {
                    let v: Option<i64> = opt_string(r, 4, "exam.hfp")?.map(|_| 0);
                    let _ = v;
                    get::<Option<i64>>(r, 4, "exam.hfp")?.map(|x| x != 0)
                },
                subjects_required: get::<Option<i64>>(r, 5, "exam.sr")?.map(|x| x as u32),
                duration_minutes: get::<Option<i64>>(r, 6, "exam.dm")?.map(|x| x as u32),
                rules: json_col(r, 7, "exam.rules")?,
            })
        })
        .await?;

        let countries = all(&db, "SELECT code,name FROM countries", "countries", |r| {
            Ok(Country {
                code: get(r, 0, "country.code")?,
                name: get(r, 1, "country.name")?,
            })
        })
        .await?;

        let subjects = all(
            &db,
            "SELECT slug,exam,name,is_compulsory,objective_paper_questions FROM subjects",
            "subjects",
            |r| {
                Ok(Subject {
                    slug: get(r, 0, "subject.slug")?,
                    exam: get(r, 1, "subject.exam")?,
                    name: get(r, 2, "subject.name")?,
                    is_compulsory: get::<i64>(r, 3, "subject.comp")? != 0,
                    objective_paper_questions: get::<Option<i64>>(r, 4, "subject.opq")?
                        .map(|x| x as u32),
                })
            },
        )
        .await?;

        let topics = all(
            &db,
            "SELECT slug,subject,exam,name,\"order\",weight,objectives FROM topics",
            "topics",
            |r| {
                Ok(Topic {
                    slug: get(r, 0, "topic.slug")?,
                    subject: get(r, 1, "topic.subject")?,
                    exam: get(r, 2, "topic.exam")?,
                    name: get(r, 3, "topic.name")?,
                    order: get::<i64>(r, 4, "topic.order")? as u32,
                    weight: get::<i64>(r, 5, "topic.weight")? as u32,
                    objectives: json_col(r, 6, "topic.objectives")?,
                })
            },
        )
        .await?;

        let subtopics = all(
            &db,
            "SELECT slug,topic,name,\"order\",objectives FROM subtopics",
            "subtopics",
            |r| {
                Ok(Subtopic {
                    slug: get(r, 0, "sub.slug")?,
                    topic: get(r, 1, "sub.topic")?,
                    name: get(r, 2, "sub.name")?,
                    order: get::<i64>(r, 3, "sub.order")? as u32,
                    objectives: json_col(r, 4, "sub.objectives")?,
                })
            },
        )
        .await?;

        let questions = all(
            &db,
            "SELECT id,exam,subject,year,source,text,inline,options,answer,subtopic_id,section,passage_id,explanation,marks,difficulty FROM questions ORDER BY id",
            "questions",
            |r| {
                let inline: String = get(r, 6, "q.inline")?;
                let options: String = get(r, 7, "q.options")?;
                Ok(Question {
                    id: get(r, 0, "q.id")?,
                    exam: get(r, 1, "q.exam")?,
                    subject: get(r, 2, "q.subject")?,
                    year: {
                        let y: i64 = get(r, 3, "q.year")?;
                        y as u16
                    },
                    source: get(r, 4, "q.source")?,
                    text: RichText {
                        text: get(r, 5, "q.text")?,
                        inline: serde_json::from_str(&inline)
                            .map_err(|e| internal("q.inline", e))?,
                    },
                    options: serde_json::from_str::<Vec<Choice>>(&options)
                        .map_err(|e| internal("q.options", e))?,
                    answer: get(r, 8, "q.answer")?,
                    subtopic_id: opt_string(r, 9, "q.subtopic")?,
                    section: opt_string(r, 10, "q.section")?,
                    passage_id: opt_string(r, 11, "q.passage")?,
                    explanation: opt_string(r, 12, "q.expl")?
                        .map(|s| {
                            serde_json::from_str::<Explanation>(&s)
                                .map_err(|e| internal("q.expl-json", e))
                        })
                        .transpose()?,
                    marks: {
                        let m: f64 = get(r, 13, "q.marks")?;
                        m as f32
                    },
                    difficulty: {
                        let d: i64 = get(r, 14, "q.diff")?;
                        d as u8
                    },
                    verified: false,
                })
            },
        )
        .await?;

        let requirements = all(
            &db,
            "SELECT exam,country,\"group\",min_select,subjects FROM exam_requirements",
            "requirements",
            |r| {
                Ok(Requirement {
                    exam: get(r, 0, "req.exam")?,
                    country: get(r, 1, "req.country")?,
                    group: get(r, 2, "req.group")?,
                    min_select: {
                        let m: i64 = get(r, 3, "req.min")?;
                        m as u32
                    },
                    subjects: json_col(r, 4, "req.subjects")?,
                })
            },
        )
        .await?;

        let scope_pairs = all(
            &db,
            "SELECT topic,country FROM topic_countries ORDER BY topic,country",
            "scope",
            |r| {
                let t: String = get(r, 0, "scope.topic")?;
                let c: String = get(r, 1, "scope.country")?;
                Ok((t, c))
            },
        )
        .await?;
        let mut scope_map: std::collections::HashMap<String, Vec<String>> =
            std::collections::HashMap::new();
        for (t, c) in scope_pairs {
            scope_map.entry(t).or_default().push(c);
        }
        let scope: Vec<(String, Vec<String>)> = scope_map.into_iter().collect();

        let verifications = all(
            &db,
            "SELECT id,question_id,kind,verdict,scope,verifier,detail,content_hash,created_at FROM verifications",
            "verifications",
            |r| {
                let kind: String = get(r, 2, "v.kind")?;
                let verdict: String = get(r, 3, "v.verdict")?;
                let scope: String = get(r, 4, "v.scope")?;
                let detail: Option<String> = opt_string(r, 6, "v.detail")?;
                serde_json::from_value::<crate::bank::model::Verification>(serde_json::json!({
                    "id": get::<String>(r, 0, "v.id")?,
                    "question_id": get::<String>(r, 1, "v.qid")?,
                    "kind": serde_json::from_str::<serde_json::Value>(&format!("\"{kind}\"")).unwrap(),
                    "verdict": serde_json::from_str::<serde_json::Value>(&format!("\"{verdict}\"")).unwrap(),
                    "scope": serde_json::from_str::<serde_json::Value>(&scope).unwrap(),
                    "verifier": get::<String>(r, 5, "v.verifier")?,
                    "detail": detail,
                    "content_hash": get::<String>(r, 7, "v.hash")?,
                    "created_at": get::<String>(r, 8, "v.at")?,
                }))
                .map_err(|e| internal("v.parse", e))
            },
        )
        .await?;

        let novels = Self::load_novels(&db).await?;
        let passages = all(
            &db,
            "SELECT id,exam,subject,year,kind,title,author,text,inline FROM passages",
            "passages",
            |r| {
                let inline: String = get(r, 8, "p.inline")?;
                Ok(Passage {
                    id: get(r, 0, "p.id")?,
                    exam: get(r, 1, "p.exam")?,
                    subject: get(r, 2, "p.subject")?,
                    year: {
                        let y: i64 = get(r, 3, "p.year")?;
                        y as u16
                    },
                    kind: get(r, 4, "p.kind")?,
                    title: opt_string(r, 5, "p.title")?,
                    author: opt_string(r, 6, "p.author")?,
                    text: RichText {
                        text: get(r, 7, "p.text")?,
                        inline: serde_json::from_str(&inline)
                            .map_err(|e| internal("p.inline", e))?,
                    },
                })
            },
        )
        .await?;

        let version = Self::compute_version(&db).await?;

        let inner = JsonStore::from_parts(StoreParts {
            exams,
            countries,
            subjects,
            topics,
            subtopics,
            questions,
            requirements,
            scope,
            verifications,
            novels,
            passages,
            withheld_questions: Vec::new(),
            withheld_notes: 0,
            version,
        })
        .map_err(|e| ApiError::Internal(format!("turso store validate: {e:?}")))?;
        Ok(Self { inner })
    }

    async fn load_novels(db: &Db) -> Result<Vec<crate::bank::model::NovelDoc>, ApiError> {
        let docs = all(
            db,
            "SELECT id,title,author,year_published,exam,year_prescribed,category,featured,synopsis,setting_place,setting_period,cover_image FROM novels",
            "novels",
            |r| {
                Ok((
                    get::<String>(r, 0, "n.id")?,
                    get::<String>(r, 1, "n.title")?,
                    get::<String>(r, 2, "n.author")?,
                    get::<Option<i64>>(r, 3, "n.yp")?,
                    get::<String>(r, 4, "n.exam")?,
                    get::<String>(r, 5, "n.ypres")?,
                    get::<String>(r, 6, "n.cat")?,
                    get::<i64>(r, 7, "n.feat")?,
                    get::<String>(r, 8, "n.syn")?,
                    get::<String>(r, 9, "n.sp")?,
                    get::<String>(r, 10, "n.st")?,
                    opt_string(r, 11, "n.cover")?,
                ))
            },
        )
        .await?;
        let mut out = Vec::new();
        for (
            id,
            title,
            author,
            year_published,
            exam,
            year_prescribed,
            category,
            featured,
            synopsis,
            setting_place,
            setting_period,
            cover_image,
        ) in docs
        {
            out.push((
                id,
                title,
                author,
                year_published,
                exam,
                year_prescribed,
                category,
                featured,
                synopsis,
                setting_place,
                setting_period,
                cover_image,
            ));
        }
        // Assemble docs with a second pass (keeps borrow scopes simple).
        let mut novels = Vec::new();
        for (
            id,
            title,
            author,
            year_published,
            exam,
            year_prescribed,
            category,
            featured,
            synopsis,
            setting_place,
            setting_period,
            cover_image,
        ) in out
        {
            let chapters = Self::chapters_for(db, &id).await?;
            let characters = Self::characters_for(db, &id).await?;
            let themes = Self::themes_for(db, &id).await?;
            let questions = Self::novel_questions_for(db, &id).await?;
            novels.push(NovelDoc {
                novel: Novel {
                    id: id.clone(),
                    title,
                    author,
                    year_published: year_published.map(|y| y as u16),
                    exam,
                    year_prescribed: serde_json::from_str(&year_prescribed)
                        .map_err(|e| internal("n.ypres", e))?,
                    category,
                    featured: featured != 0,
                    synopsis,
                    setting_place,
                    setting_period,
                    cover_image,
                },
                chapters,
                characters,
                themes,
                questions,
            });
        }
        Ok(novels)
    }

    async fn chapters_for(db: &Db, novel_id: &str) -> Result<Vec<NovelChapter>, ApiError> {
        let mut q = db
            .conn()
            .query(
                "SELECT number,title,summary,key_events FROM novel_chapters WHERE novel_id = ?1 ORDER BY number",
                (novel_id,),
            )
            .await
            .map_err(|e| internal("chapters", e))?;
        let mut v = Vec::new();
        while let Some(r) = q.next().await.map_err(|e| internal("chapters", e))? {
            let n: i64 = get(&r, 0, "c.num")?;
            v.push(NovelChapter {
                number: n as u8,
                title: get(&r, 1, "c.title")?,
                summary: opt_string(&r, 2, "c.summary")?,
                key_events: json_col(&r, 3, "c.ke")?,
            });
        }
        Ok(v)
    }

    async fn characters_for(db: &Db, novel_id: &str) -> Result<Vec<NovelCharacter>, ApiError> {
        let mut q = db
            .conn()
            .query(
                "SELECT name,role,character_type,description FROM novel_characters WHERE novel_id = ?1 ORDER BY name",
                (novel_id,),
            )
            .await
            .map_err(|e| internal("characters", e))?;
        let mut v = Vec::new();
        while let Some(r) = q.next().await.map_err(|e| internal("characters", e))? {
            v.push(NovelCharacter {
                name: get(&r, 0, "ch.name")?,
                role: get(&r, 1, "ch.role")?,
                character_type: get(&r, 2, "ch.type")?,
                description: get(&r, 3, "ch.desc")?,
            });
        }
        Ok(v)
    }

    async fn themes_for(db: &Db, novel_id: &str) -> Result<Vec<NovelTheme>, ApiError> {
        let mut q = db
            .conn()
            .query(
                "SELECT name,description,evidence FROM novel_themes WHERE novel_id = ?1 ORDER BY name",
                (novel_id,),
            )
            .await
            .map_err(|e| internal("themes", e))?;
        let mut v = Vec::new();
        while let Some(r) = q.next().await.map_err(|e| internal("themes", e))? {
            v.push(NovelTheme {
                name: get(&r, 0, "t.name")?,
                description: get(&r, 1, "t.desc")?,
                evidence: json_col(&r, 2, "t.ev")?,
            });
        }
        Ok(v)
    }

    async fn novel_questions_for(db: &Db, novel_id: &str) -> Result<Vec<NovelQuestion>, ApiError> {
        let mut q = db
            .conn()
            .query(
                "SELECT id,chapter_number,text,inline,options,answer,explanation FROM novel_questions WHERE novel_id = ?1 ORDER BY id",
                (novel_id,),
            )
            .await
            .map_err(|e| internal("nq", e))?;
        let mut v = Vec::new();
        while let Some(r) = q.next().await.map_err(|e| internal("nq", e))? {
            let inline: String = get(&r, 3, "nq.inline")?;
            let options: String = get(&r, 4, "nq.options")?;
            v.push(NovelQuestion {
                id: get(&r, 0, "nq.id")?,
                chapter_number: get::<Option<i64>>(&r, 1, "nq.ch")
                    .map(|o| o.map(|x| x as u8))
                    .unwrap_or(None),
                text: RichText {
                    text: get(&r, 2, "nq.text")?,
                    inline: serde_json::from_str(&inline).map_err(|e| internal("nq.inline", e))?,
                },
                options: serde_json::from_str::<Vec<Choice>>(&options)
                    .map_err(|e| internal("nq.options", e))?,
                answer: get(&r, 5, "nq.answer")?,
                explanation: opt_string(&r, 6, "nq.expl")?
                    .map(|s| {
                        serde_json::from_str::<Explanation>(&s)
                            .map_err(|e| internal("nq.expl-json", e))
                    })
                    .transpose()?,
                verified: false,
            });
        }
        Ok(v)
    }

    async fn compute_version(db: &Db) -> Result<String, ApiError> {
        // R7 draft: 16-hex SHA over per-table counts. The contract is string
        // equality; the full row-hash version lands with the cutover.
        let mut hasher = Sha256::new();
        for table in [
            "verifications",
            "questions",
            "passages",
            "novels",
            "novel_questions",
            "subjects",
            "exams",
            "topics",
            "subtopics",
            "countries",
            "topic_countries",
            "exam_requirements",
            "blueprints",
        ] {
            let sql = format!("SELECT COUNT(*) FROM {table}");
            let mut q = db
                .conn()
                .query(&sql, ())
                .await
                .map_err(|e| internal("version", e))?;
            let n: i64 = q
                .next()
                .await
                .map_err(|e| internal("version", e))?
                .map(|r| r.get(0).unwrap_or(0))
                .unwrap_or(0);
            hasher.update(table.as_bytes());
            hasher.update(n.to_le_bytes());
        }
        Ok(format!("{:x}", hasher.finalize())[..16].to_string())
    }
}

impl Store for TursoStore {
    fn questions(&self) -> &[Question] {
        self.inner.questions()
    }
    fn version(&self) -> &str {
        self.inner.version()
    }
    fn exams(&self) -> Vec<&str> {
        self.inner.exams()
    }
    fn exam(&self, code: &str) -> Option<&Exam> {
        self.inner.exam(code)
    }
    fn topic_scope(&self, topic: &str) -> Vec<String> {
        self.inner.topic_scope(topic)
    }
    fn requirements(&self, exam: &str, country: &str) -> Vec<&Requirement> {
        self.inner.requirements(exam, country)
    }
    fn subjects(&self, exam: &str) -> Vec<&Subject> {
        self.inner.subjects(exam)
    }
    fn subject(&self, exam: &str, slug: &str) -> Option<&Subject> {
        self.inner.subject(exam, slug)
    }
    fn syllabus(&self, exam: &str, subject_slug: &str, country: Option<&str>) -> Option<Syllabus> {
        self.inner.syllabus(exam, subject_slug, country)
    }
    fn question(&self, id: &str) -> Option<&Question> {
        self.inner.question(id)
    }
    fn questions_page(&self, filter: QuestionFilter<'_>, page: u32, per_page: u32) -> QuestionPage {
        self.inner.questions_page(filter, page, per_page)
    }
    fn subject_count(&self) -> usize {
        self.inner.subject_count()
    }
    fn question_count(&self) -> usize {
        self.inner.question_count()
    }
    fn subtopic_counts(&self) -> std::collections::HashMap<String, usize> {
        self.inner.subtopic_counts()
    }
    fn withheld_count(&self) -> usize {
        self.inner.withheld_count()
    }
    fn passage(&self, id: &str) -> Option<&Passage> {
        self.inner.passage(id)
    }
    fn topic(&self, exam: &str, subject: &str, slug: &str) -> Option<(&Topic, Vec<&Subtopic>)> {
        self.inner.topic(exam, subject, slug)
    }
    fn novels(&self, exam: Option<&str>) -> Vec<&Novel> {
        self.inner.novels(exam)
    }
    fn featured_novel(&self, exam: &str) -> Option<&Novel> {
        self.inner.featured_novel(exam)
    }
    fn novel(&self, id: &str) -> Option<&NovelDoc> {
        self.inner.novel(id)
    }
}
