## Summary

**Problem:** <!-- What's wrong or missing, and who it affects. -->

**Solution:** <!-- What this PR changes, in a few sentences. -->

Related issue: <!-- #123, or "none" -->

## Type of change

- [ ] Bug fix
- [ ] New feature (query param, config header, capability)
- [ ] Performance
- [ ] Security hardening
- [ ] Docs / CI / tooling only

## Checks

- [ ] `ruff check .` and `ruff format --check .` pass
- [ ] `mypy src/` passes
- [ ] `pytest --cov=src` passes, with tests added or updated for every behaviour change

## Compatibility

Existing deployments upgrade by redeploying the Lambda. Tick every box that is true; leave a box
unticked and explain below if it isn't.

- [ ] Derivative S3 keys are unchanged (`keys.derivative_key()` output is identical for the same input)
- [ ] `w` / `h` / `f` behaviour is unchanged, or the change is documented in the README
- [ ] No new **required** origin custom header (new settings are optional with safe defaults)
- [ ] The handler still never returns a generated response — every failure passes the request through
- [ ] Input bounds are unchanged or tighter (source size, pixel count, decoders, dimension clamp)

## Upgrade notes

<!-- Anything a deployer must do besides redeploying: IAM policy, cache policy, response headers
     policy, new origin headers, regenerating derivatives. Write "None required" only after checking. -->

## Docs

- [ ] README updated (interface, configuration headers, infra steps), or not needed
- [ ] CHANGELOG.md updated under the Unreleased section

## Notes for the reviewer

<!-- Anything that needs a closer look, trade-offs made, or how you tested it on real AWS. -->
