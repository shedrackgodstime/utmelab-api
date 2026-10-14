//! Per-topic readiness (D68): blueprint × coverage on the real bank.
//!
//! File-based, no network: `JsonStore` + `blueprints.json`. Invariants hold
//! on any bank state; the maths snapshot documents today (2026-10-14).

use utmelab_api::{JsonStore, Store, load_blueprints, per_topic};

fn data_dir() -> std::path::PathBuf {
    std::path::PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("data")
}

#[test]
fn maths_slice_is_fully_measured_and_internally_consistent() {
    let store = JsonStore::load(data_dir()).expect("bank loads");
    let bps = load_blueprints(&data_dir()).expect("blueprints load");
    let r = per_topic(&store, &bps, "JAMB", "mathematics", None);

    // All 23 measured topics resolve; nothing unmeasured in the slice.
    assert_eq!(r.total(), 23, "maths has 23 measured topics");
    assert_eq!(r.unmeasured, 0, "no unmapped rows in the slice");
    // Untagged verified rows are counted, never assigned (D68). The count fell
    // from 2 to 0 on 2026-10-14, when 74094 and 74200 were filed under
    // binary-operations — which is also what closed that topic. What matters is
    // that the number is *derived*, so it is pinned as "these rows are not in
    // any pool", not as a constant: tagging a row must move it and nothing else.
    let page = store.questions_page(
        utmelab_api::QuestionFilter {
            exam: Some("JAMB"),
            subject: Some("mathematics"),
            ..Default::default()
        },
        1,
        utmelab_api::MAX_PER_PAGE,
    );
    let untagged_verified = page
        .questions
        .iter()
        .filter(|q| q.verified && q.subtopic_id.is_none())
        .count();
    assert_eq!(
        r.unattributed, untagged_verified,
        "unattributed is exactly the verified rows no topic claims"
    );

    for t in &r.topics {
        assert!(!t.name.is_empty(), "topic {} resolves", t.topic);
        assert_eq!(t.need, t.expected.ceil() as u32, "need is ceil");
        assert!(
            t.deduped <= t.verified && t.verified <= t.held,
            "deduped <= verified <= held for {}",
            t.topic
        );
        assert_eq!(
            t.ready,
            t.deduped as u32 >= t.need,
            "ready flag matches the rule for {}",
            t.topic
        );
    }
    assert_eq!(
        r.ready,
        r.topics.iter().filter(|t| t.ready).count(),
        "ready count consistent"
    );
    assert_eq!(
        r.complete,
        r.ready == r.total(),
        "complete iff every topic ready"
    );
    // Coverage conservation: topic verified + unattributed == subject total.
    let subject_verified: usize =
        r.topics.iter().map(|t| t.verified).sum::<usize>() + r.unattributed;
    let cf = utmelab_api::QuestionFilter {
        exam: Some("JAMB"),
        subject: Some("mathematics"),
        verified: Some(true),
        ..Default::default()
    };
    let total = store
        .questions_page(cf, 1, utmelab_api::MAX_PER_PAGE)
        .total_records;
    assert_eq!(
        subject_verified, total,
        "no verified row lost or double-counted"
    );
}
