# Astra actual browser validation after implementation

Base: http://127.0.0.1:8018, isolated pm-uiux-button-task41 preview.
- evidence.json: 16 paths x 1280/390, all 200, no console/pageerror or document horizontal overflow.
- save-checks.json: created document 3, title/body persisted across reload; mocked 400/409 reasons and draft body preserved.
- portfolio-checks.json: unsaved textarea differs from downloaded saved content; save persists edited body.
- portfolio-conflict.json: saved export updated; real stale-version response preserves submitted body without overwriting saved body.
- failure-extra.json: denied clipboard + cancelled prompt returns false without success text; mocked login HTML 200 is rejected as save, mobile note return blocked with content preserved.
- date-checks.json: quick and project form date starts blank, explicit suggestion apply; org 3 weekdays=2026-10-07, project 2 override 5 weekdays=2026-10-09; project switch preserves previously chosen value until explicit apply. First task due then extension accepted. Invalid invitation days rejected by browser and server.
- db-validation.json: final ORM state confirms task16 due 2026-10-23, invite count 0, saved draft body unchanged by conflict.

Known copy discrepancy: portfolio conflict says current server draft is available in the source list below; actual draft link is in Saved private drafts above. Parent informed.

Deliberate exclusions: external integration writes, real tokens, production data. Error mocks are browser tests, not claims of real production session expiry.
Authentication storageState reused from previous TEMP directory; no authentication session file copied into this output directory.
