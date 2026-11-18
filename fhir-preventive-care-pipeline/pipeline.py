"""Generate an auditable A1c monitoring worklist from a synthetic FHIR R4 Bundle."""

import argparse
import csv
from datetime import date, datetime, timedelta, timezone
import json
from pathlib import Path

SNOMED = "http://snomed.info/sct"
LOINC = "http://loinc.org"
UCUM = "http://unitsofmeasure.org"
FIELDS = (
    "patient_id", "status", "reason", "condition_id", "latest_observation_id",
    "latest_a1c_date", "latest_a1c_percent", "next_due_date", "as_of",
)


def day(value):
    """Read a full date or an offset-aware timestamp, using UTC dates."""
    if len(value) == 10:
        return date.fromisoformat(value)
    timestamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if timestamp.tzinfo is None:
        raise ValueError(f"Timestamp needs an offset: {value}")
    return timestamp.astimezone(timezone.utc).date()


def coded(concept, system, code):
    return any(
        item.get("system") == system and item.get("code") == code
        for item in concept.get("coding", [])
    )


def diagnosis(record, as_of):
    if not coded(record.get("code", {}), SNOMED, "44054006"):
        return False
    active = coded(record.get("clinicalStatus", {}),
                   "http://terminology.hl7.org/CodeSystem/condition-clinical", "active")
    confirmed = coded(record.get("verificationStatus", {}),
                      "http://terminology.hl7.org/CodeSystem/condition-ver-status", "confirmed")
    return active and confirmed and day(record["recordedDate"]) <= as_of


def a1c(record, as_of):
    if not coded(record.get("code", {}), LOINC, "4548-4"):
        return None
    quantity = record.get("valueQuantity", {})
    if (
        record.get("status") not in {"final", "amended", "corrected"}
        or quantity.get("system") != UCUM or quantity.get("code") != "%"
        or type(quantity.get("value")) not in {int, float}
        or not 0 < quantity["value"] <= 100
        or not record.get("effectiveDateTime") or not record.get("issued")
    ):
        return None
    measured, issued = day(record["effectiveDateTime"]), day(record["issued"])
    if measured <= issued <= as_of:
        return measured, issued, record["id"], quantity["value"]
    return None


def build_worklist(bundle, as_of, interval_days):
    if interval_days < 1:
        raise ValueError("Interval must be a positive number of days")
    if bundle.get("resourceType") != "Bundle" or bundle.get("type") != "collection":
        raise ValueError("Expected a FHIR collection Bundle")
    indexed = {}
    for entry in bundle["entry"]:
        record = entry["resource"]
        key = (record["resourceType"], record["id"])
        if key in indexed and indexed[key] != record:
            raise ValueError(f"Conflicting duplicate resource: {key[0]}/{key[1]}")
        indexed[key] = record

    patients = {key[1]: record for key, record in indexed.items() if key[0] == "Patient"}
    diagnoses, observations = {}, {}
    for (kind, record_id), record in indexed.items():
        if kind not in {"Condition", "Observation"}:
            continue
        reference = record.get("subject", {}).get("reference", "")
        patient_id = reference.removeprefix("Patient/")
        if not reference.startswith("Patient/") or patient_id not in patients:
            raise ValueError(f"Unresolved relative patient reference for {kind}/{record_id}")
        if kind == "Condition" and diagnosis(record, as_of):
            diagnoses.setdefault(patient_id, []).append((day(record["recordedDate"]), record_id))
        if kind == "Observation":
            candidate = a1c(record, as_of)
            if candidate is not None:
                observations.setdefault(patient_id, []).append(candidate)

    rows = []
    for patient_id, evidence in sorted(diagnoses.items()):
        birth = date.fromisoformat(patients[patient_id]["birthDate"])
        age = as_of.year - birth.year - ((as_of.month, as_of.day) < (birth.month, birth.day))
        if age < 18:
            continue
        row = dict.fromkeys(FIELDS)
        row.update(patient_id=patient_id, condition_id=max(evidence)[1], as_of=as_of.isoformat())
        labs = observations.get(patient_id)
        if labs:
            measured, _, observation_id, value = max(labs)
            due = measured + timedelta(days=interval_days)
            if as_of > due:
                status, reason = "overdue", "interval_elapsed"
            elif as_of == due:
                status, reason = "due_today", "interval_ends_today"
            else:
                status, reason = "up_to_date", "within_interval"
            row.update(latest_observation_id=observation_id, latest_a1c_date=measured.isoformat(),
                       latest_a1c_percent=value, next_due_date=due.isoformat())
        else:
            status, reason = "no_eligible_result", "no_available_qualifying_a1c"
        row.update(status=status, reason=reason)
        rows.append(row)
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--as-of", type=date.fromisoformat, required=True)
    parser.add_argument("--interval-days", type=int, required=True)
    parser.add_argument("--out", type=Path, default=Path("build/worklist.csv"))
    args = parser.parse_args()
    try:
        bundle = json.loads(args.input.read_text(encoding="utf-8"))
        rows = build_worklist(bundle, args.as_of, args.interval_days)
    except (ValueError, KeyError, TypeError, OSError) as error:
        parser.error(str(error))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    print(f"Wrote {len(rows)} worklist rows to {args.out}")


if __name__ == "__main__":
    main()
