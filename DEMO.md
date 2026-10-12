# Run the OCI Energy AI lab

Start with the example—no customer data needed.
For an existing deployment, go straight to [Run the lab](#run-the-lab).

## Deploy and open the demo

**Preview:** the installer is published, but fresh Console installation is still
being validated. This installs a fixed build in a new stack.

The simplified installer described below is a source update awaiting publication.
The current README button still requires an Oracle Linux 9 image, uses fixed
model choices and creates a private artifact bucket. Keep its saved selections
and original package for later applies; use the new package only for a fresh stack.

Use **US East (Ashburn)** to match the verified OCI model region. You'll need:

- An OCI compartment with service access and capacity.
- Permission to create Compute, networking, API Gateway, Vault and Generative AI
  resources, plus the runtime dynamic group and IAM policy.
- Permission to read the deployment's setup secret in Vault.

The demo creates a private VM (1 OCPU, 8 GB RAM, 50 GB disk), networking/NAT,
HTTPS gateway, Vault/key and a Generative AI project. It downloads the checked
application from the shared public release bucket; new Console installations
do not create another artifact bucket. GitHub deployments keep private storage.
These resources and model requests incur charges. OpenAI and Anthropic keys
are optional.

1. Click [Deploy to Oracle Cloud in the README](README.md#deploy-on-oci).
   Sign in, select your region and compartment, review Oracle's terms and use
   Terraform **1.5.x**.
2. Choose a **Deployment name** unique across your tenancy and an **Availability domain**.
   A compatible Oracle Linux 9 platform image is selected automatically and saved
   for this stack. You can leave **Show advanced options** unchecked.
   On the review page, keep **Run apply** selected and choose **Create**.
3. After Apply succeeds, application installation continues on the VM.
   The demo URL may take longer to become available.
4. Find **Owner setup secret** (`settings_secret_ocid`) in the Apply job's outputs.
   Open that secret in OCI Vault, reveal its **CURRENT** contents and copy
   `setup_code`.
5. Open **Energy demo** (`application_origin`). Enter the setup code, choose
   your demo password and optionally add either, both or neither provider key.
   Select **Save setup**. Credentials are saved in Vault; never put them in Terraform
   variables. Keep the owner code private; presenters only need the demo password.
6. Enter your password in **Launch code** and select **Start session**.

## Run the lab

### 1. Understand the office bill

Open **Office demo**. The prepared month has a **$6,710.80** illustrative bill.
Look at the peak-day chart and the breakdown of energy, demand and fixed charges.
**Download illustrative bill** gives you the matching example PDF.

The source is public modeled office data with an invented tariff—not a customer's
measured bill.

### 2. Try a battery

Select **Calculate scenario** with the defaults:

| Control | Meaning | Default |
| --- | --- | --- |
| Power (kW) | How quickly the battery can charge or supply power | 25 |
| Capacity (kWh) | How much energy it can store | 100 |
| Round-trip efficiency | Energy retained after charging and discharging; 0.9 means 90% | 0.9 |
| Target peak (kW) | The grid-demand ceiling you want the battery to help achieve | 80 |

The modeled bill becomes **$6,344.11**, a **$366.69** difference.
Change one value and calculate again. A bigger battery does not always produce
more savings, and the app tells you if the target was reached. Use **Reset scenario**
to return to the defaults.

This uses the known month's demand and includes charging losses. It excludes
equipment costs, taxes, time-of-use pricing and other tariff complexities.

### 3. Ask the AI analysts

Choose **Office AI provider** and an **Analysis question**. Read and select the
consent checkbox, then select **Run analysts**.

**Energy Analyst** explains the bill. **Tariff & Savings Analyst** explains the
selected battery scenario. Open **Technical view** to see the actual tool calls
and model usage, or try another configured provider. Only the public office sample
and scenario are sent in this flow. Review AI explanations against the calculations.

### 4. Review electricity bills

1. Choose **Review your bills → Try the example**, or upload your own text PDFs.
2. Check dates, consumption and current electricity charges against the source.
   Enter facts manually, or read and select the consent checkbox, then choose
   **Extract with AI**.
   AI extraction sends bill text, including identifiers, to the selected provider.
3. If you edit any facts, select **Save corrections**. Select **Approve reviewed facts**.
4. Use **Include in insights** to select the approved bills, then **Calculate insights**.

Compare daily usage, total consumption, current charges and average billed cost
per kWh. Keep previous balances, payments and unrelated services out of electricity
charges; do not count included fees twice.

You can supply 1–12 unencrypted text PDFs: up to 4 MiB, 20 nonempty pages and
60,000 extracted characters each. Scans need text recognition (OCR) first.
Combined bills must have matching identities/currency and non-overlapping periods.
Missing periods and uncertain facts remain visible; a few bills are not treated
as a full year. Bill totals alone cannot establish peak demand or battery savings.

Private bills stay in memory and clear on sign-out, session expiry or restart.
PDF files are discarded after parsing. Public office history is shared among
presenters for up to 7 days/100 runs and survives restarts.

## If something doesn't work

- **Apply fails:** inspect the job logs for permissions, service access or capacity.
- **Demo stays unavailable:** inspect the VM's `oci-energy-ai-install` service.
  New installers report the phase where bootstrap stopped (such as packages,
  firewall or service) with a suggested check. This identifies the step, not
  necessarily the root cause; raw command output is kept out of installer errors.
  After fixing an exhausted installation, enable **Show advanced options** in
  the stack variables and increase **Installer retry generation** under
  **Installation recovery**. Save the variables and run **Apply** to send the
  change to the installer. Routine installation uses `0` automatically.
- **AI fails or is unavailable:** check the provider's key, model access or quota.
  The prepared calculations and manual bill review still work.

## Finish the lab

Sign out when finished. To remove a Console installation, run **Destroy** on its
Resource Manager stack. This deletes demo resources and public history; Vault
deletion follows OCI waiting periods. The empty stack record and shared public
installer files remain.

Keep the saved region, compartment and availability domain. The selected host
image is retained automatically. This preview
does not provide in-place upgrades or GitHub rollback for Console installations.

## Optional paths

<details>
<summary>Add, replace or remove provider keys</summary>

In new installations from the updated package, sign in and select **Owner settings**.
Enter your owner code, choose **Keep unchanged**, **Set a new key** or **Remove key**
for each provider, then select **Save provider keys**. The saved password stays the
same. New analyses use the saved keys immediately; an analysis already running can
finish with its previous key. Settings survive application restart.

Your owner code is the original setup code, retained as `owner_code` in the settings
secret's CURRENT contents. The demo password alone cannot change provider keys.
Saved keys are never displayed in the application. This Console flow does not
import GitHub secrets. Earlier packages do not have this maintenance screen;
use the updated package for a fresh installation.

Saving does not test model access. In **Office demo**, choose the provider and run
the public example after reviewing consent. Model requests may incur charges.

</details>

<details>
<summary>Change the Console deployment's AI models</summary>

Keep the defaults for the verified demo. If you need another model, select
**Show advanced options** in the stack's variables and edit the provider's model
ID under **AI models (optional)**. API keys stay in Vault.

Apply the configuration change to restart the app with the selected models.
The VM, saved credentials and public history remain; private sessions end.
An accepted model ID does not establish provider access or compatibility.
Run the public example with each changed provider to check it before presenting.
Models must support the demo's tool calls and bill extraction output.

</details>

<details>
<summary>Run locally or use your own interval readings</summary>

Use Linux/macOS, Python 3.12, Node 26.10.0 and [uv](https://docs.astral.sh/uv/getting-started/installation/).
From the repository root:

```sh
uv sync --locked --no-dev
cd frontend
npm ci --ignore-scripts --registry=https://registry.npmjs.org
npm run build
cd ..
uv run --no-sync python -m energy_ai.web
```

Open the printed URL and use the generated launch code. Set `DEMO_PASSWORD`
in the server environment to choose your own. The local server binds to
`127.0.0.1`; use OCI deployment for public HTTPS.

Optional server settings: `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`; local OCI also
requires `OCI_PROFILE`, `OCI_REGION`, `OCI_GENAI_PROJECT` and model permissions.
`OCI_MODEL`, `OPENAI_MODEL`, `ANTHROPIC_MODEL` override model IDs.
GitHub secrets are not downloaded to the local app. On macOS, PDF parsing needs
process-inspection permission for its memory watchdog.

The offline calculator needs only Python 3.12:

```sh
python -m energy_ai baseline
python -m energy_ai scenario --power-kw 25 --capacity-kwh 100 --target-kw 80
```

For your own readings, supply a complete calendar month of consecutive, unique,
unzoned 15-minute endpoints with CSV columns `interval_end,energy_kwh`.
Each value covers the preceding 15 minutes; the file limit is 10 MiB.
Timezone/DST repair is unsupported. Copy the example
[tariff](examples/monthly-office/tariff.json), then pass
`--intervals uploads/readings.csv --tariff uploads/tariff.json` to either command.
This flat-USD interval calculator is separate from bill-PDF analysis.

</details>

<details>
<summary>Manage a separate deployment with GitHub Actions</summary>

This alternative is for repository owners. Do not run these workflows against
a Console-created stack.

1. Fork the repository and enable Actions. Create the GitHub environment **demo**
   and restrict deployment branches to `dev` and `main` before adding credentials.
2. Add these environment settings:

| Setting | Type | Purpose |
| --- | --- | --- |
| `DEPLOYMENT_ID` | Variable | Tenancy-wide unique name; 3–32 lowercase letters/digits/hyphens; starts with a letter, ends alphanumeric |
| `OCI_REGION`, `OCI_COMPARTMENT_OCID` | Variables | Target region and compartment |
| `OCI_TENANCY_OCID`, `OCI_USER_OCID`, `OCI_FINGERPRINT` | Variables | Registered deployment identity |
| `OCI_PRIVATE_KEY` | Secret | Matching PEM signing key |
| `OCI_PRIVATE_KEY_PASSPHRASE` | Secret | Only for an encrypted key |
| `DEMO_PASSWORD` | Secret | Chosen nonblank password, up to 200 printable characters |
| `OPENAI_API_KEY`, `ANTHROPIC_API_KEY` | Secrets | Optional external providers |

3. Run **Check deployment setup**, then **Deploy OCI demo → apply**, on `dev` or
   validated `main`. Apply validates/builds the app, provisions through Resource
   Manager, delivers credentials to Vault and checks HTTPS. Host readiness can
   take up to 30 minutes. Open the reported URL with your `DEMO_PASSWORD`.
4. Run **Deploy OCI demo → verify** for configured-provider and browser checks.

The deployment identity needs Resource Manager and resource-management permissions
in the compartment, plus permission to create the runtime dynamic group/policy in
the tenancy home region. Use one owning repository per deployment ID and a
dedicated demo Vault. Keep its region/compartment fixed.

First apply pins the image and availability domain; optional `OCI_IMAGE_OCID`
and `OCI_AVAILABILITY_DOMAIN` choose them explicitly.
GitHub defaults are OCI `google.gemini-2.5-flash`, OpenAI
`gpt-4.1-mini-2025-04-14` and Anthropic `claude-haiku-5-5`.
For the verified bill examples, set `OPENAI_MODEL=gpt-4.1-2025-04-14`.
`OCI_MODEL` and `ANTHROPIC_MODEL` also override defaults. Missing external keys
leave OCI available; configured providers must pass verification.

- **apply** updates code, models or credentials.
- **rollback** restores the previous compatible release using current Vault
  credentials. Public history survives updates/restarts; private sessions end.
- **destroy**, with the exact deployment ID confirmation, removes the demo,
  public history and owned artifacts, schedules credentials for deletion and
  keeps the empty stack. Vault/key deletion follows OCI waiting periods.
  Unknown bucket objects or Vault children block cleanup.

Host-helper changes require **destroy**, then **apply**. To change the pinned
image/domain, destroy the old deployment and use a new `DEPLOYMENT_ID`.
After a failed apply, resolve the cause and wait for remote operations to finish
before rerunning its failed deployment job; that reuses the same checked build
for seven days. Changed code or an expired build needs a new apply. Cancellation
alone does not prove OCI jobs or Run Commands have stopped.

</details>

<details>
<summary>Run validation checks</summary>

After the local setup above:

```sh
uv run --no-sync python -m unittest discover -s tests -t . -v
cd frontend
npx --no-install playwright install chromium
npm test
```

Browser tests use invented data and a scripted provider; live model checks are
separate. Keep private bills in ignored `uploads/`. Never commit bills, keys,
logs or Terraform state, and keep TLS verification enabled.

</details>
