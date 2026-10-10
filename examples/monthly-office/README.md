# Prepared office month

This is a public **modeled** office electricity profile, paired with an
**invented illustrative tariff**. It is not a utility-issued bill or a measured
customer record. No affiliation with or endorsement by the data authors is implied.

## Source and license

Adapted from **DOE/NREL End-Use Load Profiles for the U.S. Building Stock**,
ComStock AMY2018 release 1 (2021), building **2083**. The publication supplies the
full author citation and describes the calibrated building simulations:

- [Dataset publication and citation](https://data.openei.org/submissions/4520)
- [Dataset layout and units](https://oedi-data-lake.s3.amazonaws.com/nrel-pds-building-stock/end-use-load-profiles-for-us-building-stock/README.md)
- [Original building profile](https://oedi-data-lake.s3.amazonaws.com/nrel-pds-building-stock/end-use-load-profiles-for-us-building-stock/2021/comstock_amy2018_release_1/timeseries_individual_buildings/by_county/upgrade=0/county=G3600610/2083-0.parquet)
- [CC BY 4.0 license](https://creativecommons.org/licenses/by/4.0/)

Source metadata identifies a 37,500 ft² MediumOffice in New York, county
G3600610. `metadata.json` records the source URL, SHA256, clock and transformation.
The file was retrieved and inspected on October 10, 2026.

## Files and changes from source

- `intervals.csv`: only June 2018 and the total electricity column, renamed to
  `interval_end,energy_kwh`. Source floating-point values are preserved as decimal
  strings. No smoothing, gap filling, scale changes or timezone shifts.
- `tariff.json`: demo-only flat energy, monthly demand and fixed rates in USD.
- `expected-bill.json`: independently checked baseline totals for regression tests.
- `metadata.json`: provenance and interpretation; retain with redistributed data.

The 2,880 readings end at 15-minute boundaries from June 1 00:15 through July 1
00:00. Preserve the unzoned source simulation clock. The data is suitable for
explaining load shapes and an illustrative battery scenario, not equipment sizing
or a customer's actual investment decision. A printable bill is not included yet.

## Reproduce the sample

Normal demo use needs only the included CSV/JSON and Python 3.12. For optional
regeneration, install `pyarrow==24.0.0` in a separate preparation environment,
download the linked original Parquet to `downloads/comstock-2083-0.parquet`, then:

```sh
python -m tools.prepare_sample downloads/comstock-2083-0.parquet --output downloads/regenerated-month
```

The command checks the exact source SHA256, building ID, count and month before
writing files. It refuses an existing output directory. Compare the four generated
files with this directory before intentionally replacing any prepared artifact.
The preparation tool makes no network requests. Keep the full source download
and preparation environment out of Git.
