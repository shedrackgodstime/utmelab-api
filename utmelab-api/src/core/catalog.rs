//! Pure catalog logic. No axum, no database client: every function here
//! is a total transformation of plain data, unit-testable with no runtime.

use super::models::TableRef;

pub fn to_refs(names: Vec<String>) -> Vec<TableRef> {
    names.into_iter().map(|name| TableRef { name }).collect()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn to_refs_preserves_names_in_order() {
        let out = to_refs(vec!["b".to_string(), "a".to_string()]);
        let names: Vec<_> = out.into_iter().map(|t| t.name).collect();
        assert_eq!(names, vec!["b".to_string(), "a".to_string()]);
    }
}
