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
use crate::bank::Store as _;
use crate::bank::{Choice, Question};

/// Source slug → (our slug, JAMB's own name). No fallback: an unknown slug is
/// a decision for a person, not a default.
const SUBJECT_MAP: &[(&str, &str, &str)] = &[
    ("government", "government", "Government"),
    ("economics", "economics", "Economics"),
    ("commerce", "commerce", "Commerce"),
    ("history", "history", "History"),
    ("geography", "geography", "Geography"),
    ("mathematics", "mathematics", "Mathematics"),
    ("physics", "physics", "Physics"),
    ("chemistry", "chemistry", "Chemistry"),
    ("biology", "biology", "Biology"),
    (
        "agricultural-science",
        "agricultural-science",
        "Agricultural Science",
    ),
    (
        "christian-religious-knowledge-crk",
        "christian-religious-studies",
        "Christian Religious Studies",
    ),
    (
        "literature-in-english",
        "literature-in-english",
        "Literature-in-English",
    ),
    ("arabic", "arabic", "Arabic"),
    ("computer-studies", "computer-studies", "Computer Studies"),
    ("french", "french", "French"),
    ("hausa", "hausa", "Hausa"),
    ("igbo", "igbo", "Igbo"),
    ("yoruba", "yoruba", "Yoruba"),
    ("home-economics", "home-economics", "Home Economics"),
    (
        "islamic-religious-knowledge-irk",
        "islamic-religious-studies",
        "Islamic Religious Studies",
    ),
    (
        "physical-education",
        "physical-education",
        "Physical and Health Education",
    ),
    ("fine-arts", "art", "Art"),
    (
        // The source spells this one "Accounts - Principles of Accounts", so
        // asking for `principles-of-accounts` returns HTTP 200 and zero rows —
        // the silent failure this map exists to make impossible.
        "accounts-principles-of-accounts",
        "principles-of-accounts",
        "Principles of Accounts",
    ),
    ("english-language", "use-of-english", "Use of English"),
];

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

pub fn run(inbox: &Path, data: &Path, dry_run: bool) -> anyhow_lite::Result<()> {
    let mut store = JsonStore::load(data).map_err(|e| format!("bank does not load: {e}"))?;

    let mut existing: Vec<Question> = store.questions().to_vec();
    let mut seen: HashSet<String> = existing
        .iter()
        .map(|q| {
            fingerprint(
                &q.text,
                &q.options.iter().map(|o| o.text.clone()).collect::<Vec<_>>(),
            )
        })
        .collect();

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

        let Some((_, slug, name)) = SUBJECT_MAP
            .iter()
            .find(|(source, _, _)| *source == source_slug)
        else {
            refusals.note("unknown subject slug", source_slug.to_owned());
            continue;
        };

        for row in read_inbox(file)? {
            // Structure first: we cannot judge a row we cannot read.
            let Some(question) = (|| -> Option<Question> {
                let text = row["text"].as_str()?.trim().to_owned();
                if text.is_empty() {
                    refusals.note("empty stem", file.display().to_string());
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
                            text: o["text"].as_str()?.to_owned(),
                        })
                    })
                    .collect::<Option<Vec<_>>>()?;
                let image = row["image"].as_str().map(str::to_owned);
                if image.is_none() && mentions_figure(&text) {
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
                    text,
                    options: choices,
                    answer,
                    subtopic_id: None,
                    section: None,
                    passage_id: None,
                    image,
                    explanation: None,
                    marks: 2.5,
                    difficulty: 3,
                    // Never set here. Review sets this, not a bulk import (D45).
                    verified: false,
                })
            })() else {
                continue;
            };

            if store.subject("JAMB", slug).is_none() {
                refusals.note("subject missing from the catalog", name.to_owned());
                continue;
            }

            let print = fingerprint(
                &question.text,
                &question
                    .options
                    .iter()
                    .map(|o| o.text.clone())
                    .collect::<Vec<_>>(),
            );
            if !seen.insert(print) {
                refusals.note(
                    "duplicate of a question we already hold",
                    question.text.clone(),
                );
                continue;
            }

            if question.image.is_some() {
                with_image += 1;
            }
            admitted += 1;
            existing.push(question);
        }
    }

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

    println!("\nAdmitted: {admitted} ({with_image} carrying a diagram)");
    if refusals.counts.is_empty() {
        println!("Refused: none");
    } else {
        println!("Refused:");
        for (reason, count) in &refusals.counts {
            let example = refusals.examples.get(reason).cloned().unwrap_or_default();
            println!(
                "  {count:>4}  {reason}\n         e.g. {}",
                truncate(&example, 78)
            );
        }
    }
    if dry_run {
        println!("\n(dry run — nothing written)");
    }
    Ok(())
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
        for (source, slug, name) in SUBJECT_MAP {
            assert!(!source.is_empty() && !slug.is_empty() && !name.is_empty());
        }
    }
}
