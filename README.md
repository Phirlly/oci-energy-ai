# OCI Energy AI

An OCI demo for reviewing electricity bills and exploring battery scenarios.
The browser connects a prepared office month, battery scenarios, two tool-using
analysts and personal bill review. Python/FastAPI and React run on OCI; the OpenAI
Agents SDK orchestrates OCI, OpenAI and Anthropic model adapters.
**Status:** local journeys and provider checks are verified. The new automated
OCI hosting workflow is awaiting its first live validation.

## Try the demo

Use **Linux or macOS**, **Python 3.12**, **Node 26.10.0** and [uv](https://docs.astral.sh/uv/getting-started/installation/).
From the repository root:

```sh
uv sync --locked --no-dev
cd frontend
npm ci --ignore-scripts --registry=https://registry.npmjs.org
npm run build
cd ..
uv run --no-sync python -m energy_ai.web
```

Open the printed localhost URL and enter its launch code. Set `DEMO_PASSWORD`
in the server environment to choose that code; otherwise one is generated locally.
**Office demo** shows
the prepared bill, downloadable illustrative PDF and demand chart. Adjust the
battery and choose **Calculate scenario**; no model key is needed. Configured
providers enable **Run analysts** after consent. **Technical view** shows actual
tool activity and measured usage; public run history preserves the original settings.

Choose **Review your bills → Try the example** to review, approve and calculate
insights from a fictional bill, also without a model key.

Upload one bill or up to 12 bills. Each must be an unencrypted text PDF, at most
4 MiB, 20 nonempty text pages and 60,000 extracted characters; scanned bills need OCR first. Review actual
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

The local presenter binds to `127.0.0.1` with one worker and 30-minute sessions.
Private bills stay in memory and clear on sign-out, expiry or restart; PDF bytes
are discarded after parsing. Public office history is shared across presenters
and stored in `runtime/office.sqlite3`, limited to 100 runs and 7 days. One office
analysis runs at a time, with a 180-second deadline and cancellation.
Linux parsing has a hard address-space limit; macOS uses a soft RSS watchdog
that needs process-inspection permission. Use the deployment workflow below for
public HTTPS hosting.

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
| `DEMO_PASSWORD` | Secret | Your chosen browser password or passphrase; nonblank, up to 200 printable characters, including spaces and Unicode |

3. Run **Check deployment setup** on `dev` or validated `main`. This checks formats
   without displaying secrets; live permissions are checked during deployment.
4. Run **Deploy OCI demo → apply**. It runs validation, builds and scans a Linux
   image, applies Terraform through OCI Resource Manager, delivers credentials to
   Vault, and verifies HTTPS login and the prepared scenario. Open the reported
   URL and enter your `DEMO_PASSWORD`. No local API-key files are needed.
5. Run **Deploy OCI demo → verify** to check public PDF upload/review and real
   office tools and bill extraction through every configured provider.

Hosting creates a private Oracle Linux 9 VM (1 OCPU, 8 GB RAM, 50 GB boot disk),
network/NAT, public HTTPS API Gateway, private artifact bucket, GenAI project,
dedicated Vault/key and instance identity. These resources and model requests
incur OCI/provider charges. The deployment identity needs management permissions
for these resources and Resource Manager in the target compartment, plus
permission to create the dynamic group and its policy in the tenancy home region.
Runtime credentials stay out of Terraform state and image artifacts.

The first apply selects and pins a compatible platform image and availability
domain. Optional variables `OCI_IMAGE_OCID` and `OCI_AVAILABILITY_DOMAIN` select
them explicitly. Keep one owning repository per deployment ID and keep its
region/compartment fixed; use a dedicated demo Vault without unrelated resources.

Defaults: OCI `google.gemini-2.5-flash` (through OCI in Ashburn), OpenAI
`gpt-4.1-mini-2025-04-14`, Anthropic `claude-haiku-5-5`. Optional variables
`OCI_MODEL`, `OPENAI_MODEL`, `ANTHROPIC_MODEL` select alternatives. Missing external
keys give an OCI-only deployment; configured providers must pass verification.

Use **apply** again to update code, models or credentials. **rollback** activates
the previous compatible release using current Vault credentials. Public office
history survives application updates and VM restarts; private bill sessions end
on restart. Host-helper changes require **destroy** then **apply**. To change the
pinned image or availability domain, destroy the old deployment, choose a new
`DEPLOYMENT_ID`, and apply; the old empty stack retains its original topology.

Use **destroy**, confirming the exact deployment ID, to stop the VM and remove
the demo. This deletes public history and owned artifacts, schedules credentials
for deletion, and retains the empty Resource Manager stack. Vault/key deletion
follows OCI waiting periods. Unknown bucket objects or Vault children block
cleanup. On timeout, inspect the reported jobs before retrying; cancellation
alone does not establish that a remote operation stopped.

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
