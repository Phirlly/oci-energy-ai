# OCI Energy AI

An OCI demo for reviewing electricity bills and exploring battery scenarios.
The **local browser app** supports bill upload, optional AI extraction, human
review and deterministic insights. Terraform foundation and hosted model checks
are available; the public OCI application deployment is still being built.

## Try bill review

Use **Python 3.12**, **Node 26.10.0** and [uv](https://docs.astral.sh/uv/getting-started/installation/).
From the repository root:

```sh
uv sync --locked --no-dev
cd frontend
npm ci --ignore-scripts --registry=https://registry.npmjs.org
npm run build
cd ..
uv run --no-sync python -m energy_ai.web
```

Open the printed localhost URL and enter its launch code. Choose **Try the
example**, review the fictional bill, approve it and calculate insights. No
model key is needed for this flow.

Upload one bill or up to 12 bills. Each must be an unencrypted text PDF, at most
4 MiB and 20 nonempty text pages; scanned bills need OCR first. Review actual
service dates, billed days, consumption, currency and current electricity charges.
Previous balances and fees already included in another charge must not be added
again. Approve each bill, then select compatible bills for combined insights.

Results include usage per day, supplied-period totals, average billed cost per
kWh and charge reconciliation. Missing facts leave affected metrics unavailable.
Overlaps, account differences and gaps are explicit; supplied bills are never
silently treated as a complete year. Bills alone cannot establish interval peaks
or precise battery savings.

**Optional AI:** server environment variables `OPENAI_API_KEY` and
`ANTHROPIC_API_KEY` enable those providers. Local OCI access requires explicit
`OCI_PROFILE`, `OCI_REGION` and `OCI_GENAI_PROJECT` settings and model permissions.
Optional `OCI_MODEL`, `OPENAI_MODEL`, `ANTHROPIC_MODEL` override model IDs. The UI
shows the selected model and asks before sending extracted text, including
identifiers. AI proposes facts with exact source quotes; you review them before
calculation. GitHub secrets are used by hosted checks, not downloaded to this app.
Extraction allows one correction attempt, with at most two model invocations
inside a shared 100-second deadline; unresolved facts still need manual review.

This presenter binds to `127.0.0.1` with one worker. Work stays in process memory
for a fixed 30-minute session and is discarded on sign-out, expiry or restart;
original PDF bytes are discarded after parsing. Do not expose it publicly.
Linux parsing has a hard address-space limit; macOS uses a soft RSS watchdog
that needs process-inspection permission. Public HTTPS hosting, Vault delivery
and persistent runs are pending.

## Explore the office battery example

The separate offline CLI needs only Python 3.12:

```sh
python -m energy_ai baseline
python -m energy_ai scenario --power-kw 25 --capacity-kwh 100 --target-kw 80
```

The [public modeled office month](examples/monthly-office/README.md) uses June
2018 readings and an invented USD tariff. Baseline: **$6,710.80**; a 25 kW /
100 kWh, 90%-efficient battery gives **$6,344.11**, including charging losses.
The $366.69 difference is a hindsight operating-cost scenario, excluding equipment
cost and degradation.

For your own readings, supply one complete calendar month with consecutive,
unique, unzoned 15-minute endpoints and CSV columns `interval_end,energy_kwh`.
Each value covers the preceding 15 minutes; maximum file size is 10 MiB.
Timezone/DST repair is unsupported. Copy the example
[tariff](examples/monthly-office/tariff.json), then pass
`--intervals uploads/readings.csv --tariff uploads/tariff.json` to either command.
This interval calculator supports the documented flat USD tariff, independently
of uploaded-bill analysis.

## GitHub / OCI setup

1. Create the GitHub environment **demo**. Restrict its deployment branches to
   `dev` and `main` before adding credentials. Forks need their own settings and
   Actions enabled.
2. Add these environment settings:

| Setting | Type | Purpose |
| --- | --- | --- |
| `DEPLOYMENT_ID` | Variable | Unique 3–32 lowercase letters/digits/hyphens; starts with a letter, ends alphanumeric |
| `OCI_REGION` | Variable | Target commercial region |
| `OCI_COMPARTMENT_OCID` | Variable | Target compartment OCID |
| `OCI_TENANCY_OCID` | Variable | Deployment tenancy |
| `OCI_USER_OCID` | Variable | Deployment user |
| `OCI_FINGERPRINT` | Variable | Registered signing-key fingerprint |
| `OCI_PRIVATE_KEY` | Secret | Matching PEM signing key |
| `OCI_PRIVATE_KEY_PASSPHRASE` | Secret | Only for an encrypted key |
| `OPENAI_API_KEY`, `ANTHROPIC_API_KEY` | Secrets | Optional external providers |

3. Run **Check deployment setup** on `dev` or validated `main`. This checks formats
   and presence, not live permissions. Custom GitHub App deployment protection
   rules are incompatible with this check.
4. After **Validate** passes, run **Bootstrap OCI foundation → apply** on the same
   commit. Terraform runs through OCI Resource Manager and creates the owned
   private bucket and GenAI project. It does not launch the application.
5. Run **Verify model tool calls → configured**. It checks real calculation-tool
   execution and generic extraction of invented public bills through OCI and
   configured external providers. Configured failures fail the run; missing
   optional keys are explicitly skipped. No personal bills are submitted.

The deployment identity needs
[Resource Manager permissions](https://docs.oracle.com/en-us/iaas/Content/Identity/Reference/resourcemanagerpolicyreference.htm),
bucket management and
[GenAI project permissions](https://docs.oracle.com/en-us/iaas/Content/generative-ai/project-permissions.htm).
Model checks also need
[OCI Responses access](https://docs.oracle.com/en-us/iaas/Content/generative-ai/get-started-agents.htm)
and incur provider charges. Defaults: OCI `google.gemini-2.5-flash` (externally
hosted through OCI in Ashburn), OpenAI `gpt-4.1-mini-2025-04-14`, Anthropic
`claude-haiku-5-5`. Optional GitHub variables `OCI_MODEL`, `OPENAI_MODEL` and
`ANTHROPIC_MODEL` select alternatives, which need their own successful check.
There is no automatic fallback. Raw model responses and traces are not published.

Keep one owning repository per deployment ID and its region/compartment fixed.
On timeout, inspect the logged Resource Manager job; it may still be running.
Wait before rerunning. To remove resources, run **Bootstrap OCI foundation →
destroy** and confirm the exact deployment ID. This retains the empty stack and
never purges bucket contents; a nonempty bucket blocks cleanup. Application
deployment, update and rollback remain pending.

## Validation and private data

```sh
uv run --no-sync python -m unittest discover -s tests -t . -v
cd frontend
npx --no-install playwright install chromium
npm test
```

Browser tests use invented data and a test-only scripted provider. Hosted model
checks prove live provider access separately. Keep private files in ignored
`uploads/`; never commit bills, credentials, logs or Terraform state. Corporate
networks may require a trusted CA bundle for package downloads; keep TLS
verification enabled.
