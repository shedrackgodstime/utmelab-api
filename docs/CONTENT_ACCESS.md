# Content access model

**Status:** target architecture. The current API still uses `x-api-key` for backend-to-API calls.
Content downloads move to short-lived RS256 JWTs.

## Goal

Protect UTME Lab's private API credentials while letting approved client applications consume content directly.

The API never requires a browser, mobile, or desktop app to carry a master API key. A credential shipped inside a client is not secret.

## Target architecture

```text
client app
  │
  │ user session
  ▼
trusted backend (Dioxus server)
  │
  │ x-api-key, server-side only
  ▼
utmelab-api token endpoint
  │
  │ short-lived RS256 JWT
  ▼
client app
  │
  │ Authorization: Bearer <jwt>
  ▼
utmelab-api content routes
  │
  ▼
UTME Lab content
```

The trusted backend holds the paid API credential. It exchanges that credential for a short-lived token. The client uses the token directly against `utmelab-api`, so bulk content does not pass through the backend.

## Token endpoint

`POST /api/v1/tokens`

- Authenticate with `x-api-key`
- Require `read:catalog`
- Return a short-lived RS256 JWT

## Token claims

- `iss`: token issuer
- `aud`: requested package or exam
- `sub`: trusted backend/client identity
- `scope`: `read:catalog`
- `exp`: about 5 minutes
- `iat`: issued time
- `jti`: unique token id
- `kid`: signing key id

## Verification

Content routes verify RS256 signature, issuer, audience, scope, expiry, and `kid`. Verification fails closed.

Clients send tokens only in:

```text
Authorization: Bearer <jwt>
```

Normal downloads do not use query-string tokens.

## Implementation tree

```text
src/auth/
  mod.rs       # Auth struct + scope vocabulary
  api_key.rs   # x-api-key gate + AuthedKey extractor
  token.rs     # RS256 issuer/verifier + SignedContentToken extractor
  session.rs   # internal dashboard session only
src/api/v1/
  tokens.rs    # POST /api/v1/tokens, requires AuthedKey + read:catalog
src/state.rs   # AppState carries signing key id + public verification key
src/config.rs  # JWT_SIGNING_KEY_PEM, JWT_KEY_ID, JWT_ISSUER, JWT_TTL_SECS
```

## Security rules

- No paid secret in browser, mobile, or desktop clients.
- API key stays server-side only.
- Scopes stay equal to enforcement.
- The signing private key is server-only.
- Clients verify with public keys only.
- Administrative scopes must never be issued to public applications.

## Public content and caching

Content that is intentionally public may be served through a CDN or cached edge layer. Caching must not bypass authorization for protected content.

An access token does not make confidential content public. It only limits what that client may read.
