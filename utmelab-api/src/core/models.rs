use serde::Serialize;

#[derive(Serialize)]
pub struct TableRef {
    pub name: String,
}

#[derive(Serialize)]
pub struct ServiceStatus {
    pub service: &'static str,
    pub has_sync: bool,
    pub contract_ok: bool,
    pub gate_rejections: u64,
    pub pulls_applied: u64,
    pub pulls_empty: u64,
}

#[derive(Serialize)]
pub struct RowPage {
    pub cols: Vec<String>,
    pub rows: Vec<Vec<String>>,
}

#[derive(serde::Deserialize)]
pub struct PrefixBody {
    pub prefix: String,
}
