# M01D user validation

Status: pending user review; M01D is not complete.

## Review steps

1. Review ADR 0012, `releases/voiceservice-v0.1.2.yaml`, and the referenced artifact manifest. Confirm the release binds the expected v0.1.2 OCI digests and the approved model revision/file identities.
2. Confirm Compose remains the service registry and that the model files remain outside Git and images.
3. Review the `make model-check` and explicit `make model-fetch` semantics. No real download, server access or deployment was performed; synthetic tests cover transfer failures and cache preservation.
4. Review local verification and the GitHub Actions result recorded in [verification](verification.md).

## Expected result

The manifest is the reviewed artifact-selection contract, not a second deployment definition. Existing verified model data is reused only after full integrity validation; failed provisioning leaves prior versions untouched. M01D remains a local foundation and does not imply M01E installation readiness on the Ubuntu host.

Reviewer, date, feedback and explicit M01D closeout decision: pending.
