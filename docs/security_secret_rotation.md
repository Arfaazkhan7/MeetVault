# MeetVault — JWT Secret Management & Key Rotation Guide

## Overview

MeetVault uses JSON Web Tokens (JWT) for stateless authentication. In production, JWT signing and verification require a cryptographically secure key of at least 32 characters (`HS256`, `HS384`, or `HS512`).

MeetVault enforces strict production startup checks to prevent startup when using missing, weak, or placeholder secrets.

---

## Configuration Reference

| Environment Variable | Required in Prod | Default | Description |
|----------------------|------------------|---------|-------------|
| `JWT_SECRET` | **Yes** | Dev secret | The active secret key used to sign all new access and refresh tokens. Must be >= 32 random characters in production. |
| `JWT_PREVIOUS_SECRETS` | Optional | `""` | Comma-separated or JSON array of retired secrets still accepted for decoding during rotation grace periods. |
| `JWT_ALGORITHM` | Optional | `HS256` | Explicit signing algorithm. Allowed: `HS256`, `HS384`, `HS512`. The `none` algorithm is strictly rejected. |
| `JWT_ISSUER` | Optional | `meetvault-api` | Expected `iss` claim. |
| `JWT_AUDIENCE` | Optional | `meetvault-client` | Expected `aud` claim. |

---

## 1. Zero-Downtime Secret Rotation Procedure

Follow this workflow to rotate keys without logging out active users or causing service disruption:

### Step 1: Generate a new secret
Generate a 256-bit cryptographic secret:
```bash
openssl rand -hex 32
```

### Step 2: Configure rotation grace period
In your production environment (e.g. Render Dashboard or Kubernetes Secret):
1. Copy the current value of `JWT_SECRET`.
2. Set or append it to `JWT_PREVIOUS_SECRETS`. If rotating multiple times, separate previous keys with commas:
   ```env
   JWT_PREVIOUS_SECRETS="<current_active_secret>"
   ```
3. Set `JWT_SECRET` to the new secret generated in Step 1:
   ```env
   JWT_SECRET="<new_32_plus_char_secret>"
   ```

### Step 3: Deploy backend
Deploy the updated configuration.
- All **new** tokens issued via `/auth/login`, `/auth/login/workspace`, etc., will be signed using the new `JWT_SECRET`.
- Existing unexpired tokens will be validated against `JWT_PREVIOUS_SECRETS`.
- When an active user calls `/auth/refresh`, their old token is validated via `JWT_PREVIOUS_SECRETS`, and a new token pair signed with the new `JWT_SECRET` is returned.

### Step 4: Decommission old secrets after grace period
After the refresh token validity period (default 7 days) has elapsed, remove the old secret from `JWT_PREVIOUS_SECRETS`:
```env
JWT_PREVIOUS_SECRETS=""
```
Redeploy. The old key is now completely retired.

---

## 2. Emergency Compromise Invalidation Procedure

If a secret is leaked, exposed in logs, or compromised:

1. **Immediate Revocation**: Remove the compromised secret from **both** `JWT_SECRET` and `JWT_PREVIOUS_SECRETS`.
2. Generate a new secret:
   ```bash
   openssl rand -hex 32
   ```
3. Set `JWT_SECRET="<new_secret>"` and clear `JWT_PREVIOUS_SECRETS=""`.
4. Redeploy immediately.
5. **Outcome**: All tokens forged or signed by the compromised secret will immediately fail validation with HTTP 401 Unauthorized across all endpoints. Legitimate users will be prompted to re-login.

---

## 3. Production Security Guarantees

1. **Fast-fail Startup**: If `ENVIRONMENT` is `production`, `prod`, or `staging`, MeetVault validates `JWT_SECRET` at boot. If the secret is missing, under 32 characters, has low entropy, or matches known placeholders, the server refuses to start with an explicit error.
2. **Algorithm Whitelist**: The header algorithm claim `alg` is inspected prior to signature validation. Algorithm substitution attacks and `alg: "none"` tokens are rejected unconditionally.
3. **Claim Verification**: `sub`, `type`, `exp`, `iss`, and `aud` are strictly validated on every request.
4. **Dev Bypass Lockdown**: Development fallback tokens (prefixed with `mv-local-` or `mail-`) are hard-disabled in production and staging environments.
