//! `cargo run -- import` — move harvested questions into the bank.
//!
//! The harvester writes to `data/inbox/`, which nothing loads. This is the one
//! step that changes `data/questions.json`, and it is deliberately the *only*
//! one: bulk content entering the bank must never be something a human edits by
//! hand, because hand-editing 600 rows is where provenance quietly rots.
//!
//! ## The three gates (D51)
//!
//! **Admissible — decided here, mechanically.** Structure, a key that points
//! at a real option, a subject the catalog knows, and no duplicate of a row we
//! already hold. Nothing here needs a human opinion.
//!
//! **Explainable — not a gate.** A harvested row arrives with no explanation
//! and `verified: false`, and stays servable. That is deliberate: the
//! explanation is what we charge for, so it cannot also be the price of
//! admission, or the bank stays empty until someone writes 600 lessons.
//!
//! **Sellable — `verified`, set by review, never by this command.** A
//! third-party answer key is evidence, not review (D45/D49).
//!
//! ## Slug mapping
//!
//! The source spells subjects its own way (`english-language`,
//! `christian-religious-knowledge-crk`). We use JAMB's (D21), so every incoming
//! slug passes through here; an unmapped slug is refused rather than invented.

use sha2::Digest;
use std::collections::HashSet;
use std::path::{Path, PathBuf};

use serde_json::Value;

use crate::JsonStore;
use crate::bank::Store;
use crate::bank::{Choice, ImagePosition, Inline, InlineKind, Question, RichText};

/// The subject map lives in `config/harvest.json`, not here.
///
/// It used to be a `const` in this file, with the harvester holding a second
/// copy in Python. Two lists is how a subject gets crawled under one slug and
/// merged under another — which is exactly how `art`/`fine-arts` and
/// `accounts-principles-of-accounts`/`principles-of-accounts` drifted apart.
/// One file, read by both.
///
/// A missing entry is a refusal, never a fallback: an unmapped slug is a
/// decision for a person.
#[derive(serde::Deserialize)]
struct HarvestConfig {
    subjects: Vec<HarvestSubject>,
}

#[derive(serde::Deserialize)]
struct HarvestSubject {
    source: String,
    slug: String,
    #[allow(dead_code)] // present so the file is self-describing; validated on load
    name: String,
}

/// Read the config, defaulting to `config/harvest.json` beside the manifest.
fn subject_map(config_path: Option<&Path>) -> anyhow_lite::Result<Vec<(String, String)>> {
    let path = match config_path {
        Some(p) => p.to_path_buf(),
        None => Path::new(env!("CARGO_MANIFEST_DIR")).join("config/harvest.json"),
    };
    let text = std::fs::read_to_string(&path)
        .map_err(|e| format!("harvest config {}: {e}", path.display()))?;
    let config: HarvestConfig =
        serde_json::from_str(&text).map_err(|e| format!("parse {}: {e}", path.display()))?;
    Ok(config
        .subjects
        .into_iter()
        .map(|s| (s.source, s.slug))
        .collect())
}

/// What we refused, and why. Every refusal is counted and printed: a silent
/// drop is indistinguishable from a bug, and we have lost questions to silence
/// twice already today.
#[derive(Default)]
struct Refusals {
    counts: std::collections::BTreeMap<&'static str, usize>,
    examples: std::collections::BTreeMap<&'static str, String>,
}

impl Refusals {
    fn note(&mut self, reason: &'static str, detail: impl Into<String>) {
        *self.counts.entry(reason).or_default() += 1;
        self.examples.entry(reason).or_insert_with(|| detail.into());
    }
}

/// Read a RichText value from an inbox row. Accepts the harvester's
/// `{"text", "inline"}` shape; a bare string means unmarked prose (old
/// inbox files predate marks). Anything else is a refusal, counted.
fn inbox_text(value: &Value) -> Option<RichText> {
    match value {
        Value::String(s) => Some(RichText::plain(s.trim().to_owned())),
        Value::Object(_) => {
            let text: String = value.get("text")?.as_str()?.trim().to_owned();
            let mut rt = RichText::plain(text);
            for m in value.get("inline")?.as_array()? {
                rt.inline.push(Inline {
                    start: m.get("start")?.as_u64()? as u32,
                    len: m.get("len")?.as_u64()? as u32,
                    kind: match m.get("kind")?.as_str()? {
                        "bold" => InlineKind::Bold,
                        "italic" => InlineKind::Italic,
                        "underline" => InlineKind::Underline,
                        "strike" => InlineKind::Strike,
                        "subscript" => InlineKind::Subscript,
                        "superscript" => InlineKind::Superscript,
                        "image" => InlineKind::Image {
                            url: m.get("url")?.as_str()?.to_owned(),
                            position: match m.get("position")?.as_str()? {
                                "below" => ImagePosition::Below,
                                _ => ImagePosition::Above,
                            },
                            alt: m.get("alt").and_then(|a| a.as_str()).map(str::to_owned),
                        },
                        _ => return None,
                    },
                });
            }
            Some(rt)
        }
        _ => None,
    }
}

/// A stable fingerprint of a question's *content*, used to spot duplicates.
/// Ids are useless here: the same question legitimately arrives under two ids.
fn fingerprint(text: &str, options: &[String]) -> String {
    let mut all: Vec<String> = options.iter().map(|o| o.trim().to_lowercase()).collect();
    all.sort();
    let joined = format!("{}|{}", text.trim().to_lowercase(), all.join("~"));
    let digest = sha2::Sha256::digest(joined.as_bytes());
    digest[..8].iter().map(|b| format!("{b:02x}")).collect()
}

fn read_inbox(path: &Path) -> anyhow_lite::Result<Vec<Value>> {
    let text = std::fs::read_to_string(path)?;
    let value: Value = serde_json::from_str(&text)?;
    Ok(value["questions"].as_array().cloned().unwrap_or_default())
}

mod anyhow_lite {
    pub type Result<T> = std::result::Result<T, Box<dyn std::error::Error>>;
}

pub fn run(
    inbox: &Path,
    data: &Path,
    dry_run: bool,
    config: Option<&Path>,
) -> anyhow_lite::Result<()> {
    let subjects = subject_map(config)?;
    // Same transitional split as `serve`: catalog embedded, questions from
    // `data/questions.json`. Import stays local-only — it never touches the
    // VPS; the file it writes becomes the Turso seed.
    let mut store =
        JsonStore::load_embedded(data).map_err(|e| format!("bank does not load: {e}"))?;

    // Servable plus withheld: the rewrite must carry every valid row back,
    // or the next import silently deletes what review has not assigned yet
    // (D58 — this exact path ate q_unassigned_civic_001).
    let mut existing: Vec<Question> = store
        .questions()
        .iter()
        .chain(store.withheld_questions().iter())
        .cloned()
        .collect();
    let mut seen: HashSet<String> = existing
        .iter()
        .map(|q| {
            fingerprint(
                &q.text.text,
                &q.options
                    .iter()
                    .map(|o| o.text.text.clone())
                    .collect::<Vec<_>>(),
            )
        })
        .collect();

    let adm = admit(&store, &subjects, inbox, &mut existing, &mut seen)?;
    if !dry_run {
        let problems = store.replace_questions(existing);
        if !problems.is_empty() {
            // Refuse to write a file the loader would then reject on boot.
            println!("\nRefusing to write — the merged bank would not load:");
            for problem in problems.iter().take(10) {
                println!("  {problem}");
            }
            return Ok(());
        }
        store.write_questions(data)?;
        println!("\nWritten to {}", data.join("questions.json").display());
    }
    report(&adm, dry_run);
    Ok(())
}

/// Turso sink for the same admission (W2). The file path above stays the
/// dev behavior byte-for-byte; this writes validated rows straight to the
/// source of truth. Withheld carry-through stays file-side (D58 lives in
/// `run`): Turso holds servable rows only, and the R4 gate runs on the
/// merged bank before a single row is written.
pub async fn run_turso(
    db: &crate::db::Db,
    store: &crate::bank::TursoStore,
    inbox: &Path,
    dry_run: bool,
    config: Option<&Path>,
) -> anyhow_lite::Result<()> {
    let subjects = subject_map(config)?;
    let base = store.questions().len();
    let mut existing: Vec<Question> = store.questions().to_vec();
    let mut seen: HashSet<String> = existing
        .iter()
        .map(|q| {
            fingerprint(
                &q.text.text,
                &q.options
                    .iter()
                    .map(|o| o.text.text.clone())
                    .collect::<Vec<_>>(),
            )
        })
        .collect();

    let adm = admit(store, &subjects, inbox, &mut existing, &mut seen)?;
    let new: &[Question] = &existing[base..];
    let problems = store.check_new_questions(new);
    if !problems.is_empty() {
        // Same refusal contract as the file path: nothing is written.
        println!("\nRefusing to write — the merged bank would not load:");
        for problem in problems.iter().take(10) {
            println!("  {problem}");
        }
        return Ok(());
    }
    if !dry_run {
        let n = crate::bank::write::upsert_questions(db, new)
            .await
            .map_err(|e| format!("turso upsert: {e}"))?;
        println!("\nUpserted {n} rows to Turso");
    }
    report(&adm, dry_run);
    Ok(())
}

/// Shared admission core: files loop + per-row gates + catalog check +
/// id/dup checks. Sink-agnostic: works against any `Store` (file or Turso).
/// Appends admitted rows to `existing`; returns counts plus refusals for the
/// shared summary. Review stays out — admission never judges quality (D51).
struct Admitted {
    admitted: usize,
    with_image: usize,
    refusals: Refusals,
}

fn admit(
    store: &dyn Store,
    subjects: &[(String, String)],
    inbox: &Path,
    existing: &mut Vec<Question>,
    seen: &mut HashSet<String>,
) -> anyhow_lite::Result<Admitted> {
    let mut refusals = Refusals::default();
    let mut admitted = 0usize;
    let mut with_image = 0usize;

    let mut files: Vec<PathBuf> = std::fs::read_dir(inbox)?
        .filter_map(|e| e.ok().map(|e| e.path()))
        .filter(|p| p.extension().and_then(|e| e.to_str()) == Some("json"))
        .collect();
    files.sort();

    for file in &files {
        // `<subject>-<year>.json` — the year is also the cohort a row with no
        // stated year belongs to (D52).
        let (source_slug, file_year) = match file
            .file_stem()
            .and_then(|s| s.to_str())
            .and_then(|s| s.rsplit_once('-'))
        {
            Some((slug, year)) => (slug.to_owned(), year.parse::<u16>().unwrap_or(2025)),
            None => (String::new(), 2025),
        };
        let source_slug = source_slug.as_str();

        let Some((_, slug)) = subjects.iter().find(|(source, _)| source == source_slug) else {
            refusals.note("unknown subject slug", source_slug.to_owned());
            continue;
        };
        let slug = slug.as_str();

        for row in read_inbox(file)? {
            // Structure first: we cannot judge a row we cannot read.
            let Some(question) = (|| -> Option<Question> {
                let mut stem = inbox_text(&row["text"])?;
                let text = stem.text.clone();
                if text.is_empty() {
                    refusals.note("empty stem", file.display().to_string());
                    return None;
                }
                // Marks arriving in the inbox are validated at the gate like
                // every other mechanical rule — a bad offset must be a
                // counted refusal, not a whole-file boot failure later.
                let mark_problems = stem.validate(row["id"].as_str().unwrap_or("?"), "inbox text");
                if !mark_problems.is_empty() {
                    refusals.note(
                        "invalid marks",
                        mark_problems.first().cloned().unwrap_or_default(),
                    );
                    return None;
                }
                let options: Vec<Value> = row["options"].as_array()?.clone();
                if !(2..=5).contains(&options.len()) {
                    refusals.note("option count outside 2-5", text.clone());
                    return None;
                }
                let answer = row["answer"].as_str()?.to_owned();
                if !options
                    .iter()
                    .any(|o| o["id"].as_str() == Some(answer.as_str()))
                {
                    refusals.note("key points outside the options", text.clone());
                    return None;
                }
                let choices: Vec<Choice> = options
                    .iter()
                    .map(|o| {
                        Some(Choice {
                            id: o["id"].as_str()?.to_owned(),
                            text: inbox_text(&o["text"])?,
                        })
                    })
                    .collect::<Option<Vec<_>>>()?;
                for c in &choices {
                    let problems = c.text.validate(
                        row["id"].as_str().unwrap_or("?"),
                        &format!("inbox option '{}'", c.id),
                    );
                    if !problems.is_empty() {
                        refusals.note(
                            "invalid marks",
                            problems.first().cloned().unwrap_or_default(),
                        );
                        return None;
                    }
                }
                // A figure becomes an `Image` anchor mark on the stem (D60):
                // zero-length, attached at the start for `above` and the end
                // for `below`. Placement is read off the stem's own prose
                // ("the diagram below") — mechanical, no judgment. Anything
                // else renders above, the observed 90% case on both stores.
                // Marks the harvester already mapped ride through untouched.
                match row["image"].as_str() {
                    None => {}
                    Some(src) if !src.starts_with("https://") => {
                        refusals.note("image is not an absolute URL", text.clone());
                        return None;
                    }
                    Some(src) => {
                        let position = image_position(&text);
                        let anchor = match position {
                            ImagePosition::Above => 0,
                            ImagePosition::Below => text.chars().count() as u32,
                        };
                        stem.inline.push(Inline {
                            start: anchor,
                            len: 0,
                            kind: InlineKind::Image {
                                url: src.to_owned(),
                                position,
                                alt: None,
                            },
                        });
                    }
                };
                let carried_image = stem.has_mark(|k| matches!(k, InlineKind::Image { .. }));
                if !carried_image && mentions_figure(&text) {
                    refusals.note("needs a figure we do not have", text.clone());
                    return None;
                }

                Some(Question {
                    id: row["id"].as_str()?.to_owned(),
                    exam: "JAMB".to_owned(),
                    subject: (*slug).to_owned(),
                    // The source states the year it attributes the paper to; if
                    // it states none, the cohort is the year being harvested (D52).
                    year: row["year"].as_u64().map(|y| y as u16).unwrap_or(file_year),
                    source: row["source"].as_str().unwrap_or("imported").to_owned(),
                    text: stem,
                    options: choices,
                    answer,
                    subtopic_id: None,
                    section: None,
                    passage_id: None,
                    explanation: None,
                    // The harvester strips markup and carries no marks —
                    // quarantine flags the underlined rows, review fills them.
                    marks: 2.5,
                    difficulty: 3,
                    // Never set here. Review sets this, not a bulk import (D45).
                    // (Derived at load from the verification log, D62.)
                    verified: false,
                })
            })() else {
                continue;
            };

            if store.subject("JAMB", slug).is_none() {
                refusals.note("subject missing from the catalog", slug.to_owned());
                continue;
            }

            // An id already in the bank is a no-op, not a second copy. The
            // content fingerprint below cannot catch it on its own: cleaning
            // entities out of the bank made its text differ from the raw inbox
            // text, so the row looked new while its id was taken — and the
            // loader then refused the whole file.
            if existing.iter().any(|q| q.id == question.id) {
                refusals.note("id already in the bank", question.id.clone());
                continue;
            }

            let print = fingerprint(
                &question.text.text,
                &question
                    .options
                    .iter()
                    .map(|o| o.text.text.clone())
                    .collect::<Vec<_>>(),
            );
            if !seen.insert(print) {
                refusals.note(
                    "duplicate of a question we already hold",
                    question.text.text.clone(),
                );
                continue;
            }

            if question
                .text
                .has_mark(|k| matches!(k, InlineKind::Image { .. }))
            {
                with_image += 1;
            }
            admitted += 1;
            existing.push(question);
        }
    }

    Ok(Admitted {
        admitted,
        with_image,
        refusals,
    })
}

fn report(adm: &Admitted, dry_run: bool) {
    println!(
        "\nAdmitted: {} ({} carrying a diagram)",
        adm.admitted, adm.with_image
    );
    if adm.refusals.counts.is_empty() {
        println!("Refused: none");
    } else {
        println!("Refused:");
        for (reason, count) in &adm.refusals.counts {
            let example = adm
                .refusals
                .examples
                .get(reason)
                .cloned()
                .unwrap_or_default();
            println!(
                "  {count:>4}  {reason}\n         e.g. {}",
                truncate(&example, 78)
            );
        }
    }
    if dry_run {
        println!("\n(dry run — nothing written)");
    }
}

fn mentions_figure(text: &str) -> bool {
    [
        "diagram",
        "figure",
        "graph",
        "illustrat",
        "shown",
        "sketch",
        "table",
    ]
    .iter()
    .any(|h| text.to_lowercase().contains(h))
}

/// Placement off the stem's prose: only "below" is ever stated, and only for
/// the figure ("use the diagram below"). Everything else — "above" or nothing
/// said — renders above, the observed case on both stores.
fn image_position(text: &str) -> ImagePosition {
    if text.to_lowercase().contains("below") {
        ImagePosition::Below
    } else {
        ImagePosition::Above
    }
}

fn truncate(text: &str, max: usize) -> String {
    if text.chars().count() <= max {
        return text.to_owned();
    }
    let mut out: String = text.chars().take(max).collect();
    out.push('…');
    out
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn inbox_text_accepts_marks_and_plain_strings() {
        // Harvester shape: marks ride through with exact offsets.
        let marked = serde_json::json!({
            "text": "The plaintiff made very cogent submissions.",
            "inline": [{"start": 24, "len": 6, "kind": "underline"}],
        });
        let rt = inbox_text(&marked).expect("marked shape parses");
        assert_eq!(rt.text, "The plaintiff made very cogent submissions.");
        assert_eq!(rt.inline.len(), 1);
        // Pre-marks inbox files: a bare string means unmarked prose.
        let plain = inbox_text(&serde_json::json!("Just words.")).expect("string parses");
        assert_eq!(plain.inline.len(), 0);
        // Unknown mark kinds refuse rather than smuggle through.
        let bogus = serde_json::json!({
            "text": "Words.",
            "inline": [{"start": 0, "len": 5, "kind": "sparkle"}],
        });
        assert!(inbox_text(&bogus).is_none());
    }

    #[test]
    fn a_figure_reference_is_spotted() {
        assert!(mentions_figure("From the diagram above, find the area"));
        assert!(mentions_figure("The graph of the function X is"));
        assert!(!mentions_figure(
            "Which of these colours has the longest wavelength?"
        ));
    }

    #[test]
    fn duplicates_are_caught_even_when_ids_differ() {
        let a = fingerprint("The capital of Nigeria?", &["Lagos".into(), "Abuja".into()]);
        let b = fingerprint(
            "  the capital of nigeria?  ",
            &["Abuja".into(), "Lagos".into()],
        );
        assert_eq!(a, b, "case, spacing and option order must not hide a dupe");
        assert_ne!(a, fingerprint("The capital of Kenya?", &["Nairobi".into()]));
    }

    #[test]
    fn every_source_slug_maps_to_a_jamb_slug() {
        for (source, slug) in subject_map(None).expect("config parses") {
            assert!(!source.is_empty() && !slug.is_empty());
        }
    }

    /// The config and the catalog must agree, or a question is harvested under a
    /// subject that does not exist and is silently refused at merge time.
    #[test]
    fn the_harvest_config_and_the_catalog_agree_on_subjects() {
        let bank = JsonStore::load(Path::new("data")).expect("bank loads");
        let config: HarvestConfig =
            serde_json::from_str(&std::fs::read_to_string("config/harvest.json").expect("config"))
                .expect("config parses");

        for entry in &config.subjects {
            let subject = bank.subject("JAMB", &entry.slug).unwrap_or_else(|| {
                panic!(
                    "config lists {:?} but the catalog has no JAMB subject {:?}",
                    entry.source, entry.slug
                )
            });
            // Names too: importing a syllabus with a slug as its display name
            // lowercased half the catalog, and D21 says these carry JAMB's own
            // spelling. Slug present but name wrong is the same drift.
            assert_eq!(
                subject.name, entry.name,
                "{:?} is named {:?} in the catalog but {:?} in the config",
                entry.slug, subject.name, entry.name
            );
        }
    }
    #[test]
    fn check_new_questions_gates_merged_bank() {
        use crate::bank::{Choice, RichText};
        let dir = std::path::PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("data");
        let store = crate::JsonStore::load(&dir).expect("real bank loads for gate test");
        // Empty candidates: a clean bank stays clean.
        assert!(store.check_new_questions(&[]).is_empty());
        // Unknown subject: the merged bank would not boot.
        let bad = Question {
            id: "t_gate_probe".to_string(),
            exam: "JAMB".to_string(),
            subject: "No Such Subject".to_string(),
            year: 2025,
            source: "imported".to_string(),
            text: RichText {
                text: "Probe?".to_string(),
                inline: Vec::new(),
            },
            options: vec![Choice {
                id: "a".to_string(),
                text: RichText {
                    text: "Yes".to_string(),
                    inline: Vec::new(),
                },
            }],
            answer: "a".to_string(),
            subtopic_id: None,
            section: None,
            passage_id: None,
            explanation: None,
            marks: 2.5,
            difficulty: 3,
            verified: false,
        };
        let problems = store.check_new_questions(std::slice::from_ref(&bad));
        assert!(
            !problems.is_empty(),
            "unknown subject must fail the R4 gate"
        );
    }
}
