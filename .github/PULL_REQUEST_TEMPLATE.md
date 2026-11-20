## What this PR does

<!-- One or two sentences. Link the issue it closes, if any: Closes #123 -->

## Type of change

- [ ] Bug fix
- [ ] New feature
- [ ] Site support / extractor work
- [ ] Documentation
- [ ] Refactor (no behaviour change)

## Verification

<!-- Paste commands you actually ran. "Should work" is not verification. -->

- [ ] `python -m unittest discover -s tests -t .` passes
- [ ] `node --check` passes for every changed `lib/*.js` / `scripts/*.mjs`
- [ ] `node scripts/check-manifest.mjs` passes
- [ ] `npm run doctor` is green on a machine that can actually transcribe
- [ ] Ran at least one real link end to end (paste the job result)

## Checklist

- [ ] No secrets, cookies, tokens or personal paths in the diff
- [ ] New user-visible strings are documented in both `README.md` and `README_zh.md`
- [ ] `CHANGELOG.md` updated under `Unreleased`
- [ ] I have the right to use the sample links I tested with
