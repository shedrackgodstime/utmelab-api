//! Dashboard surface: customer self-service plus admin administration.
//! Session-authenticated, unversioned, excluded from public API docs.
//! Convention: `/internal/admin/*` is admin-only, everything else under
//! `/internal/*` is customer or session. Customer handlers live in
//! `dashboard`, admin handlers in `admin`; both share `store` and small
//! `core` slices only.

pub mod admin;
pub mod dashboard;

use axum::{
    routing::{get, post},
    Router,
};

use crate::{config::Config, state::AppState};

pub fn router(state: AppState, cfg: &Config) -> Router<AppState> {
    Router::new()
        .route(
            "/internal/admin/status",
            get(admin::status).route_layer(cfg.fast_timeout()),
        )
        .route(
            "/internal/login",
            post(dashboard::login).route_layer(cfg.slow_timeout()),
        )
        .route(
            "/internal/logout",
            post(dashboard::logout).route_layer(cfg.slow_timeout()),
        )
        .route(
            "/internal/keys",
            get(dashboard::my_keys).route_layer(cfg.fast_timeout()),
        )
        .route(
            "/internal/keys/create",
            post(dashboard::create_key).route_layer(cfg.slow_timeout()),
        )
        .route(
            "/internal/keys/delete",
            post(dashboard::delete_key).route_layer(cfg.slow_timeout()),
        )
        .route(
            "/internal/admin/users",
            get(admin::list_users).route_layer(cfg.fast_timeout()),
        )
        .route(
            "/internal/admin/users/role",
            post(admin::set_role).route_layer(cfg.slow_timeout()),
        )
        .route(
            "/internal/admin/keys/create",
            post(admin::create_key).route_layer(cfg.slow_timeout()),
        )
        .route(
            "/internal/admin/keys/rotate",
            post(admin::rotate).route_layer(cfg.slow_timeout()),
        )
        .route(
            "/internal/admin/keys",
            get(admin::list_keys).route_layer(cfg.fast_timeout()),
        )
        .route(
            "/internal/admin/keys/revoke",
            post(admin::revoke).route_layer(cfg.slow_timeout()),
        )
        .route(
            "/internal/admin/keys/unrevoke",
            post(admin::unrevoke).route_layer(cfg.slow_timeout()),
        )
        .route(
            "/internal/admin/reports",
            get(admin::list_reports).route_layer(cfg.fast_timeout()),
        )
        .with_state(state)
}
