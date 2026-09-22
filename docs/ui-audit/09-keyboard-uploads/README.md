# UI evidence 09 — keyboard-operable file uploads

## Why this changed

The independent Astra cross-surface audit found that the visible “.md 올리기”
and “파일” controls were labels around file inputs removed from keyboard flow.
Project Documents and meeting notes hid the entire upload form with
`display:none`; API Documents used the `hidden` attribute. In all three screens,
the input rendered at `0×0`, the visible label had `tabIndex=-1`, and forcing
focus left `BODY` active.

## Before and after keyboard focus

| Surface (`390×844`) | Before | After |
| --- | --- | --- |
| Project Documents | ![Documents upload cannot receive focus before](mobile-docs-keyboard-before.png) | ![Documents upload has visible keyboard focus after](mobile-docs-keyboard-after.png) |
| Project API Documents | ![API file upload cannot receive focus before](mobile-api-keyboard-before.png) | ![API file upload has visible keyboard focus after](mobile-api-keyboard-after.png) |
| Organization meeting notes | ![Meeting-note upload cannot receive focus before](mobile-notes-keyboard-before.png) | ![Meeting-note upload has visible keyboard focus after](mobile-notes-keyboard-after.png) |

Each pair uses the same route, account, data, viewport, and color scheme. The
after image records the actual native file input focused through the visible
button treatment; no file was selected or uploaded.

## Implementation and measured result

- Keep a native file input in each existing multipart form and associate it with
  the visible label using a unique `for`/`id` pair.
- Visually reduce the input to a clipped `1px` control instead of removing it
  from layout/accessibility. It remains in Tab order and retains native file
  chooser semantics.
- Project Documents and meeting notes no longer use invalid label → hidden form
  nesting. Their upload forms are visible inline form containers alongside the
  existing create actions.
- `:focus-visible` on the native input draws a `2px` primary outline around its
  visible upload label.
- Before: active element `BODY`, input rectangle `0×0`, no visible focus. After:
  active element `INPUT`, rendered clipped rectangle `2×2` including borders,
  and the visible `40px`-high upload button carries the focus outline.
- Pressing Enter on the focused file input raised a native file-chooser event on
  all three routes. The test closed each page without choosing a file, so no
  upload or application-data change occurred.
- All three pages retained a `390px` document width with no horizontal overflow.

## Verification

- Upload/document/note focused web tests: `21 passed`.
- Template regression coverage verifies each focusable input, associated label,
  absence of `hidden`, and removal of the Documents `display:none` form.
- Browser checks covered focus indication and Enter activation on all three
  native inputs without selecting a file.
- Ruff lint, JavaScript syntax, Django system check, and `git diff --check`:
  passed.
