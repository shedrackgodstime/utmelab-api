//! A question that promises a stimulus the bank does not hold is a coin
//! flip, not a question.
//!
//! Six rows sat in the bank in that shape for years (five English
//! comprehension questions pointing at a bird passage, one commerce question
//! pointing at a data block), all harvested from a source that published the
//! stimulus on the page — `tools/harvest.py` read it into a `ref` field
//! nothing consumed, and the guard written to catch that was inert because
//! nothing ever set `passage`. Both are fixed; this test is the third leg.
//!
//! A row may legitimately carry its stimulus **inline**. This source renders
//! it three ways: above the stem (English — recovered 2026-10-14), inside the
//! `<h1>` so the harvester merged it into the stem (Arabic, French, Hausa,
//! Igbo — 33 rows, answerable as served), or as a figure mark on the row.
//! Only the shape that is genuinely broken is a stem that announces a stimulus
//! and then does not have one anywhere.
//!
//! The other failure mode is invisible to any bank-side test: the birds passage
//! rows announced nothing in the stem — the announcement was on the *page* — so
//! no test could catch them. That one is why `tools/harvest.py` reads the
//! stimulus off the page and refuses a row whose stimulus it could not
//! extract, and why `tools/recover_passages.py` exists for what is already in.

fn bank() -> utmelab_api::JsonStore {
    let dir = std::path::PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("data");
    utmelab_api::JsonStore::load(&dir).expect("bank loads")
}

/// What a stem can promise that the row must then deliver.
const PROMISED_STIMULUS: &[(&str, &str)] = &[
    ("passage below", "a passage"),
    ("passage above", "a passage"),
    ("following passage", "a passage"),
    ("read the passage", "a passage"),
    ("according to the passage", "a passage"),
    ("the text below", "a passage or inline text"),
    ("according to the text", "a passage or inline text"),
    ("use the information below", "a passage"),
    ("use the information", "a passage"),
    ("following the data", "a passage"),
    ("the table below", "a passage"),
];

/// A gap question can announce its stimulus two ways: by carrying the sentence
/// with the gap inline (`74804`–`74811`, self-contained and fine), or by
/// pointing at a numbered gap in a passage we do not hold (`74779`, a coin
/// flip that was marked verified for years). Only the second is broken.
const GAP_POINTER: &str = "gap labelled";

#[test]
fn a_gap_pointer_row_carries_its_sentence_or_its_passage() {
    let store = bank();
    let known: Vec<&str> = store.passages().iter().map(|p| p.id.as_str()).collect();
    let mut broken: Vec<String> = Vec::new();
    for q in store.questions() {
        let text = q.text.text.to_lowercase();
        if !text.contains(GAP_POINTER) {
            continue;
        }
        let carries = q
            .passage_id
            .as_deref()
            .is_some_and(|id| known.contains(&id))
            || q.text
                .inline
                .iter()
                .any(|m| matches!(m.kind, utmelab_api::InlineKind::Image { .. }));
        if !carries {
            broken.push(format!(
                "{} [{}]: points at a gap it does not carry",
                q.id, q.subject
            ));
        }
    }
    assert!(
        broken.is_empty(),
        "a numbered gap with no sentence and no passage is a coin flip: {broken:?}"
    );
}

/// How much text after the announcement still counts as a stimulus carried
/// inline. A question is one sentence; 200 characters is three or four, which
/// is where the language subjects' merged stems sit comfortably above and the
/// broken English rows sit far below (theirs were 40-60 characters).
const INLINE_STIMULUS_CHARS: usize = 200;

#[test]
fn no_row_promises_a_stimulus_it_does_not_carry() {
    let store = bank();
    let known: Vec<&str> = store.passages().iter().map(|p| p.id.as_str()).collect();
    let mut broken: Vec<String> = Vec::new();
    for q in store.questions() {
        let text = q.text.text.to_lowercase();
        let announcement = PROMISED_STIMULUS
            .iter()
            .find(|(needle, _)| text.contains(needle))
            .map(|(needle, what)| (*needle, *what));
        let Some((needle, what)) = announcement else {
            continue;
        };
        // A figure IS the stimulus when the stem points at something drawn.
        let carries_figure = q
            .text
            .inline
            .iter()
            .any(|m| matches!(m.kind, utmelab_api::InlineKind::Image { .. }));
        let carries_passage = q
            .passage_id
            .as_deref()
            .is_some_and(|id| known.contains(&id));
        // Or the stimulus rides in the stem itself, as it does for Arabic,
        // French, Hausa and Igbo on this source.
        let after = text
            .split(needle)
            .nth(1)
            .unwrap_or_default()
            .trim()
            .to_owned();
        let carries_inline = after.chars().count() >= INLINE_STIMULUS_CHARS;
        if !(carries_passage || carries_figure || carries_inline) {
            broken.push(format!(
                "{} [{}]: promises {what} but carries none (stem tail: {:.40})",
                q.id, q.subject, after
            ));
        }
    }
    assert!(
        broken.is_empty(),
        "a question that points at a stimulus we do not hold is not answerable: {broken:?}"
    );
}

#[test]
fn every_passage_id_resolves_and_every_passage_is_used() {
    let store = bank();
    let known: Vec<&str> = store.passages().iter().map(|p| p.id.as_str()).collect();
    for q in store.questions() {
        if let Some(id) = q.passage_id.as_deref() {
            assert!(
                known.contains(&id),
                "{} points at a missing passage: {id}",
                q.id
            );
        }
    }
    // A passage nobody reads is either a mistake or a stub we should notice.
    let used: Vec<&str> = store
        .questions()
        .iter()
        .filter_map(|q| q.passage_id.as_deref())
        .collect();
    let unused: Vec<&&str> = known.iter().filter(|id| !used.contains(id)).collect();
    assert!(unused.is_empty(), "passages with no question: {unused:?}");
}
