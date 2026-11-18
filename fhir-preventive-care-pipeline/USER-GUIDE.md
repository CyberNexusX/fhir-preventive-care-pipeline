# FHIR Preventive Care Pipeline — User Guide

The [project homepage](README.md) explains the workflow and sample use cases. This guide documents the exact run commands, input contract, and worklist fields.

## Run the included example

Use Python 3.11 or newer. No package installation is required.

```sh
python pipeline.py --input examples/synthetic-bundle.json --as-of 2026-01-01 --interval-days 180 --out build/worklist.csv
```

| Option | Purpose |
|---|---|
| `--input` | Path to a synthetic FHIR JSON collection Bundle |
| `--as-of` | Evaluation date in YYYY-MM-DD format |
| `--interval-days` | Positive integer for the illustrative reporting interval |
| `--out` | CSV path. Defaults to `build/worklist.csv`. |

To check a later snapshot without replacing the first output:

```sh
python pipeline.py --input examples/synthetic-bundle.json --as-of 2026-01-03 --interval-days 180 --out build/later-worklist.csv
```

## Input contract

- The top-level resource must be a FHIR `Bundle` of type `collection`. Each entry needs a resource with a type and ID.
- A Patient used for cohort selection must have a full birth date. Age is measured at the evaluation date.
- Condition and Observation resources must reference a Patient in the same Bundle using `Patient/<id>`. Other resource types do not contribute to cohort selection.
- A qualifying Condition carries SNOMED CT code `44054006`, has active clinical status and confirmed verification status, and has a recorded date by the evaluation date.
- A qualifying Observation carries LOINC code `4548-4`. It must have status `final`, `amended`, or `corrected`, a numeric quantity in UCUM `%`, and both `effectiveDateTime` and `issued`.
- Full dates and timestamps with UTC offsets are supported for condition and lab timing. Timestamps are converted to UTC dates. The cutoff includes the entire evaluation date. A result's measurement date must be on or before its issue date, and the issue date must be at or before the cutoff.
- Identical resources with the same type and ID are treated as one record. Conflicting duplicates cause an error. The pipeline does not reconstruct historical versions or accept contained, absolute, or URN patient references.

This loader checks the documented worklist input contract. It does not perform complete FHIR profile or terminology validation.

## Output dictionary

| Column | Meaning |
|---|---|
| `patient_id` | ID of the eligible synthetic Patient |
| `status` | Worklist state produced by the rule |
| `reason` | Machine-readable explanation for the status |
| `condition_id` | Most recently recorded qualifying diabetes Condition ID, with ties resolved by ID |
| `latest_observation_id` | ID of the selected qualifying A1c observation |
| `latest_a1c_date` | Measurement date of the selected result |
| `latest_a1c_percent` | Synthetic result in percent |
| `next_due_date` | Selected measurement date plus the supplied interval |
| `as_of` | Evaluation cutoff date |

Observation and due-date fields are blank when there is no eligible result. Rows are sorted by patient ID.

| Status | Reason | Decision |
|---|---|---|
| `up_to_date` | `within_interval` | Cutoff precedes the calculated due date |
| `due_today` | `interval_ends_today` | Cutoff equals the calculated due date |
| `overdue` | `interval_elapsed` | Cutoff follows the calculated due date |
| `no_eligible_result` | `no_available_qualifying_a1c` | No observation meets the input rules by the cutoff |

## Verify the output

```sh
python -m unittest discover -s tests -v
```

On macOS or Linux:

```sh
cmp examples/expected-worklist.csv build/worklist.csv
```

On Windows PowerShell:

```powershell
Get-FileHash examples/expected-worklist.csv, build/worklist.csv
```

Matching bytes or hashes confirm the default fixture output. The tests also verify that the delayed lab becomes eligible after issuance, a minor stays outside the adult cohort, and conflicts are surfaced before export.
