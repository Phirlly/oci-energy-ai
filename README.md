# OCI Energy AI

A reusable electricity-bill and battery-scenario demo for OCI.
**Available today:** offline calculations and a GitHub configuration check.
Agents, bill uploads, a browser interface and automated OCI deployment are pending.

## Quick start

From the repository root, use **Python 3.12**. No packages, credentials or network
access are needed:

```sh
python -m energy_ai baseline
python -m energy_ai scenario --power-kw 25 --capacity-kwh 100 --target-kw 80
```

Both commands print JSON with monetary amounts in USD. The prepared example uses
June 2018 public **modeled** office readings and an **invented tariff**: $0.18/kWh,
$20/kW monthly peak demand and a $75 fixed fee.
See [sample provenance and files](examples/monthly-office/README.md).

| Result | Baseline | Battery scenario |
| --- | ---: | ---: |
| Electricity use | 25,924.38 kWh | 25,939.48 kWh |
| Peak demand | 98.47 kW | 80.00 kW |
| Modeled bill | **$6,710.80** | **$6,344.11** |

The 25 kW / 100 kWh battery uses 90% round-trip efficiency, includes charging
losses and starts and ends empty within numeric tolerance. The $366.69 difference
is an illustrative operating-cost result. This hindsight scenario excludes
equipment cost and degradation; it is not an investment return or real-time
controller. Check `target_achieved` when changing battery settings.

## Use your own readings

Supply one complete calendar month of 15-minute energy readings with these exact
CSV columns:

```csv
interval_end,energy_kwh
2018-06-01T00:15:00,2.5
2018-06-01T00:30:00,2.8
```

Each value covers the preceding 15 minutes. Endpoints run from the first day's
00:15 through the next month's first day at 00:00. Timestamps must be consecutive,
unique and unzoned; timezone conversion and DST repair are unsupported. Energy
must be finite and nonnegative. Maximum CSV size: 10 MiB.

Copy [tariff.json](examples/monthly-office/tariff.json), adjust its rates, then run:

```sh
python -m energy_ai baseline --intervals uploads/readings.csv --tariff uploads/tariff.json
```

Use the same file options with `scenario` for battery calculations. Only the flat
USD calendar-month tariff is supported; taxes, tiers, time-of-use rates and demand
ratchets are excluded. Bill PDFs and annual bill analysis are pending. Monthly
bill totals alone cannot establish interval peaks or precise battery savings.

## GitHub setup

The **Check deployment setup** workflow checks configuration only. Provisioning,
deployment, update, rollback and cleanup are pending. No local Python, `.env` or
OCI profile is needed for this check.

1. In your repository, open **Settings → Environments → New environment** and
   create `demo`. Before adding credentials, restrict **Deployment branches and
   tags** to selected branches `dev` and `main`, using branch rules.
2. Add the environment variables and secrets below. All variables are required.
   Variables are nonsecret metadata; put keys only in **secrets**, never in
   variables, source files or Terraform inputs.

| Environment setting | Type | Value |
| --- | --- | --- |
| `DEPLOYMENT_ID` | Variable | Unique name: 3–32 lowercase letters, digits or hyphens; first character a letter, last alphanumeric |
| `OCI_REGION` | Variable | Target OCI commercial region |
| `OCI_COMPARTMENT_OCID` | Variable | Target compartment OCID, not its display name |
| `OCI_TENANCY_OCID` | Variable | Deployment identity's tenancy OCID |
| `OCI_USER_OCID` | Variable | Deployment identity's user OCID |
| `OCI_FINGERPRINT` | Variable | Fingerprint of that user's registered API signing key |
| `OCI_PRIVATE_KEY` | Secret | Required: matching PEM private key |
| `OCI_PRIVATE_KEY_PASSPHRASE` | Secret | Required only for an encrypted private key |
| `OPENAI_API_KEY` | Secret | Optional OpenAI key |
| `ANTHROPIC_API_KEY` | Secret | Optional Anthropic key |

3. Open **Actions → Check deployment setup → Run workflow**, select `dev` or a
   validated `main`, and inspect the summary. Forks need Actions enabled and their
   own settings. The workflow must exist on the repository's default branch.

Use an OCI identity authorized for the target compartment. A passing check verifies
identifier formats and secret presence only—not credentials, IAM, quotas or model
access. Optional provider keys may be omitted. No cloud resources or model calls
are made. Custom GitHub App deployment protection rules are incompatible with this
check; the branch restrictions above are supported.

## Terraform configuration

The foundation defines a private artifact bucket and a Generative AI project;
application infrastructure is pending. From a successful
[Validate run](https://github.com/Phirlly/oci-energy-ai/actions/workflows/validate.yml)
with **all three jobs passed**, download
`terraform-<commit SHA>-attempt-<attempt number>` while signed into GitHub.
Artifacts expire after seven days.

Extract the download, then verify the inner `terraform.zip` from that directory:

```sh
sha256sum -c terraform.zip.sha256       # Linux
shasum -a 256 -c terraform.zip.sha256   # macOS
```

The result should be `terraform.zip: OK`. This archive contains configuration only.

## Tests and private data

Run the offline Python suite:

```sh
python -m unittest discover -s tests -t . -v
```

Keep private inputs under Git-ignored `uploads/`. Never commit bills, API keys or
Terraform state. The calculation CLI runs locally and prints results without
making model or cloud calls.
