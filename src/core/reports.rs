//! Report rules. Pure validation only; storage lives in `store`.
//!
//! Reasons are a closed set so flags aggregate instead of scattering
//! across free text. Detail is capped context, never PII.

/// Flags one key may file per UTC day. Generous for humans, useless
/// for floods.
pub const MAX_REPORTS_PER_DAY: u32 = 10;
/// Optional context cap, counted in characters, not bytes.
pub const MAX_DETAIL_CHARS: usize = 500;
/// Per-minute report attempts per key, enforced by the shared limiter.
pub const MAX_REPORTS_PER_MINUTE: u32 = 10;

/// Reportable content kinds. One endpoint serves all of them; a new
/// kind is one match arm in the existence check, never a new route.
pub fn parse_target_type(s: &str) -> Result<&'static str, crate::error::AppError> {
    match s {
        "question" => Ok("question"),
        "topic" => Ok("topic"),
        "passage" => Ok("passage"),
        "novel" => Ok("novel"),
        _ => Err(crate::error::AppError::BadRequest(
            "target_type must be one of: question, topic, passage, novel.".to_string(),
        )),
    }
}

/// Closed reason set. Unknown strings reject loudly: an open text
/// field would make every flag its own category.
pub fn parse_reason(s: &str) -> Result<&'static str, crate::error::AppError> {
    match s {
        "wrong_answer" => Ok("wrong_answer"),
        "unclear_stem" => Ok("unclear_stem"),
        "broken_option" => Ok("broken_option"),
        "wrong_explanation" => Ok("wrong_explanation"),
        "other" => Ok("other"),
        _ => Err(crate::error::AppError::BadRequest(
            "reason must be one of: wrong_answer, unclear_stem, broken_option, wrong_explanation, other."
                .to_string(),
        )),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn known_reasons_pass_through() {
        for r in [
            "wrong_answer",
            "unclear_stem",
            "broken_option",
            "wrong_explanation",
            "other",
        ] {
            assert_eq!(parse_reason(r).unwrap(), r);
        }
    }

    #[test]
    fn unknown_reasons_reject() {
        assert!(parse_reason("").is_err());
        assert!(parse_reason("WRONG_ANSWER").is_err());
        assert!(parse_reason("wrong answer").is_err());
    }

    #[test]
    fn target_types_are_closed() {
        for t in ["question", "topic", "passage", "novel"] {
            assert_eq!(parse_target_type(t).unwrap(), t);
        }
        assert!(parse_target_type("").is_err());
        assert!(parse_target_type("subject").is_err());
        assert!(parse_target_type("Question").is_err());
    }
}
