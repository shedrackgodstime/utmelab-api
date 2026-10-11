//! `cargo run -- quarantine` — the mechanical-defect report, read-only.
//!
//! No judgment here: every check is decidable without reading comprehension.
//! A listed row needs a fix or a human; nothing listed may be marked `verified`
//! until its kind is resolved. This command never writes — it prints, and the
//! boot validation in `bank::JsonStore` stays the only gate.
//!
//! Kinds, and what resolves each:
//! * `underline_missing` — stem names an underlined word but `emphasis` is
//!   empty. Resolve by backfilling `emphasis` (the proposal script covers
//!   synonyms/antonyms; stress and sound items need hand-reading).
//! * `missing_figure` — stem mentions a diagram/figure/graph the row does not
//!   carry. Resolve with the image-mirror job, or withhold.
//! * `duplicate_stem` — content fingerprint already held under another id.
//!   Resolve by dropping the weaker copy.
//! * `cloze_without_passage` — "fill the gap labelled N" with no `passage_id`:
//!   the gap number points at a passage the row does not link, so the stem
//!   alone cannot be answered. Resolve by linking the passage, or withhold.
//!   (Rows that carry their passage inline in the stem — Arabic/French
//!   comprehension — need no link and are not listed; only the numbered-gap
//!   form names something absent.)
//! * `option_count` — not four options in a 2025-cohort bank. JAMB sets four;
//!   anything else needs a human to confirm the era or fix the row.
//! * `novel_leak` — names Bepo/Stardom/Lekki: a novel question sitting in the
//!   subject bank (D35). Resolve by moving it to the novel document.

use std::collections::{BTreeMap, HashSet};
use std::path::Path;

use sha2::Digest;

use crate::JsonStore;
use crate::bank::Store as _;

/// One mechanical defect on one row.
#[derive(Debug)]
pub struct Finding {
    pub kind: &'static str,
    pub id: String,
    pub detail: String,
}

pub fn scan(store: &JsonStore) -> Vec<Finding> {
    let mut out = Vec::new();
    out.extend(underline_missing(store));
    out.extend(missing_figures(store));
    out.extend(duplicate_stems(store));
    out.extend(cloze_without_passage(store));
    out.extend(option_counts(store));
    out.extend(novel_leaks(store));
    out
}

/// Stems that point at an underlined word without saying which one.
fn underline_missing(store: &JsonStore) -> Vec<Finding> {
    store
        .questions()
        .iter()
        .filter(|q| q.emphasis.is_none() && q.text.to_lowercase().contains("underlin"))
        .map(|q| Finding {
            kind: "underline_missing",
            id: q.id.clone(),
            detail: truncate(&q.text, 80),
        })
        .collect()
}

/// Stems that mention a figure the row does not carry.
fn missing_figures(store: &JsonStore) -> Vec<Finding> {
    const HINTS: [&str; 7] = [
        "diagram",
        "figure",
        "graph",
        "illustrat",
        "shown",
        "sketch",
        "table",
    ];
    store
        .questions()
        .iter()
        .filter(|q| q.image.is_none() && HINTS.iter().any(|h| q.text.to_lowercase().contains(h)))
        .map(|q| Finding {
            kind: "missing_figure",
            id: q.id.clone(),
            detail: truncate(&q.text, 80),
        })
        .collect()
}

fn fingerprint(text: &str, options: &[String]) -> String {
    let mut all: Vec<String> = options.iter().map(|o| o.trim().to_lowercase()).collect();
    all.sort();
    let joined = format!("{}|{}", text.trim().to_lowercase(), all.join("~"));
    let digest = sha2::Sha256::digest(joined.as_bytes());
    digest[..8].iter().map(|b| format!("{b:02x}")).collect()
}

/// Second and later holders of one content fingerprint.
fn duplicate_stems(store: &JsonStore) -> Vec<Finding> {
    let mut seen: HashSet<String> = HashSet::new();
    let mut out = Vec::new();
    let mut questions: Vec<_> = store.questions().iter().collect();
    questions.sort_by(|a, b| a.id.cmp(&b.id));
    for q in questions {
        let print = fingerprint(
            &q.text,
            &q.options.iter().map(|o| o.text.clone()).collect::<Vec<_>>(),
        );
        if !seen.insert(print) {
            out.push(Finding {
                kind: "duplicate_stem",
                id: q.id.clone(),
                detail: truncate(&q.text, 80),
            });
        }
    }
    out
}

/// Option counts outside the four JAMB sets.
fn option_counts(store: &JsonStore) -> Vec<Finding> {
    store
        .questions()
        .iter()
        .filter(|q| q.options.len() != 4)
        .map(|q| Finding {
            kind: "option_count",
            id: q.id.clone(),
            detail: format!("{} options", q.options.len()),
        })
        .collect()
}

/// "Fill the gap labelled N" with nowhere to look the gap up.
fn cloze_without_passage(store: &JsonStore) -> Vec<Finding> {
    store
        .questions()
        .iter()
        .filter(|q| q.passage_id.is_none() && has_numbered_gap(&q.text))
        .map(|q| Finding {
            kind: "cloze_without_passage",
            id: q.id.clone(),
            detail: truncate(&q.text, 80),
        })
        .collect()
}

/// `gap labelled 6`, `gap numbered 3` — digits required, so "the gap in
/// understanding" and history's Middle Passage never match.
fn has_numbered_gap(text: &str) -> bool {
    let lower = text.to_lowercase();
    for marker in [
        "gap labelled",
        "gap numbered",
        "gaps labelled",
        "gaps numbered",
    ] {
        let mut rest = lower.as_str();
        while let Some(pos) = rest.find(marker) {
            rest = &rest[pos + marker.len()..];
            let digits = rest
                .trim_start()
                .chars()
                .take_while(|c| c.is_ascii_digit())
                .count();
            if digits > 0 {
                return true;
            }
        }
    }
    false
}

/// Novel vocabulary sitting in the subject bank (D35).
fn novel_leaks(store: &JsonStore) -> Vec<Finding> {
    store
        .questions()
        .iter()
        .filter(|q| {
            let blob = format!(
                "{} {}",
                q.text,
                q.options
                    .iter()
                    .map(|o| o.text.as_str())
                    .collect::<Vec<_>>()
                    .join(" ")
            )
            .to_lowercase();
            blob.contains("bepo") || blob.contains("stardom") || blob.contains("lekki")
        })
        .map(|q| Finding {
            kind: "novel_leak",
            id: q.id.clone(),
            detail: truncate(&q.text, 80),
        })
        .collect()
}

fn truncate(text: &str, max: usize) -> String {
    if text.chars().count() <= max {
        return text.to_owned();
    }
    let mut out: String = text.chars().take(max).collect();
    out.push('…');
    out
}

pub fn run(
    data: &Path,
    stdout: &mut dyn std::fmt::Write,
) -> Result<(), Box<dyn std::error::Error>> {
    let store = JsonStore::load_embedded(data).map_err(|e| format!("bank does not load: {e}"))?;
    let findings = scan(&store);

    let mut by_kind: BTreeMap<&str, Vec<&Finding>> = BTreeMap::new();
    for f in &findings {
        by_kind.entry(f.kind).or_default().push(f);
    }

    let _ = writeln!(
        stdout,
        "\nQuarantine: {} finding(s) across {} servable question(s)",
        findings.len(),
        store.question_count(),
    );
    if findings.is_empty() {
        let _ = writeln!(stdout, "Clean — nothing mechanical blocks review.");
    } else {
        for (kind, items) in &by_kind {
            let _ = writeln!(stdout, "\n  {:>4}  {kind}", items.len());
            for f in items.iter().take(25) {
                let _ = writeln!(stdout, "    {}  {}", f.id, f.detail);
            }
            if items.len() > 25 {
                let _ = writeln!(stdout, "    … and {} more", items.len() - 25);
            }
        }
    }
    let _ = writeln!(stdout, "\n(read-only — nothing written)");
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::bank::{Choice, Question};

    fn row(id: &str, text: &str) -> Question {
        Question {
            id: id.to_owned(),
            exam: "JAMB".to_owned(),
            subject: "use-of-english".to_owned(),
            year: 2025,
            source: "authored".to_owned(),
            text: text.to_owned(),
            options: vec![
                Choice {
                    id: "a".into(),
                    text: "one".into(),
                },
                Choice {
                    id: "b".into(),
                    text: "two".into(),
                },
                Choice {
                    id: "c".into(),
                    text: "three".into(),
                },
                Choice {
                    id: "d".into(),
                    text: "four".into(),
                },
            ],
            answer: "a".into(),
            subtopic_id: None,
            section: None,
            passage_id: None,
            image: None,
            emphasis: None,
            explanation: None,
            marks: 2.0,
            difficulty: 3,
            verified: false,
        }
    }

    fn store_of(name: &str, rows: Vec<Question>) -> JsonStore {
        let dir = std::env::temp_dir().join(format!("utmelab-quar-{}-{name}", std::process::id()));
        let _ = std::fs::remove_dir_all(&dir);
        std::fs::create_dir_all(&dir).expect("scratch");
        std::fs::copy("data/questions.json", dir.join("questions.json")).expect("seed");
        let mut store = JsonStore::load_embedded(&dir).expect("loads");
        let problems = store.replace_questions(rows);
        assert!(problems.is_empty(), "fixture must be valid: {problems:?}");
        let _ = std::fs::remove_dir_all(&dir);
        store
    }

    #[test]
    fn an_underlined_stem_without_emphasis_is_listed_and_one_with_is_not() {
        let mut missing = row(
            "q1",
            "Pick the option opposite to the underlined word: cogent matters.",
        );
        let mut filled = row(
            "q2",
            "Pick the option opposite to the underlined word: taciturn kept to himself.",
        );
        filled.emphasis = Some("taciturn".into());
        let plain = row("q3", "Pick the closest in meaning to: cogent matters.");
        let store = store_of("underline", vec![missing.clone(), filled, plain]);
        missing.emphasis = None;
        let findings = scan(&store);
        let kinds: Vec<(&str, &str)> = findings.iter().map(|f| (f.kind, f.id.as_str())).collect();
        assert!(kinds.contains(&("underline_missing", "q1")));
        assert!(!kinds.iter().any(|(_, id)| *id == "q2" || *id == "q3"));
    }

    #[test]
    fn a_figure_mention_without_an_image_is_listed_and_one_with_is_not() {
        use crate::bank::{ImagePosition, ImageRef};

        let bare = row("q1", "From the graph above, find x.");
        let mut carried = row("q2", "From the graph above, find y.");
        carried.image = Some(ImageRef {
            url: "https://cdn.example/y.png".into(),
            position: ImagePosition::Above,
        });
        let store = store_of("images", vec![bare, carried]);
        let findings = scan(&store);
        let missing: Vec<&str> = findings
            .iter()
            .filter(|f| f.kind == "missing_figure")
            .map(|f| f.id.as_str())
            .collect();
        assert_eq!(missing, vec!["q1"]);
    }

    #[test]
    fn a_numbered_gap_without_a_passage_is_listed() {
        let orphan = row("q1", "Fill the gap labelled 6");
        let mut linked = row("q2", "Fill the gap labelled 7");
        linked.passage_id = Some("psg_jamb_2025_eng_cloze_1".into());
        let history = row("q3", "The Middle Passage refers to:");
        let store = store_of("gaps", vec![orphan, linked, history]);
        let findings = scan(&store);
        let gaps: Vec<&str> = findings
            .iter()
            .filter(|f| f.kind == "cloze_without_passage")
            .map(|f| f.id.as_str())
            .collect();
        assert_eq!(gaps, vec!["q1"]);
    }

    #[test]
    fn the_second_holder_of_a_stem_is_the_duplicate() {
        let a = row("q1", "What is two plus two?");
        let mut b = row("q2", "  WHAT is two plus TWO?  ");
        b.options = a.options.clone();
        let store = store_of("dupes", vec![a, b]);
        let findings = scan(&store);
        let dupes: Vec<&str> = findings
            .iter()
            .filter(|f| f.kind == "duplicate_stem")
            .map(|f| f.id.as_str())
            .collect();
        assert_eq!(dupes, vec!["q2"]);
    }
}
