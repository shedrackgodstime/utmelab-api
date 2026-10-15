//! `cargo run -- quarantine` — the mechanical-defect report, read-only.
//!
//! No judgment here: every check is decidable without reading comprehension.
//! A listed row needs a fix or a human; nothing listed may be marked `verified`
//! until its kind is resolved. This command never writes — it prints, and the
//! boot validation in `bank::JsonStore` stays the only gate.
//!
//! Kinds, and what resolves each:
//! * `underline_missing` — stem names an underlined word but carries no
//!   `Underline` mark. Resolve by backfilling the mark (the proposal script
//!   covers synonyms/antonyms; stress and sound items need hand-reading).
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
use crate::bank::InlineKind;
use crate::bank::Store;

/// One mechanical defect on one row.
#[derive(Debug)]
pub struct Finding {
    pub kind: &'static str,
    pub id: String,
    pub detail: String,
}

pub fn scan(store: &dyn Store) -> Vec<Finding> {
    let mut out = Vec::new();
    out.extend(underline_missing(store));
    out.extend(missing_figures(store));
    out.extend(duplicate_stems(store));
    out.extend(cloze_without_passage(store));
    out.extend(option_counts(store));
    out.extend(novel_leaks(store));
    out
}

/// Stems that point at an underlined word without marking one.
fn underline_missing(store: &dyn Store) -> Vec<Finding> {
    store
        .questions()
        .iter()
        .filter(|q| {
            q.text.names_underline() && !q.text.has_mark(|k| matches!(k, InlineKind::Underline))
        })
        .map(|q| Finding {
            kind: "underline_missing",
            id: q.id.clone(),
            detail: truncate(&q.text.text, 80),
        })
        .collect()
}

/// Stems that mention a figure the row does not carry.
///
/// Word-boundary matching, not substring. The old scan fired on real English:
/// "debatable" contains "table". Per-hint strictness below: `figure` and
/// `table` double as ordinary words, so only the exact word counts. A check
/// that fires wrongly is a bug in the check (HANDOFF §8). Residual edges (a
/// stem genuinely using one of these words as vocabulary) survive on
/// purpose: quarantine is a report for a human to judge, not a verdict.
fn missing_figures(store: &dyn Store) -> Vec<Finding> {
    store
        .questions()
        .iter()
        .filter(|q| {
            !q.text.has_mark(|k| matches!(k, InlineKind::Image { .. }))
                && mentions_figure_hint(&q.text.text)
        })
        .map(|q| Finding {
            kind: "missing_figure",
            id: q.id.clone(),
            detail: truncate(&q.text.text, 80),
        })
        .collect()
}

/// Does `text` mention a figure? Word-boundary matching, not substring.
/// The old scan fired on real English: "debatable" holds "table".
///
/// Per-hint strictness is deliberate linguistics, not tuning: `figure`
/// (calculations) and `table` (furniture, vocabulary, data) double as
/// ordinary words constantly, so only the exact word counts. `diagram`,
/// `graph` and `sketch` tolerate a plural `s` ("the diagrams below" is as
/// much a figure); `illustrat` is a prefix stem (every continuation is
/// figure-related); `shown` is exact. Residual edges (a stem genuinely
/// using one of these words as vocabulary, like the word-stress item
/// listing "table") survive on purpose: quarantine is a report for a human
/// to judge, not a verdict.
fn mentions_figure_hint(text: &str) -> bool {
    // (hint, plural_s_allowed, prefix_match)
    const HINTS: [(&str, bool, bool); 7] = [
        ("diagram", true, false),
        ("figure", false, false),
        ("graph", true, false),
        ("illustrat", false, true),
        ("shown", false, false),
        ("sketch", true, false),
        ("table", false, false),
    ];
    let lower = text.to_lowercase();
    let bytes = lower.as_bytes();
    let is_word = |b: u8| b.is_ascii_alphabetic() || b == b'-';
    for (hint, plural, prefix) in HINTS {
        let mut from = 0usize;
        while let Some(pos) = lower[from..].find(hint) {
            let start = from + pos;
            let end = start + hint.len();
            let before_ok = start == 0 || !is_word(bytes[start - 1]);
            let run = bytes[end..].iter().take_while(|&&b| is_word(b)).count();
            let after_ok = if prefix || run == 0 {
                true
            } else {
                plural && run == 1 && bytes[end] == b's'
            };
            if before_ok && after_ok {
                return true;
            }
            from = start + 1;
        }
    }
    false
}

fn fingerprint(text: &str, options: &[String]) -> String {
    let mut all: Vec<String> = options.iter().map(|o| o.trim().to_lowercase()).collect();
    all.sort();
    let joined = format!("{}|{}", text.trim().to_lowercase(), all.join("~"));
    let digest = sha2::Sha256::digest(joined.as_bytes());
    digest[..8].iter().map(|b| format!("{b:02x}")).collect()
}

/// Second and later holders of one content fingerprint.
fn duplicate_stems(store: &dyn Store) -> Vec<Finding> {
    let mut seen: HashSet<String> = HashSet::new();
    let mut out = Vec::new();
    let mut questions: Vec<_> = store.questions().iter().collect();
    questions.sort_by(|a, b| a.id.cmp(&b.id));
    for q in questions {
        let print = fingerprint(
            &q.text.text,
            &q.options
                .iter()
                .map(|o| o.text.text.clone())
                .collect::<Vec<_>>(),
        );
        if !seen.insert(print) {
            out.push(Finding {
                kind: "duplicate_stem",
                id: q.id.clone(),
                detail: truncate(&q.text.text, 80),
            });
        }
    }
    out
}

/// Option counts outside the four JAMB sets.
fn option_counts(store: &dyn Store) -> Vec<Finding> {
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
fn cloze_without_passage(store: &dyn Store) -> Vec<Finding> {
    store
        .questions()
        .iter()
        .filter(|q| q.passage_id.is_none() && has_numbered_gap(&q.text.text))
        .map(|q| Finding {
            kind: "cloze_without_passage",
            id: q.id.clone(),
            detail: truncate(&q.text.text, 80),
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
fn novel_leaks(store: &dyn Store) -> Vec<Finding> {
    store
        .questions()
        .iter()
        .filter(|q| {
            let blob = format!(
                "{} {}",
                q.text.text,
                q.options
                    .iter()
                    .map(|o| o.text.text.as_str())
                    .collect::<Vec<_>>()
                    .join(" ")
            )
            .to_lowercase();
            blob.contains("bepo") || blob.contains("stardom") || blob.contains("lekki")
        })
        .map(|q| Finding {
            kind: "novel_leak",
            id: q.id.clone(),
            detail: truncate(&q.text.text, 80),
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
    let store = JsonStore::load(data).map_err(|e| format!("bank does not load: {e}"))?;
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
    use crate::bank::{Choice, Inline, Question, RichText};

    fn row(id: &str, text: &str) -> Question {
        Question {
            id: id.to_owned(),
            exam: "JAMB".to_owned(),
            subject: "use-of-english".to_owned(),
            year: 2025,
            source: "authored".to_owned(),
            text: RichText::plain(text),
            options: vec![
                Choice {
                    id: "a".into(),
                    text: RichText::plain("one"),
                },
                Choice {
                    id: "b".into(),
                    text: RichText::plain("two"),
                },
                Choice {
                    id: "c".into(),
                    text: RichText::plain("three"),
                },
                Choice {
                    id: "d".into(),
                    text: RichText::plain("four"),
                },
            ],
            answer: "a".into(),
            subtopic_id: None,
            section: None,
            passage_id: None,
            explanation: None,
            marks: 2.0,
            difficulty: 3,
            verified: false,
        }
    }

    fn store_of(name: &str, rows: Vec<Question>) -> JsonStore {
        let _ = name;
        // Full catalog from disk (tests run from the repo root), fixture
        // rows swapped in — same shape the loader served before.
        let mut store = JsonStore::load("data").expect("loads");
        let problems = store.replace_questions(rows);
        assert!(problems.is_empty(), "fixture must be valid: {problems:?}");
        store
    }

    #[test]
    fn an_underlined_stem_without_a_mark_is_listed_and_one_with_is_not() {
        let missing = row(
            "q1",
            "Pick the option opposite to the underlined word: cogent matters.",
        );
        let mut filled = row(
            "q2",
            "Pick the option opposite to the underlined word: taciturn kept to himself.",
        );
        filled.text.inline.push(Inline {
            start: 49,
            len: 8,
            kind: InlineKind::Underline,
        });
        let plain = row("q3", "Pick the closest in meaning to: cogent matters.");
        let store = store_of("underline", vec![missing, filled, plain]);
        let findings = scan(&store);
        let kinds: Vec<(&str, &str)> = findings.iter().map(|f| (f.kind, f.id.as_str())).collect();
        assert!(kinds.contains(&("underline_missing", "q1")));
        assert!(!kinds.iter().any(|(_, id)| *id == "q2" || *id == "q3"));
    }

    #[test]
    fn a_figure_mention_without_an_image_mark_is_listed_and_one_with_is_not() {
        use crate::bank::{ImagePosition, InlineKind};

        let bare = row("q1", "From the graph above, find x.");
        let mut carried = row("q2", "From the graph above, find y.");
        carried.text.inline.push(Inline {
            start: 27,
            len: 0,
            kind: InlineKind::Image {
                url: "https://cdn.example/y.png".into(),
                position: ImagePosition::Above,
                alt: None,
            },
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
    fn a_figure_word_inside_real_english_does_not_count() {
        // "debatable" held "table" and fired under the old substring scan.
        // Word-boundary matching fixes that one; `q1` is now clean.
        let debate = row(
            "q1",
            "Between Achebe and Soyinka it is debatable who is more enigmatic.",
        );
        let store = store_of("english", vec![debate]);
        let findings = scan(&store);
        assert!(
            !findings.iter().any(|f| f.kind == "missing_figure"),
            "\"debatable\" is prose, not a figure: {:?}",
            findings.iter().map(|f| f.id.as_str()).collect::<Vec<_>>()
        );
    }

    #[test]
    fn a_vocabulary_word_that_names_a_figure_still_gets_reported() {
        // The honest residual. A word-stress item listing "table" as one of
        // its words is indistinguishable from a figure reference by any
        // heuristic — so quarantine *reports* it (a human judges it) and,
        // crucially, the finding never voids `verified` (see `derive_verified`).
        // A report a human can dismiss beats a silent false positive.
        let stress = row(
            "q2",
            "Choose the word with a different stress pattern: commit · begin · record · table.",
        );
        let store = store_of("stress", vec![stress]);
        let findings = scan(&store);
        let missing: Vec<&str> = findings
            .iter()
            .filter(|f| f.kind == "missing_figure")
            .map(|f| f.id.as_str())
            .collect();
        assert_eq!(
            missing,
            vec!["q2"],
            "reported for a human, never auto-voided"
        );
    }

    #[test]
    fn plurals_still_count_as_figures_but_numbers_do_not() {
        // "diagrams" is as much a figure as "diagram".
        assert!(mentions_figure_hint("use the diagrams below"));
        // "diagrammatic" is prose, not a figure.
        assert!(!mentions_figure_hint("a diagrammatic explanation"));
        // "figures" here means numbers, not diagrams — figure/table are
        // exact-word only because they double as ordinary words.
        assert!(!mentions_figure_hint(
            "the manager knew the figures would not add up"
        ));
        assert!(mentions_figure_hint("see the figure below"));
        // Prefix stem: every continuation of illustrat is figure-related.
        assert!(mentions_figure_hint("as illustrated in the passage"));
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
