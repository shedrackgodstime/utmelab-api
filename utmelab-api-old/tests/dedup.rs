//! No duplicates in the bank (D72) — enforced, not promised.
//!
//! Identity here is the **normalized stem plus the normalized options**.
//! Deliberately *not* `content_fingerprint`: that one folds in the
//! explanation, so it answers "has this row changed?" (which is what the
//! Turso version gate wants) and cannot answer "is this question in the bank
//! twice?". Two copies of one question with different explanations would sail
//! past it.
//!
//! Normalization keeps every unicode letter and digit. An earlier audit used
//! `[^a-z0-9]`, which deleted Arabic and Hausa text outright and reported 66
//! good rows as one duplicate — the false alarm that made this test worth
//! writing.
//!
//! A shared stem with different options is not automatically a duplicate: two
//! papers ask "which of these is not a source document?" with different option
//! sets, and both rows are real questions. Those pairs are reviewed and listed
//! below, so a *new* one fails the test until a person looks at it.

use std::collections::HashMap;

use utmelab_api::{Choice, JsonStore, Question};

/// Shared stems a person has checked and kept, with the reason. Add a row here
/// only after reading both questions and confirming they ask different things.
const REVIEWED_SHARED_STEMS: &[(&str, &str, &str)] = &[
    (
        "q_claim_2025_biology_74441",
        "q_claim_2025_biology_74496",
        "different figures: a cell organelle versus a mollusc's body parts",
    ),
    (
        "q_claim_2025_computer-studies_64098",
        "q_claim_2025_computer-studies_64379",
        "different item groups: memory types versus storage media",
    ),
];

fn bank() -> JsonStore {
    let dir = std::path::PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("data");
    JsonStore::load(&dir).expect("bank loads")
}

/// Lowercased letters and digits, nothing else — every script survives. Right
/// for "are these two rows the same question": tolerant of markup noise, and it
/// is the normalizer whose `[^a-z0-9]` ancestor once called 66 Arabic and Hausa
/// rows one duplicate.
fn norm(text: &str) -> String {
    text.chars()
        .filter(|c| c.is_alphanumeric())
        .flat_map(|c| c.to_lowercase())
        .collect()
}

/// What a reader sees: spacing collapsed, **every character kept — including
/// case**. Options are compared with this, not with `norm`: dropping
/// punctuation collapses `x = 10, y = 6` into `x = 10 y = 6` and invents a
/// score of mathematics phantoms, while folding case erases the capitals that
/// *are* the answer in a word-stress row (`SImilarly` vs `simiLARly`).
fn display_norm(text: &str) -> String {
    text.split_whitespace().collect::<Vec<_>>().join(" ")
}

/// What makes two rows the same question.
fn identity(q: &Question) -> String {
    let options: Vec<String> = q
        .options
        .iter()
        .map(|o| format!("{}\u{1e}{}", o.id, norm(&o.text.text)))
        .collect();
    format!("{}|{}", norm(&q.text.text), options.join("|"))
}

#[test]
fn no_two_rows_are_the_same_question() {
    let store = bank();
    let mut seen: HashMap<String, String> = HashMap::new();
    let mut duplicates: Vec<String> = Vec::new();
    for q in store.questions() {
        let id = identity(q);
        match seen.get(&id) {
            Some(first) => duplicates.push(format!("{first} == {}", q.id)),
            None => {
                seen.insert(id, q.id.clone());
            }
        }
    }
    assert!(
        duplicates.is_empty(),
        "the bank holds the same question twice: {duplicates:?} — keep one copy, \
         and record why in REVIEWED_SHARED_STEMS if they are genuinely different"
    );
}

#[test]
fn ids_are_unique() {
    let store = bank();
    let mut seen: HashMap<&str, usize> = HashMap::new();
    for q in store.questions() {
        *seen.entry(q.id.as_str()).or_default() += 1;
    }
    let repeated: Vec<(&str, usize)> = seen.into_iter().filter(|(_, n)| *n > 1).collect();
    assert!(repeated.is_empty(), "repeated ids: {repeated:?}");
}

/// Same question, different option order — always a duplicate, never a pair to
/// review. This is the one shape where the answer letter can silently differ
/// while the question does not.
#[test]
fn no_shared_stem_carries_the_same_key_with_different_options() {
    let store = bank();
    let mut by_stem: HashMap<String, Vec<&Question>> = HashMap::new();
    for q in store.questions() {
        by_stem.entry(norm(&q.text.text)).or_default().push(q);
    }
    let mut suspicious: Vec<String> = Vec::new();
    for (stem, group) in &by_stem {
        if group.len() < 2 {
            continue;
        }
        let mut keys: Vec<(&str, String)> = group
            .iter()
            .map(|q| {
                let options: Vec<String> = q.options.iter().map(|o| o.text.text.clone()).collect();
                (q.id.as_str(), options.join("|"))
            })
            .collect();
        keys.sort();
        keys.dedup_by(|a, b| a.0 == b.0 && a.1 == b.1);
        if keys.len() == 1 {
            continue; // identical options: caught by identity, if the stems match too
        }
        let answers: std::collections::HashSet<&str> =
            group.iter().map(|q| q.answer.as_str()).collect();
        if answers.len() == 1 {
            suspicious.push(format!(
                "{stem:.40}… keyed {} by {}",
                group[0].answer,
                group
                    .iter()
                    .map(|q| q.id.as_str())
                    .collect::<Vec<_>>()
                    .join(", ")
            ));
        }
    }
    assert!(
        suspicious.is_empty(),
        "same stem, same key, different options — one copy's key is probably wrong: {suspicious:?}"
    );
}

/// Every shared-stem pair in the bank is one a person read. A new pair stops
/// the suite until someone decides whether it is one question or two.
#[test]
fn shared_stems_are_all_reviewed() {
    let store = bank();
    let mut by_stem: HashMap<String, Vec<&str>> = HashMap::new();
    for q in store.questions() {
        by_stem
            .entry(norm(&q.text.text))
            .or_default()
            .push(q.id.as_str());
    }
    let mut unpaired: Vec<(String, Vec<&str>)> = Vec::new();
    for (stem, group) in &by_stem {
        if group.len() < 2 {
            continue;
        }
        let reviewed = group.iter().all(|id| {
            REVIEWED_SHARED_STEMS.iter().any(|(a, b, _)| {
                (*a == *id && group.contains(b)) || (*b == *id && group.contains(a))
            })
        });
        if !reviewed {
            unpaired.push((stem.clone(), group.clone()));
        }
    }
    assert!(
        unpaired.is_empty(),
        "unreviewed shared stems: {unpaired:?} — read both rows, then add the pair \
         to REVIEWED_SHARED_STEMS with its reason"
    );
}

/// The keyed option must be the **only** option carrying its text. A repeated
/// keyed option means two letters are correct, so the row cannot be scored
/// honestly — the defect the option audit found in two rows on 2026-10-14,
/// where "معلمون" and "Additive" each appeared twice and the key sat on one of
/// the copies.
#[test]
fn the_keyed_option_is_unique_among_its_options() {
    let store = bank();
    let mut broken: Vec<String> = Vec::new();
    for q in store.questions() {
        let keyed: Vec<&Choice> = q.options.iter().filter(|o| o.id == q.answer).collect();
        if keyed.is_empty() {
            continue; // the loader already refuses a key outside the options
        }
        let answer_text = &keyed[0].text.text;
        let twins: Vec<&str> = q
            .options
            .iter()
            .filter(|o| display_norm(&o.text.text) == display_norm(answer_text))
            .map(|o| o.id.as_str())
            .collect();
        if twins.len() > 1 {
            broken.push(format!(
                "{} [{}]: key {} shares its text with {:?}",
                q.id, q.subject, q.answer, twins
            ));
        }
    }
    assert!(
        broken.is_empty(),
        "a keyed option repeated makes two letters correct: {broken:?}"
    );
}

/// Repeated *wrong* options are a sloppiness, not a scoring defect: the key is
/// still unique, so every candidate gets the same verdict. Three rows carry
/// one today (geography_75506, mathematics_74091, mathematics_74092) and are
/// recorded here rather than fixed, because repairing them means inventing an
/// option the paper never carried. A new one fails the test so the count stays
/// deliberate.
#[test]
fn repeated_wrong_options_stay_at_the_reviewed_count() {
    const REVIEWED: &[&str] = &[
        "q_claim_2025_geography_75506",
        "q_claim_2025_mathematics_74091",
        "q_claim_2025_mathematics_74092",
    ];
    let store = bank();
    let mut cosmetic: Vec<&str> = Vec::new();
    for q in store.questions() {
        let mut seen: HashMap<String, usize> = HashMap::new();
        for o in &q.options {
            *seen.entry(display_norm(&o.text.text)).or_default() += 1;
        }
        let repeats = seen.values().filter(|n| **n > 1).count();
        let keyed_repeats = q
            .options
            .iter()
            .filter(|o| o.id == q.answer)
            .filter(|o| seen[&display_norm(&o.text.text)] > 1)
            .count();
        if repeats > 0 && keyed_repeats == 0 {
            cosmetic.push(q.id.as_str());
        }
    }
    cosmetic.sort();
    assert_eq!(
        cosmetic, REVIEWED,
        "rows with a repeated wrong option changed — review the new ones and update the list"
    );
}
