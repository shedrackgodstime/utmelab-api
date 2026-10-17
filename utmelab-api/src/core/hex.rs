//! Lowercase hex encoding. One spelling for every digest, token, and random
//! id the crate renders, so key prefixes, session tokens, report ids, and
//! ETags can never drift into two different encodings.

/// Encode bytes as lowercase hex (two chars per byte).
pub fn encode(bytes: &[u8]) -> String {
    const DIGITS: &[u8; 16] = b"0123456789abcdef";
    let mut out = String::with_capacity(bytes.len() * 2);
    for &b in bytes {
        out.push(DIGITS[(b >> 4) as usize] as char);
        out.push(DIGITS[(b & 0x0f) as usize] as char);
    }
    out
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn encodes_lowercase_and_pads() {
        assert_eq!(encode(&[0x00, 0x0f, 0xa5, 0xff]), "000fa5ff");
    }

    #[test]
    fn empty_is_empty() {
        assert_eq!(encode(&[]), "");
    }
}
