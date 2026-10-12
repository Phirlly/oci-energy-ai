# OCI Energy AI

An OCI demo for reviewing electricity bills and exploring battery scenarios.
The browser connects a prepared office month, battery scenarios, two tool-using
analysts and personal bill review. Python/FastAPI and React run on OCI; the OpenAI
Agents SDK orchestrates OCI, OpenAI and Anthropic model adapters.
**Status:** Demo preview. Office calculations and agent tool calls have been
verified through OCI, OpenAI and Anthropic. Bill-reading accuracy and fresh
installation remain under validation.

## Deploy on OCI

**Preview installer:** the published package is verified; a complete fresh
Resource Manager installation is still being validated.

<p align="center">
  <a href="https://cloud.oracle.com/resourcemanager/stacks/create?zipUrl=https%3A%2F%2Fobjectstorage.us-ashburn-1.oraclecloud.com%2Fn%2Fiddpyrbvyjar%2Fb%2Foci-energy-ai-releases-5d7383358dbb-artifacts%2Fo%2Ftemplates%252F94f711f0aa3cf27b24ec5bb753b1334fa0cdb634977108a6f642192e9bba70ad.zip">
    <img src="https://oci-resourcemanager-plugin.plugins.oci.oraclecloud.com/latest/deploy-to-oracle-cloud.svg" alt="Deploy to Oracle Cloud">
  </a>
</p>

Deploys the pinned [751fc20 build](https://github.com/Phirlly/oci-energy-ai/commit/751fc2087c2dcb3367ac860eb92f4be6358f8bd0).
No GitHub configuration, local tools or API signing key are needed for this path.

**Before you start:** use an OCI compartment with capacity for the resources below.
Your OCI identity must be able to provision them, create the runtime dynamic group
and IAM policy, and read Vault secret contents. Start with **US East (Ashburn)**,
where the demo's OCI model has been verified. Hosting creates a private VM
(1 OCPU, 8 GB RAM, 50 GB boot disk), networking/NAT, HTTPS API Gateway, an artifact
bucket, Vault/key and a Generative AI project. OCI and model-provider charges apply.

1. Click the button, sign in to OCI and select the target region and compartment.
   Review Oracle's terms and create a **new stack** using Terraform **1.5.x**.
2. Choose a unique **Deployment name**, **Availability domain** and compatible
   **Oracle Linux 9 image**. Leave **Installer retry generation** at `0`.
   Keep **Run apply** selected on the review page, then choose **Create**.
3. Wait for Apply to succeed. Application installation continues on the VM;
   the demo URL may take longer to become available.
4. In the Apply job's outputs, find **Owner setup secret** (`settings_secret_ocid`).
   Open that secret in OCI Vault, reveal its **CURRENT** version's contents and
   copy the `setup_code` value.
5. Open **Energy demo** (`application_origin`). Enter the setup code, choose your
   demo password and optionally add OpenAI and Anthropic API keys. Select
   **Save setup**, then sign in with that password. Settings are stored in OCI Vault;
   never enter passwords or API keys in Terraform variables.
6. Open **Office demo** and select **Calculate scenario**. For bill review, choose
   **Review your bills → Try the example**. Both work without external model keys.

If Apply fails, inspect its job logs for permission or capacity errors. If the
demo remains unavailable after Apply, inspect the VM's `oci-energy-ai-install`
service; increase **Installer retry generation** only after fixing an exhausted
installation. Keep the saved region, compartment, image and availability domain.
This preview installs a fixed build in a fresh stack; it does not provide in-place
upgrades or GitHub-managed rollback for Console installations.

**Remove this installation:** run **Destroy** on its Resource Manager stack.
This removes demo resources and public history; Vault deletion follows OCI waiting
periods. The empty stack record remains. Shared public installer files are retained.

## Run locally (optional)

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
that needs process-inspection permission. Use **Deploy on OCI** above for public
HTTPS hosting.

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

## GitHub deployment (optional)

Use this alternative to manage builds and deployment from your own repository.
These workflows and lifecycle commands apply to GitHub-managed installations;
do not point them at a stack created with the Console button above.

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
   The host-readiness stage allows up to 30 minutes.
5. Run **Deploy OCI demo → verify** to check public PDF upload/review and real
   office tools and bill extraction through every configured provider, followed
   by Chromium checks of login, battery scenarios, bill review and sign-out.

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
For the verified bill examples, set `OPENAI_MODEL=gpt-4.1-2025-04-14`.

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
cleanup. On timeout, inspect GitHub/OCI jobs and Run Commands before retrying;
cancellation alone does not establish that a remote operation stopped.
For a failed **apply**, once the blocking condition is resolved and remote
operations have finished, re-run its failed deployment job to reuse the original
commit and checked image
(retained for seven days). Changed code or an unavailable image requires a new
**apply** run and validation.

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
