//! The textbook surface: books, chapters, sections and exercises.
//!
//! These routes carry the teaching half of the platform. The exam half
//! (traps and practice written in an exam's wording) hangs off the same
//! chapter sections, and the exam pack joins the two.

use axum::{
    extract::{Path, Query, State},
    routing::get,
    Json, Router,
};

use serde::Deserialize;

use crate::{
    auth::{api_key::AuthedKey, SCOPE_READ_CATALOG},
    core,
    error::AppError,
    state::{AppState, DbState},
    store,
};

#[utoipa::path(
    get,
    path = "/api/v1/textbooks",
    tag = "textbook",
    operation_id = "listTextbooks",
    summary = "Every book, with the subject area and the level it teaches.",
    responses(
        (status = 200, body = Vec<crate::core::models::Book>),
        core::models::ApiErrorResponses,
    ),
)]
pub async fn list_textbooks(
    State(s): State<DbState>,
    AuthedKey(auth): AuthedKey,
) -> Result<Json<Vec<crate::core::models::Book>>, AppError> {
    auth.require(SCOPE_READ_CATALOG)?;
    Ok(Json(store::chapters::list_books(&s).await?))
}

#[utoipa::path(
    get,
    path = "/api/v1/textbooks/{book_id}",
    tag = "textbook",
    operation_id = "getTextbook",
    summary = "One book and the chapters it holds.",
    params(("book_id" = String, Path, description = "Book id, e.g. `secondary_physics`.")),
    responses(
        (status = 200, body = crate::core::models::BookWithChapters),
        (status = 404, description = "No book with that id", body = crate::core::models::ErrorResponse),
        core::models::ApiErrorResponses,
    ),
)]
pub async fn get_textbook(
    State(s): State<DbState>,
    AuthedKey(auth): AuthedKey,
    Path(book_id): Path<String>,
) -> Result<Json<crate::core::models::BookWithChapters>, AppError> {
    auth.require(SCOPE_READ_CATALOG)?;
    let Some((book, chapters)) = store::chapters::get_book(&s, &book_id).await? else {
        return Err(AppError::NotFound);
    };
    Ok(Json(crate::core::models::BookWithChapters {
        id: book.id,
        title: book.title,
        subject_area: book.subject_area,
        level: book.level,
        edition: book.edition,
        description: book.description,
        parts: book.parts,
        chapters,
    }))
}

#[utoipa::path(
    get,
    path = "/api/v1/chapters/{chapter_id}",
    tag = "textbook",
    operation_id = "getChapter",
    summary = "One chapter: its outline, learning objectives, and section index.",
    params(("chapter_id" = String, Path, description = "Chapter id, e.g. `phy_forces_and_newtons_laws`.")),
    responses(
        (status = 200, body = crate::core::models::ChapterOutline),
        (status = 404, description = "No chapter with that id", body = crate::core::models::ErrorResponse),
        core::models::ApiErrorResponses,
    ),
)]
pub async fn get_chapter(
    State(s): State<DbState>,
    AuthedKey(auth): AuthedKey,
    Path(chapter_id): Path<String>,
) -> Result<Json<crate::core::models::ChapterOutline>, AppError> {
    auth.require(SCOPE_READ_CATALOG)?;
    let Some(chapter) = store::chapters::get_chapter(&s, &chapter_id).await? else {
        return Err(AppError::NotFound);
    };
    let mut outline = core::catalog::chapter_to_outline(&chapter)?;
    core::catalog::resolve_chapter_outline(&mut outline, s.media_base_url.as_ref());
    Ok(Json(outline))
}

#[utoipa::path(
    get,
    path = "/api/v1/chapters/{chapter_id}/sections/{section_id}",
    tag = "textbook",
    operation_id = "getSectionDetail",
    summary = "Fully structured teaching content for one section of a chapter.",
    params(
        ("chapter_id" = String, Path, description = "Chapter id, e.g. `phy_forces_and_newtons_laws`."),
        ("section_id" = String, Path, description = "Section id, e.g. `sec-1` or `sec-2`."),
    ),
    responses(
        (status = 200, body = crate::core::models::SectionDetail),
        (status = 404, description = "No section with that id in this chapter", body = crate::core::models::ErrorResponse),
        core::models::ApiErrorResponses,
    ),
)]
pub async fn get_section_detail(
    State(s): State<DbState>,
    AuthedKey(auth): AuthedKey,
    Path((chapter_id, section_id)): Path<(String, String)>,
) -> Result<Json<crate::core::models::SectionDetail>, AppError> {
    auth.require(SCOPE_READ_CATALOG)?;
    let Some(sec) = store::chapters::get_section(&s, &chapter_id, &section_id).await? else {
        return Err(AppError::NotFound);
    };
    let mut detail = core::catalog::section_to_detail(&chapter_id, 2, &sec)?;
    core::catalog::resolve_section_detail(&mut detail, s.media_base_url.as_ref());
    Ok(Json(detail))
}

/// Narrow an exercise list to a section or a tier.
#[derive(Clone, Debug, Default, Deserialize, utoipa::IntoParams)]
pub struct ExerciseQuery {
    /// Only the exercises of this section.
    pub section_id: Option<String>,
    /// Only the exercises of this tier: `warm_up`, `core` or `stretch`.
    pub tier: Option<String>,
}

#[utoipa::path(
    get,
    path = "/api/v1/chapters/{chapter_id}/exercises",
    tag = "textbook",
    operation_id = "listChapterExercises",
    summary = "The exercises of a chapter, each with its answer and its solution.",
    params(
        ("chapter_id" = String, Path, description = "Chapter id."),
        ExerciseQuery,
    ),
    responses(
        (status = 200, body = Vec<crate::core::models::ChapterExercise>),
        core::models::ApiErrorResponses,
    ),
)]
pub async fn list_chapter_exercises(
    State(s): State<DbState>,
    AuthedKey(auth): AuthedKey,
    Path(chapter_id): Path<String>,
    Query(query): Query<ExerciseQuery>,
) -> Result<Json<Vec<crate::core::models::ChapterExercise>>, AppError> {
    auth.require(SCOPE_READ_CATALOG)?;
    let mut exercises = store::chapters::list_exercises(
        &s,
        &chapter_id,
        query.section_id.as_deref(),
        query.tier.as_deref(),
    )
    .await?;
    for ex in &mut exercises {
        core::catalog::resolve_exercise(ex, s.media_base_url.as_ref());
    }
    Ok(Json(exercises))
}

/// Narrow a trap list to an exam or a section.
#[derive(Clone, Debug, Default, Deserialize, utoipa::IntoParams)]
pub struct TrapQuery {
    /// Only the traps of this exam, e.g. `JAMB`.
    pub exam: Option<String>,
    /// Only the traps of this section.
    pub section_id: Option<String>,
}

#[utoipa::path(
    get,
    path = "/api/v1/exam-traps",
    tag = "textbook",
    operation_id = "listExamTraps",
    summary = "The mistakes candidates make, with the evidence behind each one.",
    params(TrapQuery),
    responses(
        (status = 200, body = Vec<crate::core::models::ExamTrap>),
        core::models::ApiErrorResponses,
    ),
)]
pub async fn list_exam_traps(
    State(s): State<DbState>,
    AuthedKey(auth): AuthedKey,
    Query(query): Query<TrapQuery>,
) -> Result<Json<Vec<crate::core::models::ExamTrap>>, AppError> {
    auth.require(SCOPE_READ_CATALOG)?;
    let mut traps =
        store::chapters::list_traps(&s, query.exam.as_deref(), query.section_id.as_deref()).await?;
    for trap in &mut traps {
        core::catalog::resolve_trap(trap, s.media_base_url.as_ref());
    }
    Ok(Json(traps))
}

/// Narrow a practice list to an exam or a section.
#[derive(Clone, Debug, Default, Deserialize, utoipa::IntoParams)]
pub struct RecallQuery {
    /// Only the practice items of this exam, e.g. `WAEC`.
    pub exam: Option<String>,
    /// Only the practice items of this section.
    pub section_id: Option<String>,
}

#[utoipa::path(
    get,
    path = "/api/v1/exam-practice",
    tag = "textbook",
    operation_id = "listExamPractice",
    summary = "Practice items written in an exam's own wording.",
    params(RecallQuery),
    responses(
        (status = 200, body = Vec<crate::core::models::ExamRecallCheck>),
        core::models::ApiErrorResponses,
    ),
)]
pub async fn list_exam_practice(
    State(s): State<DbState>,
    AuthedKey(auth): AuthedKey,
    Query(query): Query<RecallQuery>,
) -> Result<Json<Vec<crate::core::models::ExamRecallCheck>>, AppError> {
    auth.require(SCOPE_READ_CATALOG)?;
    let mut checks =
        store::chapters::list_recall_checks(&s, query.exam.as_deref(), query.section_id.as_deref())
            .await?;
    for check in &mut checks {
        core::catalog::resolve_recall_check(check, s.media_base_url.as_ref());
    }
    Ok(Json(checks))
}

pub fn router(state: AppState) -> Router<AppState> {
    Router::new()
        .route("/v1/textbooks", get(list_textbooks))
        .route("/v1/textbooks/{book_id}", get(get_textbook))
        .route("/v1/chapters/{chapter_id}", get(get_chapter))
        .route(
            "/v1/chapters/{chapter_id}/sections/{section_id}",
            get(get_section_detail),
        )
        .route(
            "/v1/chapters/{chapter_id}/exercises",
            get(list_chapter_exercises),
        )
        .route("/v1/exam-traps", get(list_exam_traps))
        .route("/v1/exam-practice", get(list_exam_practice))
        .with_state(state)
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::{
        core::models::{
            Book, BookPart, Chapter, ChapterExercise, ChapterSection, Choice, ContentBlock,
            ExampleTitle, ExerciseHint, ExerciseOption, ExerciseSolutionStep, FormulaSheetEntry,
            GlossaryEntry, ImagePosition, LearningObjective, PaperEvidence, Provenance, RichText,
            SectionMisconception, SectionWorkedExample, TableCell, TeachingTextContainer,
            WorkedStep,
        },
        testing::{api_schema, call, connect, issue_key, replica, state},
    };
    use axum::http::StatusCode;

    fn sample_book() -> Book {
        Book {
            id: "secondary_physics".into(),
            title: "Secondary Physics".into(),
            subject_area: "physics".into(),
            level: "secondary".into(),
            edition: "draft-1".into(),
            description: "Complete physics curriculum.".into(),
            parts: vec![BookPart {
                id: "part-1".into(),
                order: 1,
                title: "Mechanics".into(),
            }],
            sources: vec![Provenance {
                publisher: "OpenStax".into(),
                title: "College Physics 2e".into(),
                url: "https://openstax.org".into(),
                locator: "Section 1".into(),
                licence: "CC BY 4.0".into(),
            }],
        }
    }

    fn sample_blocks() -> Vec<ContentBlock> {
        vec![
            ContentBlock::Paragraph {
                id: "b-1".into(),
                text: RichText {
                    text: "A force is a push or pull.".into(),
                    inline: vec![],
                },
            },
            ContentBlock::Heading {
                id: "b-2".into(),
                level: 2,
                text: RichText {
                    text: "Newton's Laws".into(),
                    inline: vec![],
                },
            },
            ContentBlock::Definition {
                id: "b-3".into(),
                term: RichText {
                    text: "Inertia".into(),
                    inline: vec![],
                },
                definition: RichText {
                    text: "Resistance to change in motion.".into(),
                    inline: vec![],
                },
            },
            ContentBlock::Rule {
                id: "b-4".into(),
                statement: RichText {
                    text: "Net force equals mass times acceleration.".into(),
                    inline: vec![],
                },
                conditions: Some(RichText {
                    text: "Constant mass system.".into(),
                    inline: vec![],
                }),
                note: Some(RichText {
                    text: "Valid in inertial frames.".into(),
                    inline: vec![],
                }),
            },
            ContentBlock::Formula {
                id: "b-5".into(),
                expression: "F = ma".into(),
                caption: Some(RichText {
                    text: "Second law".into(),
                    inline: vec![],
                }),
                conditions: Some(RichText {
                    text: "In SI units".into(),
                    inline: vec![],
                }),
            },
            ContentBlock::Example {
                id: "b-6".into(),
                title: Some(ExampleTitle::Plain("Accelerating Block".into())),
                prompt: RichText {
                    text: "Find force for 2 kg at 3 m/s^2.".into(),
                    inline: vec![],
                },
                steps: vec![WorkedStep {
                    step_number: 1,
                    expression: "F = 2 * 3 = 6 N".into(),
                    description: Some("Multiply mass by acceleration".into()),
                }],
                answer: Some(RichText {
                    text: "6 N".into(),
                    inline: vec![],
                }),
            },
            ContentBlock::Figure {
                id: "b-7".into(),
                asset_url: "books/secondary_physics/diagram.png".into(),
                caption: Some(RichText {
                    text: "Free body diagram".into(),
                    inline: vec![],
                }),
                alt: Some("Box with arrows".into()),
                licence: Some("CC BY 4.0".into()),
            },
            ContentBlock::Table {
                id: "b-8".into(),
                title: Some(RichText {
                    text: "Friction Coefficients".into(),
                    inline: vec![],
                }),
                rows: vec![
                    vec![
                        TableCell::Text("Surface".into()),
                        TableCell::Text("mu".into()),
                    ],
                    vec![
                        TableCell::Text("Wood on wood".into()),
                        TableCell::Text("0.4".into()),
                    ],
                ],
                alt: Some("Two column table".into()),
            },
            ContentBlock::List {
                id: "b-9".into(),
                ordered: true,
                items: vec![
                    RichText {
                        text: "First law".into(),
                        inline: vec![],
                    },
                    RichText {
                        text: "Second law".into(),
                        inline: vec![],
                    },
                ],
            },
            ContentBlock::Callout {
                id: "b-10".into(),
                kind: "warning".into(),
                text: RichText {
                    text: "Do not confuse mass with weight.".into(),
                    inline: vec![],
                },
            },
            ContentBlock::Summary {
                id: "b-11".into(),
                points: vec![
                    RichText {
                        text: "Force changes velocity.".into(),
                        inline: vec![],
                    },
                    RichText {
                        text: "Action equals reaction.".into(),
                        inline: vec![],
                    },
                ],
            },
            ContentBlock::ExerciseRef {
                id: "b-12".into(),
                exercise_id: "ex-sec-1-01".into(),
                prompt: Some(RichText {
                    text: "Check your understanding now.".into(),
                    inline: vec![],
                }),
            },
            ContentBlock::GlossaryEntry {
                id: "b-13".into(),
                term: RichText {
                    text: "Newton".into(),
                    inline: vec![],
                },
                definition: RichText {
                    text: "SI unit of force (kg m/s^2).".into(),
                    inline: vec![],
                },
            },
            ContentBlock::Image {
                id: "b-14".into(),
                url: "books/secondary_physics/photo.jpg".into(),
                caption: Some(RichText {
                    text: "Rocket launch".into(),
                    inline: vec![],
                }),
                alt: Some("Rocket ascending".into()),
                position: Some(ImagePosition::Above),
            },
            ContentBlock::Question {
                id: "b-15".into(),
                question: RichText {
                    text: "What opposes motion?".into(),
                    inline: vec![],
                },
                options: vec![
                    Choice {
                        id: "a".into(),
                        text: RichText {
                            text: "Friction".into(),
                            inline: vec![],
                        },
                    },
                    Choice {
                        id: "b".into(),
                        text: RichText {
                            text: "Gravity".into(),
                            inline: vec![],
                        },
                    },
                ],
                answer: "a".into(),
            },
        ]
    }

    fn sample_chapter() -> Chapter {
        Chapter {
            chapter_id: "phy_forces_and_newtons_laws".into(),
            schema_version: 2,
            updated_at: "2026-11-12".into(),
            title: "Forces and Newton's Laws of Motion".into(),
            book_id: "secondary_physics".into(),
            part_id: Some("part-1".into()),
            order: 1,
            facts_inherited: true,
            learning_objectives: vec![LearningObjective {
                id: "lo-1".into(),
                statement: "State and apply Newton's laws".into(),
                bloom_level: "apply".into(),
            }],
            prerequisites: vec!["phy_kinematics".into()],
            formula_sheet: vec![FormulaSheetEntry {
                id: "f-1".into(),
                expression: "F_net = ma".into(),
                caption: RichText {
                    text: "Newton's second law".into(),
                    inline: vec![],
                },
                conditions: Some(RichText {
                    text: "Constant mass".into(),
                    inline: vec![],
                }),
                provenance: Some(Provenance {
                    publisher: "OpenStax".into(),
                    title: "College Physics 2e".into(),
                    url: "https://openstax.org".into(),
                    locator: "Section 4.1".into(),
                    licence: "CC BY 4.0".into(),
                }),
            }],
            glossary: vec![GlossaryEntry {
                id: Some("g-1".into()),
                term: RichText {
                    text: "force".into(),
                    inline: vec![],
                },
                definition: RichText {
                    text: "A push or pull on an object".into(),
                    inline: vec![],
                },
                provenance: None,
            }],
            sections: vec![ChapterSection {
                id: "sec-1".into(),
                order: 1,
                slug: "force-concept".into(),
                title: "The Force Concept".into(),
                est_minutes: 20,
                facts_inherited: true,
                learning_objectives: vec![LearningObjective {
                    id: "sec-lo-1".into(),
                    statement: "Define force as a vector".into(),
                    bloom_level: "understand".into(),
                }],
                teaching_text: TeachingTextContainer::Wrapped {
                    blocks: sample_blocks(),
                },
                worked_examples: vec![SectionWorkedExample {
                    id: "we-1".into(),
                    statement: RichText {
                        text: "Calculate net force.".into(),
                        inline: vec![],
                    },
                    steps: vec![WorkedStep {
                        step_number: 1,
                        expression: "F = ma".into(),
                        description: Some("Apply second law".into()),
                    }],
                    answer: RichText {
                        text: "10 N".into(),
                        inline: vec![],
                    },
                    provenance: Provenance::default(),
                }],
                misconceptions: vec![SectionMisconception {
                    id: "mis-1".into(),
                    claim: RichText {
                        text: "Force is required to keep an object moving.".into(),
                        inline: vec![],
                    },
                    correction: RichText {
                        text: "Objects keep moving at constant velocity unless acted upon.".into(),
                        inline: vec![],
                    },
                    provenance: Provenance::default(),
                }],
                summary_points: vec![
                    RichText {
                        text: "Forces are vector quantities.".into(),
                        inline: vec![],
                    },
                    RichText {
                        text: "Unbalanced forces cause acceleration.".into(),
                        inline: vec![],
                    },
                ],
                exercise_ids: vec!["phy_forces_and_newtons_laws:ex-sec-1-01".into()],
                exam_links: vec![],
                provenance: Provenance {
                    publisher: "OpenStax".into(),
                    title: "College Physics 2e".into(),
                    url: "https://openstax.org".into(),
                    locator: "Chapter 4".into(),
                    licence: "CC BY 4.0".into(),
                },
                no_worked_example_reason: None,
            }],
            exercises: vec![ChapterExercise {
                id: "ex-sec-1-01".into(),
                section_id: "sec-1".into(),
                tier: "core".into(),
                kind: "numeric".into(),
                difficulty: 3,
                marks: 3.0,
                stem: RichText {
                    text: "A 5 kg mass accelerates at 2 m/s^2. Net force is:".into(),
                    inline: vec![],
                },
                options: vec![
                    ExerciseOption {
                        id: "a".into(),
                        text: "10 N".into(),
                    },
                    ExerciseOption {
                        id: "b".into(),
                        text: "2.5 N".into(),
                    },
                ],
                answer: RichText {
                    text: "10 N".into(),
                    inline: vec![],
                },
                answer_kind: "expression".into(),
                solution: vec![ExerciseSolutionStep {
                    step_number: 1,
                    expression: "F = 5 * 2 = 10 N".into(),
                }],
                hints: vec![ExerciseHint {
                    hint_number: 1,
                    text: RichText {
                        text: "Use F = ma".into(),
                        inline: vec![],
                    },
                }],
                tags: vec!["dynamics".into()],
                provenance: Provenance::default(),
                solution_provenance: "Authored".into(),
                answer_note: None,
            }],
            exam_traps: vec![crate::core::models::ExamTrap {
                id: "trap-1".into(),
                exam: "JAMB".into(),
                subject: "physics".into(),
                section_id: "sec-1".into(),
                misconception: RichText {
                    text: "Action and reaction forces cancel each other.".into(),
                    inline: vec![],
                },
                correction: RichText {
                    text: "They act on different bodies.".into(),
                    inline: vec![],
                },
                signal: RichText {
                    text: "Newton third law questions".into(),
                    inline: vec![],
                },
                status: "candidate".into(),
                paper_evidence: Some(PaperEvidence {
                    question_id: Some("q-1".into()),
                    section_id: Some("sec-1".into()),
                    exam: Some("JAMB".into()),
                    year: Some(2024),
                    source: Some("past_paper".into()),
                    url: None,
                }),
                frequency: "common".into(),
                provenance: Provenance::default(),
            }],
            exam_recall_checks: vec![crate::core::models::ExamRecallCheck {
                id: "rc-1".into(),
                exam: "JAMB".into(),
                subject: "physics".into(),
                section_id: "sec-1".into(),
                stem: RichText {
                    text: "The SI unit of force is".into(),
                    inline: vec![],
                },
                options: vec![
                    ExerciseOption {
                        id: "a".into(),
                        text: "Newton".into(),
                    },
                    ExerciseOption {
                        id: "b".into(),
                        text: "Joule".into(),
                    },
                ],
                answer: "a".into(),
                explanation: RichText {
                    text: "1 N = 1 kg m/s^2".into(),
                    inline: vec![],
                },
                difficulty: 1,
                source: "JAMB Physics Syllabus".into(),
            }],
            sources: vec![Provenance {
                publisher: "OpenStax".into(),
                title: "College Physics 2e".into(),
                url: "https://openstax.org".into(),
                locator: "Chapter 4".into(),
                licence: "CC BY 4.0".into(),
            }],
        }
    }

    async fn seeded_app() -> axum::Router {
        let db = replica().await;
        {
            let conn = connect(&db).await;
            api_schema(&conn).await;
            issue_key(&conn, "textbook.key", "commercial", "read:catalog", false).await;
        }
        let st = crate::state::DbState::detached(db.clone());
        let bundle = store::chapters::ChapterBundle {
            books: vec![sample_book()],
            chapters: vec![sample_chapter()],
        };
        store::chapters::import_bundle(&st, &bundle)
            .await
            .expect("import test bundle");
        crate::routes::router(state(db), &crate::config::Config::default())
    }

    #[test]
    fn every_content_block_type_serializes_and_deserializes() {
        let blocks = sample_blocks();
        assert_eq!(blocks.len(), 15, "all 15 content block types present");

        for block in &blocks {
            core::catalog::validate_content_block(block).expect("valid block");
            let json = serde_json::to_string(block).expect("serialize block");
            let deserialized: ContentBlock =
                serde_json::from_str(&json).expect("deserialize block");
            assert_eq!(block, &deserialized);
        }
    }

    #[test]
    fn paragraph_normalizes_content_alias_to_text() {
        let json = r#"{"id":"b-p","type":"paragraph","content":{"text":"Prose content","inline":[]}}"#;
        let block: ContentBlock = serde_json::from_str(json).expect("parse alias");
        match block {
            ContentBlock::Paragraph { id, text } => {
                assert_eq!(id, "b-p");
                assert_eq!(text.text, "Prose content");
            }
            _ => panic!("wrong block variant"),
        }
    }

    #[test]
    fn callout_normalizes_body_alias_to_text() {
        let json = r#"{"id":"b-c","type":"callout","kind":"tip","body":{"text":"Helpful tip","inline":[]}}"#;
        let block: ContentBlock = serde_json::from_str(json).expect("parse alias");
        match block {
            ContentBlock::Callout { id, kind, text } => {
                assert_eq!(id, "b-c");
                assert_eq!(kind, "tip");
                assert_eq!(text.text, "Helpful tip");
            }
            _ => panic!("wrong block variant"),
        }
    }

    #[test]
    fn figure_resolves_media_url_cleanly() {
        let mut block = ContentBlock::Figure {
            id: "fig-1".into(),
            asset_url: "books/secondary_physics/test.jpg".into(),
            caption: Some(RichText {
                text: "Caption".into(),
                inline: vec![],
            }),
            alt: Some("Alt".into()),
            licence: None,
        };
        core::catalog::resolve_content_block(&mut block, "https://cdn.example.com");
        match block {
            ContentBlock::Figure { asset_url, .. } => {
                assert_eq!(
                    asset_url,
                    "https://cdn.example.com/books/secondary_physics/test.jpg"
                );
            }
            _ => panic!("wrong variant"),
        }
    }

    #[tokio::test]
    async fn list_textbooks_endpoint() {
        let app = seeded_app().await;

        assert_eq!(
            call(app.clone(), "GET", "/api/v1/textbooks", None, None)
                .await
                .0,
            StatusCode::UNAUTHORIZED
        );

        let (status, body) =
            call(app, "GET", "/api/v1/textbooks", Some("textbook.key"), None).await;
        assert_eq!(status, StatusCode::OK);
        let books = body.as_array().expect("array of books");
        assert_eq!(books.len(), 1);
        assert_eq!(books[0]["id"], "secondary_physics");
        assert_eq!(books[0]["title"], "Secondary Physics");
        assert_eq!(books[0]["sources"][0]["publisher"], "OpenStax");
    }

    #[tokio::test]
    async fn get_textbook_endpoint() {
        let app = seeded_app().await;

        let (status, body) = call(
            app.clone(),
            "GET",
            "/api/v1/textbooks/secondary_physics",
            Some("textbook.key"),
            None,
        )
        .await;
        assert_eq!(status, StatusCode::OK);
        assert_eq!(body["id"], "secondary_physics");
        assert_eq!(body["chapters"].as_array().unwrap().len(), 1);
        assert_eq!(
            body["chapters"][0]["chapter_id"],
            "phy_forces_and_newtons_laws"
        );

        let (not_found, _) = call(
            app,
            "GET",
            "/api/v1/textbooks/nonexistent_book",
            Some("textbook.key"),
            None,
        )
        .await;
        assert_eq!(not_found, StatusCode::NOT_FOUND);
    }

    #[tokio::test]
    async fn get_chapter_outline_endpoint() {
        let app = seeded_app().await;

        let (status, body) = call(
            app.clone(),
            "GET",
            "/api/v1/chapters/phy_forces_and_newtons_laws",
            Some("textbook.key"),
            None,
        )
        .await;
        assert_eq!(status, StatusCode::OK);
        assert_eq!(body["id"], "phy_forces_and_newtons_laws");
        assert_eq!(body["title"], "Forces and Newton's Laws of Motion");
        assert_eq!(body["formula_sheet"][0]["expression"], "F_net = ma");
        assert_eq!(body["glossary"][0]["term"]["text"], "force");

        let sections = body["section_index"].as_array().expect("section_index");
        assert_eq!(sections.len(), 1);
        assert_eq!(sections[0]["id"], "sec-1");
        assert_eq!(sections[0]["title"], "The Force Concept");

        let (not_found, _) = call(
            app,
            "GET",
            "/api/v1/chapters/nonexistent_chapter",
            Some("textbook.key"),
            None,
        )
        .await;
        assert_eq!(not_found, StatusCode::NOT_FOUND);
    }

    #[tokio::test]
    async fn get_section_detail_endpoint() {
        let app = seeded_app().await;

        // By local id "sec-1"
        let (status, body) = call(
            app.clone(),
            "GET",
            "/api/v1/chapters/phy_forces_and_newtons_laws/sections/sec-1",
            Some("textbook.key"),
            None,
        )
        .await;
        assert_eq!(status, StatusCode::OK);
        assert_eq!(body["id"], "sec-1");
        assert_eq!(body["chapter_id"], "phy_forces_and_newtons_laws");
        assert_eq!(body["title"], "The Force Concept");
        assert_eq!(body["est_minutes"], 20);

        let content = body["content"].as_array().expect("content blocks");
        assert_eq!(content.len(), 15);
        assert_eq!(content[0]["type"], "paragraph");
        assert_eq!(content[0]["text"]["text"], "A force is a push or pull.");
        assert_eq!(content[4]["type"], "formula");
        assert_eq!(content[4]["expression"], "F = ma");

        assert_eq!(body["worked_examples"].as_array().unwrap().len(), 1);
        assert_eq!(body["misconceptions"].as_array().unwrap().len(), 1);
        assert_eq!(body["summary_points"].as_array().unwrap().len(), 2);
        assert_eq!(body["provenance"]["publisher"], "OpenStax");

        // By slug "force-concept"
        let (status_slug, body_slug) = call(
            app.clone(),
            "GET",
            "/api/v1/chapters/phy_forces_and_newtons_laws/sections/force-concept",
            Some("textbook.key"),
            None,
        )
        .await;
        assert_eq!(status_slug, StatusCode::OK);
        assert_eq!(body_slug["id"], "sec-1");

        // Non-existent section
        let (not_found, _) = call(
            app,
            "GET",
            "/api/v1/chapters/phy_forces_and_newtons_laws/sections/sec-999",
            Some("textbook.key"),
            None,
        )
        .await;
        assert_eq!(not_found, StatusCode::NOT_FOUND);
    }

    #[tokio::test]
    async fn list_chapter_exercises_endpoint() {
        let app = seeded_app().await;

        let (status, body) = call(
            app.clone(),
            "GET",
            "/api/v1/chapters/phy_forces_and_newtons_laws/exercises",
            Some("textbook.key"),
            None,
        )
        .await;
        assert_eq!(status, StatusCode::OK);
        let exercises = body.as_array().expect("exercises");
        assert_eq!(exercises.len(), 1);
        assert_eq!(
            exercises[0]["id"],
            "phy_forces_and_newtons_laws:ex-sec-1-01"
        );
        assert_eq!(exercises[0]["marks"], 3.0);
        assert_eq!(exercises[0]["options"][0]["id"], "a");
        assert_eq!(exercises[0]["options"][0]["text"], "10 N");
        assert_eq!(exercises[0]["answer"]["text"], "10 N");
        assert_eq!(exercises[0]["solution"][0]["expression"], "F = 5 * 2 = 10 N");

        let (narrowed_status, narrowed_body) = call(
            app,
            "GET",
            "/api/v1/chapters/phy_forces_and_newtons_laws/exercises?tier=stretch",
            Some("textbook.key"),
            None,
        )
        .await;
        assert_eq!(narrowed_status, StatusCode::OK);
        assert_eq!(narrowed_body.as_array().unwrap().len(), 0);
    }

    #[tokio::test]
    async fn list_exam_traps_endpoint() {
        let app = seeded_app().await;

        let (status, body) = call(
            app.clone(),
            "GET",
            "/api/v1/exam-traps?exam=JAMB",
            Some("textbook.key"),
            None,
        )
        .await;
        assert_eq!(status, StatusCode::OK);
        let traps = body.as_array().expect("traps");
        assert_eq!(traps.len(), 1);
        assert_eq!(traps[0]["exam"], "JAMB");
        assert_eq!(
            traps[0]["misconception"]["text"],
            "Action and reaction forces cancel each other."
        );
        assert_eq!(traps[0]["paper_evidence"]["question_id"], "q-1");
    }

    #[tokio::test]
    async fn list_exam_practice_endpoint() {
        let app = seeded_app().await;

        let (status, body) = call(
            app.clone(),
            "GET",
            "/api/v1/exam-practice?exam=JAMB",
            Some("textbook.key"),
            None,
        )
        .await;
        assert_eq!(status, StatusCode::OK);
        let checks = body.as_array().expect("checks");
        assert_eq!(checks.len(), 1);
        assert_eq!(checks[0]["exam"], "JAMB");
        assert_eq!(checks[0]["stem"]["text"], "The SI unit of force is");
        assert_eq!(checks[0]["answer"], "a");
    }

    #[tokio::test]
    async fn real_bank_chapter_end_to_end_http_query() {
        let chapter_path = std::path::Path::new(
            "/home/kristency/Projects/utmelab-bank/data/chapters/phy_forces_and_newtons_laws.json",
        );
        if !chapter_path.exists() {
            return;
        }
        let chapter_data = std::fs::read_to_string(chapter_path).expect("read chapter");
        let chapter: crate::core::models::Chapter =
            serde_json::from_str(&chapter_data).expect("deserialize bank chapter");

        let db = replica().await;
        {
            let conn = connect(&db).await;
            api_schema(&conn).await;
            issue_key(&conn, "textbook.key", "commercial", "read:catalog", false).await;
        }
        let st = crate::state::DbState::detached(db.clone());
        let bundle = store::chapters::ChapterBundle {
            books: vec![sample_book()],
            chapters: vec![chapter],
        };
        store::chapters::import_bundle(&st, &bundle)
            .await
            .expect("import real bank chapter");

        let app = crate::routes::router(state(db), &crate::config::Config::default());

        // 1. Get Chapter Outline
        let (status, body) = call(
            app.clone(),
            "GET",
            "/api/v1/chapters/phy_forces_and_newtons_laws",
            Some("textbook.key"),
            None,
        )
        .await;
        assert_eq!(status, StatusCode::OK);
        assert_eq!(body["id"], "phy_forces_and_newtons_laws");
        let sections = body["section_index"].as_array().expect("sections");
        assert!(!sections.is_empty(), "expected sections in chapter outline");
        let first_sec_id = sections[0]["id"].as_str().expect("first section id");

        // 2. Get Section Detail using local section ID
        let (status, sec_body) = call(
            app.clone(),
            "GET",
            &format!("/api/v1/chapters/phy_forces_and_newtons_laws/sections/{first_sec_id}"),
            Some("textbook.key"),
            None,
        )
        .await;
        assert_eq!(status, StatusCode::OK);
        assert_eq!(sec_body["id"], first_sec_id);
        let blocks = sec_body["content"].as_array().expect("content blocks");
        assert!(!blocks.is_empty(), "expected content blocks in section");

        // 3. List Exercises for this chapter
        let (status, ex_body) = call(
            app.clone(),
            "GET",
            "/api/v1/chapters/phy_forces_and_newtons_laws/exercises",
            Some("textbook.key"),
            None,
        )
        .await;
        assert_eq!(status, StatusCode::OK);
        let exercises = ex_body.as_array().expect("exercises");
        assert!(!exercises.is_empty(), "expected exercises in chapter");
    }
}
