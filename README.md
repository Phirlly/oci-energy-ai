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

Deployment inputs are `deployment_id` (3–32 lowercase letters, digits or hyphens,
starting with a letter and ending with a letter or digit), `region` and an OC1
`compartment_ocid`. Syntactic checks do not prove service availability or IAM
permissions. The full deployment instructions will accompany the runnable service.

## Privacy and current limits

These local commands make no model or cloud calls and do not retain input files
or results beyond the JSON printed to your terminal. Keep private files under
`uploads/`, which is excluded from Git. Do not commit bills, keys or cloud state.

No OCI deployment or live agent integration is advertised yet. The intended
customer experience adds real agent tool calls, an evidence-based bill review,
a browser interface and repeatable deployment and cleanup instructions.
