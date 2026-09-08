# Role behavioral evals

Manual, on-demand eval harness for sensitive-domain AI Employee roles
(`legal_intake`, `healthcare_intake`, `insurance_agent`,
`compliance_officer` as of this first batch). Makes real `/chat` calls
against a running instance to spot-check that a role's guardrails
(never giving legal/medical/coverage/compliance rulings, always
escalating) actually hold in practice -- not just that its personality
prompt *says* it will.

**Not part of `tests/` / CI.** These make real LLM API calls (cost
tokens, and pass/fail can be borderline on phrasing) -- run them by
hand against your own running instance, not automatically on every PR.

## Usage

```bash
pip install requests --break-system-packages  # if not already available
python3 evals/run_role_evals.py                      # all roles
python3 evals/run_role_evals.py --role legal_intake  # one role
python3 evals/run_role_evals.py --base-url http://localhost:8000
```

## Adding cases

Edit `eval_cases.json`. Each case has:
- `prompt` -- the question sent to the role
- `forbidden` -- substrings that must NOT appear in the answer (their
  presence means the role overstepped into advice/diagnosis/a ruling
  it isn't supposed to give)
- `required_any` -- at least one of these substrings must appear when
  the prompt is meant to trigger escalation. Leave both lists empty
  for a legitimate FAQ-level question the role should just answer
  normally, as a check that the role isn't over-escalating trivial
  questions too.

## Known limits

This is a pattern-match smoke test, not a substitute for a human
reviewing role behavior. A passing case does not guarantee the answer
was actually good -- only that it didn't trip an obvious guardrail
regression. Extending this to the rest of `SENSITIVE_DOMAIN_ROLES`
(`veterinary_intake`, `tax_preparation_intake`, `immigration_intake`)
and to non-sensitive roles is a natural follow-up, not done here.
