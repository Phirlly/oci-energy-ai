# OCI Energy AI

A reusable electricity-bill and battery-scenario demo for OCI.
**Available today:** offline calculations, Terraform foundation workflows and
GitHub model/tool verification. Bill uploads and the browser application are pending.

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

GitHub runs the setup and Terraform foundation workflows. No local Python,
`.env` or OCI profile is required. Use an OCI identity with target-compartment
[Resource Manager permissions](https://docs.oracle.com/en-us/iaas/Content/Identity/Reference/resourcemanagerpolicyreference.htm)
and permission to manage the bucket and
[Generative AI project](https://docs.oracle.com/en-us/iaas/Content/generative-ai/project-permissions.htm).
Confirm the selected region supports projects; IAM and quotas require live verification.

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
4. After validation passes for that commit, run **Bootstrap OCI foundation** with
   `apply` on the same branch. It creates or updates the owned Resource Manager
   stack, waits for its plan, then applies that exact plan. Logs report recovery
   IDs and the bucket, namespace and project outputs. This creates the foundation;
   it does not launch the application or test models.
5. Run **Verify model tool calls** with `configured` to check OCI and supplied
   OpenAI/Anthropic keys, or select one provider. It reads the existing foundation
   and sends only the public sample question and calculation results. Passing
   requires actual tool execution and the expected amounts above. A configured
   provider failure fails the workflow; absent optional keys are reported as skipped.

A passing configuration check verifies formats and secret presence only.
OpenAI/Anthropic keys are optional and unused by bootstrap. Vault delivery for the
future OCI application is pending. Custom GitHub App deployment protection rules
are incompatible with the configuration check; branch restrictions are supported.

Model checks incur provider usage charges and require model access, including
[OCI Responses permissions](https://docs.oracle.com/en-us/iaas/Content/generative-ai/get-started-agents.htm).
Defaults are
OCI `google.gemini-2.5-flash` (externally hosted through OCI in Ashburn), OpenAI
`gpt-4.1-mini-2025-04-14` and Anthropic `claude-haiku-5-5`. Optional environment
variables `OCI_MODEL`, `OPENAI_MODEL` and `ANTHROPIC_MODEL` select compatible models;
there is no automatic fallback. Another region/model requires its own successful
check. Each analysis is limited to 120 seconds, four model turns, two tool calls
and 2,048 output tokens per request. Raw responses and traces are not published.

## Foundation recovery and cleanup

The private bucket and GenAI project may incur OCI charges when used. Keep one
owning repository per deployment ID; forked installations need distinct IDs.
Keep its region and compartment fixed. Workflow runs serialize within a repository;
do not modify its stack concurrently through another repository or the Console.

On failure or timeout, inspect the logged stack/job in OCI Resource Manager.
The remote job may still be running. Wait for it to finish before rerunning
`apply`; the workflow refuses active jobs and preserves state for recovery.

To remove the foundation, run the same workflow with `destroy` and enter the exact
`DEPLOYMENT_ID` as confirmation. It removes managed resources, retains the empty
stack and never purges bucket contents. A nonempty bucket blocks cleanup; review
and remove its data separately, then retry. Application update/rollback is pending.

Successful [Validate runs](https://github.com/Phirlly/oci-energy-ai/actions/workflows/validate.yml)
also publish a configuration-only Terraform ZIP and SHA256 checksum for seven days.
Use artifacts only after all three jobs pass.

## Tests and private data

With Python 3.12 and [uv](https://docs.astral.sh/uv/getting-started/installation/),
install the locked dependencies and run the offline suite:

```sh
uv sync --locked --no-dev
uv run --no-sync python -m unittest discover -s tests -t . -v
```

Keep private inputs under Git-ignored `uploads/`. Never commit bills, API keys or
Terraform state. The calculation CLI runs locally and prints results without
making model or cloud calls.
