use std::time::Duration;

pub async fn slow() -> &'static str {
    tokio::time::sleep(Duration::from_millis(50)).await;
    "done"
}
