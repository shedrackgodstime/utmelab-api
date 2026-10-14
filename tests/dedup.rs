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

use utmelab_api::{JsonStore, Question};

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

/// Lowercased letters and digits, nothing else — every script survives.
fn norm(text: &str) -> String {
    text.chars()
        .filter(|c| c.is_alphanumeric())
        .flat_map(|c| c.to_lowercase())
        .collect()
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
