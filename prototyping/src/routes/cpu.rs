pub async fn cpu_work() -> String {
    tokio::task::spawn_blocking(|| {
        let mut x: u64 = 0;
        for i in 0..100_000 {
            x = x.wrapping_add(i ^ (i << 3));
        }
        format!("{x}")
    })
    .await
    .unwrap_or_else(|_| "busy".to_string())
}
