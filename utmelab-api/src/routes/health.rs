use axum::extract::State;

use crate::state::HealthState;

// Takes the narrow substate (not the full AppState) so the wiring stays
// honest even though this handler needs nothing from it.
pub async fn health(_s: State<HealthState>) -> &'static str {
    "ok"
}
