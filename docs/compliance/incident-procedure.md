# If a released output turns out to contain personal data

This procedure supports CNIL-15. It is addressed to the data controller; the tool cannot run it for you.

1. **Find what was released.** Every export appends a line to the local release register (default `~/.local/state/anonimizer/release_register.jsonl`, or the path in `ANONIMIZER_REGISTER`): date, record id, tier, output directory, file names. Each bundle also contains `release_label.json` and `assessment_record.json` with the same record id.
2. **Stop the distribution.** Withdraw the files from every place they were shared. A `LOCAL_ONLY` output should never have left the machine; a `RESTRICTED` output should never have left the organisation.
3. **Assess.** Compare the suspect values with the source. `anonimizer generate` can be re-run on the same source with the same contract and seed to reproduce the output exactly.
4. **Decide on notification.** Publishing personal data believed to be anonymous can be a personal-data breach. Whether it must be notified is the controller's decision, with its data protection officer.
5. **Record.** Add the decision to `docs/compliance/decisions/` if the output came from this repository's own tests, or to your organisation's incident log otherwise.
6. **Report the defect.** If a control of this tool failed, open a finding in `docs/compliance/findings.yaml` with the adversarial fixture that reproduces it, without real data.
