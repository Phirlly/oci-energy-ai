# OCI Energy AI

A reusable electricity-bill and battery-scenario demonstration, being built for
OCI. The calculation foundation runs locally today. Agents, bill-document upload,
the browser interface and OCI deployment are still to be implemented.

## Run the prepared example

Use Python 3.12 from the repository root. No packages, cloud credentials or network
access are needed for these commands:

```sh
python -m energy_ai baseline
python -m energy_ai scenario --power-kw 25 --capacity-kwh 100 --target-kw 80
```

Both commands print JSON. Monetary amounts are decimal strings in USD.

The example is **June 2018**, using 2,880 quarter-hour readings from a public
**modeled** New York medium office. It is not a customer's measured meter record.
The [sample files and attribution](examples/monthly-office/README.md) document
the source, license, clock convention and transformation.

The **illustrative tariff** charges $0.18/kWh, $20/kW for the month's maximum
15-minute demand, and a $75 fixed fee. It is not the building's actual tariff.

| Result | Baseline | Battery scenario |
| --- | ---: | ---: |
| Electricity use | 25,924.38 kWh | 25,939.48 kWh |
| Peak demand | 98.47 kW | 80.00 kW |
| Energy charge | $4,666.39 | $4,669.11 |
| Demand charge | $1,969.41 | $1,600.00 |
| Fixed charge | $75.00 | $75.00 |
| Modeled total | **$6,710.80** | **$6,344.11** |

The scenario uses a 25 kW / 100 kWh battery at 90% round-trip efficiency. It
includes charging energy and losses, starts empty, and ends empty within numeric
tolerance. The $366.69 difference is an illustrative operating-cost result.

Dispatch uses knowledge of the entire supplied month to limit charging to future
reachable demand above the target. This hindsight scenario is not an optimal
schedule or a real-time controller. It excludes equipment cost, degradation,
auxiliary loads and investment return. Some batteries or targets cannot achieve
the requested peak; the JSON reports `target_achieved`.

## Use your own interval readings

```sh
python -m energy_ai baseline --intervals uploads/readings.csv --tariff uploads/tariff.json
python -m energy_ai scenario --intervals uploads/readings.csv --tariff uploads/tariff.json --target-kw 80
```

Supply a complete calendar month with these exact CSV columns:

```csv
interval_end,energy_kwh
2018-06-01T00:15:00,2.5
2018-06-01T00:30:00,2.8
```

Each value is energy consumed during the preceding 15 minutes. The first endpoint
is 00:15 on the first day; the last is 00:00 on the first day of the next month.
Use consecutive, unzoned timestamps on a consistent source clock. The current
reader rejects gaps, duplicates, timezone-qualified timestamps, negative values,
nonfinite numbers, files above 10 MiB and more than 35,136 rows. It does not
convert timezones or repair DST gaps. Numeric inputs support up to 24 digits,
with interval energy and tariff rates bounded to 0–1 billion.

Copy [tariff.json](examples/monthly-office/tariff.json) and change the rates.
Only the stated flat USD calendar-month tariff is supported; taxes, tiered and
time-of-use charges, demand ratchets and noncalendar billing periods are not.
Each charge is rounded half-up to cents before summing the total.

Bill PDFs are not accepted by this CLI. The planned bill-review experience will
handle one or multiple actual billing periods, with visible extracted evidence
and corrections. Monthly bill totals alone cannot establish interval peaks or
precise battery savings.

## Check the calculations

```sh
python -m unittest discover -s tests -t . -v
python -m compileall -q energy_ai tools deployment
```

Tests check hand-calculated bills, the independent sample baseline, battery
energy balance and limits, invalid inputs, source-verification failures and CLI
contracts. Tests are separated into `tests/unit`, `tests/contracts` and
`tests/integration/sample`. All Python tests run offline. For a focused check:

```sh
python -m unittest tests.unit.energy.test_billing -v
```

## Terraform foundation

The initial configuration defines a private artifact bucket and a Generative AI
project with optional memory services disabled. It does not yet deploy the
application, networking or deployment lifecycle. No cloud credentials are needed
for these checks; provider installation requires network access:

```sh
terraform -chdir=infra/terraform init -backend=false -input=false -lockfile=readonly
terraform -chdir=infra/terraform validate
```

GitHub Actions validates with Terraform **1.5.7** for Resource Manager compatibility
and **1.16.4** for offline provider-mocked tests. With 1.16.4, run:

```sh
terraform -chdir=infra/terraform fmt -check -recursive
terraform -chdir=infra/terraform test
python -m deployment.terraform_bundle --output dist/terraform.zip
```

The ZIP contains only the reviewed Terraform files and exact provider lock.
Packaging prints its SHA256 and refuses to overwrite an existing archive; choose
a new output path when rerunning. Local state, credentials, test files and private
documents are excluded. This command creates an archive only.

### Download the configuration from GitHub

While signed into GitHub, open a completed successful
[Validate run](https://github.com/Phirlly/oci-energy-ai/actions/workflows/validate.yml).
All three jobs must pass; an available artifact alone does not mean the entire
run passed. Under **Artifacts**, download
`terraform-<commit SHA>-attempt-<attempt number>` for the packaging attempt.
Rerunning all jobs creates a separately named artifact. Artifacts expire after
seven days; rerun validation when a fresh download is needed.

Extract the downloaded GitHub archive to obtain `terraform.zip` and
`terraform.zip.sha256`. From that directory, verify the inner Terraform ZIP:

```sh
# Linux
sha256sum -c terraform.zip.sha256

# macOS
shasum -a 256 -c terraform.zip.sha256
```

The command should report `terraform.zip: OK`. The checksum file covers the
inner ZIP; GitHub also displays a separate digest for its outer artifact.
This is the Terraform configuration foundation, not a deployed application
or a complete demo release.

Deployment inputs are `deployment_id` (3–32 lowercase letters, digits or hyphens,
starting with a letter and ending with a letter or digit), `region` and an OC1
`compartment_ocid`. Syntactic checks do not prove service availability or IAM
permissions. The full deployment instructions will accompany the runnable service.

## GitHub deployment setup

GitHub Actions is the intended entry point for deploying this demo. The
**configuration check is available now**; automated provisioning, application
deployment, update, rollback and cleanup are still pending. You do not need a
local `.env`, Python installation or local OCI profile to run this check.

In your copy of this repository:

1. Open **Settings → Environments**, create an environment named `demo`, and set
   **Deployment branches and tags** to selected branches: `dev` and `main`
   (branch rules, not tag rules). Configure it before adding credentials.
2. Add the following **environment variables**. These are nonsecret metadata;
   GitHub may display variable values in Actions logs.

| Variable | Value to supply |
| --- | --- |
| `DEPLOYMENT_ID` | Your unique demo name, following the Terraform input rules above |
| `OCI_REGION` | Your target OCI commercial region |
| `OCI_COMPARTMENT_OCID` | Target compartment OCID, not its display name |
| `OCI_TENANCY_OCID` | Tenancy OCID for the deployment identity |
| `OCI_USER_OCID` | User OCID for the deployment identity |
| `OCI_FINGERPRINT` | Fingerprint of that user's registered OCI API signing key |

3. Add these **environment secrets** through GitHub's settings. Never place key
   values in variables, workflow inputs, source files or Terraform inputs.

| Secret | Required? |
| --- | --- |
| `OCI_PRIVATE_KEY` | Yes: the matching OCI API signing private key in PEM format |
| `OCI_PRIVATE_KEY_PASSPHRASE` | Only if that private key is encrypted |
| `OPENAI_API_KEY` | Optional: for OpenAI access |
| `ANTHROPIC_API_KEY` | Optional: for Anthropic access |

Use an existing OCI deployment identity approved for the target compartment, or
have an administrator prepare the required IAM permissions. The complete permission
and provisioning instructions will accompany the deployment workflow. The OCI
signing key authenticates deployment operations; it is separate from the optional
model-provider keys. A workstation profile name is not a GitHub credential.

4. Open **Actions → Check deployment setup → Run workflow**, select `dev` (or a
   validated `main`), and inspect the run summary. The workflow must exist on your
   repository's default branch to appear in the manual-run UI. In a fork, enable
   Actions and configure your own environment; credentials are not supplied by
   this repository.

Missing or malformed required settings fail together with their names and
correction guidance. A passing result means identifier formats were accepted and
the required secret was supplied. Keys are checked for presence only: their
contents, passphrase requirements, authentication, IAM, quotas and model access
are **not validated**. Optional providers show `not_configured` or
`supplied_unverified`; omitting both allows OCI-only configuration. No OCI
resources, model calls, Vault writes or GitHub deployment records are produced.
Custom GitHub App deployment protection rules are incompatible with this check's
environment mode; the branch restrictions above are supported.

The intended deployment then uses GitHub Actions to submit Terraform to OCI
Resource Manager, write configured provider keys to OCI Vault secrets through a
separate secret-management operation, and deploy the application. Raw provider
keys must stay out of Terraform state. The OCI backend will retrieve them using
its instance identity. Deployment smoke tests must prove a real model → tool →
answer for every enabled provider before it is shown as ready. This lifecycle
and runtime secret retrieval have not been implemented or verified yet.

## Privacy and current limits

These local commands make no model or cloud calls and do not retain input files
or results beyond the JSON printed to your terminal. Keep private files under
`uploads/`, which is excluded from Git. Do not commit bills, keys or cloud state.

No OCI deployment or live agent integration is advertised yet. The intended
customer experience adds real agent tool calls, an evidence-based bill review,
a browser interface and repeatable deployment and cleanup instructions.
