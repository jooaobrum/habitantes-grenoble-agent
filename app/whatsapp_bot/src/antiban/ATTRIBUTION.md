# Attribution

This directory vendors 4 files from the [`baileys-antiban`](https://github.com/kobie3717/baileys-antiban)
project (npm package `baileys-antiban@4.10.0`), MIT licensed.

- **Source repository:** https://github.com/kobie3717/baileys-antiban
- **Source commit:** `0c805095bf7576e7885932400203e984e55fa90d`
- **Corresponds to npm version:** `baileys-antiban@4.10.0`

## Vendored files

Copied unchanged from `src/` in the source repo:

- `rateLimiter.ts` — account-wide send budget + jittered delay
- `health.ts` — ban-risk scoring from disconnect/loggedOut/403/463 signals
- `warmup.ts` — gated daily safety valve after (re)pair
- `webhooks.ts` — alert sender (Telegram/Discord/generic webhook)

All four are pure, dependency-free, zero-import modules; the only network I/O across
them is `webhooks.ts`'s `fetch()` call to an operator-configured alert URL.

Only these 4 files were vendored. The source package's other ~43 modules — including
device/session fingerprinting, stealth connection behavior, fake human-typing/entropy
injection, and multi-instance coordination — were deliberately **not** vendored; see
`.specs/features/whatsapp-antiban-hardening/design.md` for the exclusion rationale.

## License

```
MIT License

Copyright (c) 2026 Kobus Wentzel

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```
