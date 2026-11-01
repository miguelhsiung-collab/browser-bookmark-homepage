# Host and URL filters for frequent sites

## Skip URL path patterns (case-insensitive)

Treat as auth / session noise; do not use these URLs as the card link. Still count the host if other clean URLs exist.

- `/login`, `/signin`, `/sign-in`, `/signup`, `/sign-up`
- `/oauth`, `/authorize`, `/auth/`, `/sso`, `/saml`
- `/accounts/Login`, `/Session`, `password`, `logout`
- query keys: `client_id=`, `redirect_uri=`, `code=`, `state=`, `challenge=`, `returnTo=`
- path/query tokens: `loginDeepControl`, `join-team`

## Prefer clean home URLs

When picking the display URL for a host:

1. Bookmark URL whose path is `/` or a short marketing path.
2. Else `https://{host}/`.
3. Never prefer a URL containing the skip patterns above.

## Optional host denylist

Skip counting entirely (local / non-web):

- `localhost`, `127.0.0.1`, `0.0.0.0`
- `*.local`
- bare IP addresses (unless the user asks to keep intranet tools)

## Registrable host key

Normalize: lowercase host, strip leading `www.`. Keep meaningful subdomains (`movie.douban.com`, `mp.weixin.qq.com`) as distinct keys.


## Auth host denylist

Skip counting these hosts entirely:

- `accounts.*`, `login.*`, `auth.*` prefixes
- `accounts.google.com`, `login.microsoftonline.com`, `authenticator.cursor.sh`, `*.auth0.com`
