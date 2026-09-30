"""Resumable bounded batches; run explicitly offline, never during a request."""

import hashlib
import json
import time
from datetime import UTC, datetime
from pathlib import Path

import httpx
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from stations.enrichment import VERSION, match_candidate, station_name, write_json
from stations.ingestion import audit_csv


def redact(value, secret):
    if isinstance(value, dict):
        return {
            k: redact(v, secret)
            for k, v in value.items()
            if k.lower() not in ("apikey", "authorization")
        }
    if isinstance(value, list):
        return [redact(v, secret) for v in value]
    return value.replace(secret, "[REDACTED]") if isinstance(value, str) and secret else value


class Command(BaseCommand):
    help = "Prepare, submit, or resume one offline Geoapify batch; defaults to dry run."

    def add_arguments(self, parser):
        parser.add_argument("source")
        parser.add_argument("--output", default="data/enriched/stations.json")
        parser.add_argument("--limit", type=int, default=30)
        parser.add_argument("--sample-manifest")
        parser.add_argument("--execute", action="store_true")
        parser.add_argument("--dry-run", action="store_true")
        parser.add_argument("--quality-report")
        parser.add_argument("--credit-budget", type=float, default=2500)

    def handle(self, source, **options):
        audit = audit_csv(source)
        limit = options["limit"]
        if not 1 <= limit <= 1000:
            raise CommandError("One batch must contain 1–1000 inputs")
        ids = sorted(audit.stations)[:limit]
        if options["sample_manifest"]:
            manifest = json.loads(Path(options["sample_manifest"]).read_text())
            if manifest["source_sha256"] != audit.sha256:
                raise CommandError("Sample source hash mismatch")
            ids = [str(r["OPIS Truckstop ID"]) for r in manifest["records"]][:limit]
        inputs = []
        for opis_id in ids:
            fields = audit.stations[opis_id]["fields"]
            name, _ = station_name(fields["Truckstop Name"])
            inputs.append(
                {
                    "id": opis_id,
                    "params": {
                        "name": name,
                        "city": fields["City"],
                        "state": fields["State"],
                        "country": "United States",
                    },
                }
            )
        payload = {
            "api": "/v1/geocode/search",
            "priority": 0.5,
            "params": {
                "filter": "countrycode:us",
                "bias": "countrycode:none",
                "type": "amenity",
                "limit": 5,
                "format": "json",
            },
            "inputs": inputs,
        }
        digest = hashlib.sha256(
            json.dumps([VERSION, audit.sha256, payload], sort_keys=True).encode()
        ).hexdigest()
        cache_dir = settings.BASE_DIR / "data/cache/enrichment"
        state_path = cache_dir / f"{digest}.json"
        estimated = len(ids) * 0.5
        self.stdout.write(
            json.dumps(
                {
                    "inputs": len(ids),
                    "estimated_credits": estimated,
                    "query_version": VERSION,
                    "cache_key": digest,
                    "note": "Estimate excludes follow-ups and account-wide usage.",
                }
            )
        )
        if not options["execute"] or options["dry_run"]:
            return
        if limit > 30:
            report = (
                json.loads(Path(options["quality_report"]).read_text())
                if options["quality_report"]
                else {}
            )
            if (
                report.get("reviewed_usable", 0) < 24
                or report.get("observed_false_acceptances", 1) != 0
                or report.get("policy_version") != VERSION
            ):
                raise CommandError(
                    "Bulk work requires a matching-policy review: ≥24/30 usable and zero observed false acceptances"
                )
        key = settings.GEOAPIFY_API_KEY
        if not key:
            raise CommandError("GEOAPIFY_API_KEY is not configured")
        state = (
            json.loads(state_path.read_text())
            if state_path.exists()
            else {"payload": payload, "status": "prepared"}
        )
        if state["status"] == "ambiguous_submission":
            raise CommandError(
                "Submission response was lost; reconcile the provider job before resubmitting"
            )
        if state["status"] == "failed":
            raise CommandError(
                "Previous submission failed; reconcile its status before preparing a new job"
            )
        if state["status"] != "complete":
            # Caller controls the quota window; never assume the provider reset timezone.
            ledger_path = cache_dir / "credit-ledger.json"
            ledger = (
                json.loads(ledger_path.read_text())
                if ledger_path.exists()
                else {"reserved_credits": 0}
            )
            if state["status"] == "prepared":
                if ledger["reserved_credits"] + estimated > options["credit_budget"]:
                    raise CommandError(
                        "Local credit reserve exhausted; reconcile dashboard/window before further work"
                    )
                ledger["reserved_credits"] += estimated
                write_json(ledger_path, ledger)
                state["status"] = "ambiguous_submission"
                write_json(state_path, state)
                method, params, body = "POST", {"apiKey": key}, payload
            else:
                if time.time() - state.get("last_poll", 0) < 60:
                    raise CommandError(
                        "Wait at least 60 seconds between polls; completed work is retained"
                    )
                method, params, body = "GET", {"apiKey": key, "id": state["job_id"]}, None
                state["last_poll"] = time.time()
                write_json(state_path, state)
            try:
                with httpx.Client(timeout=30) as client:
                    response = client.request(
                        method, "https://api.geoapify.com/v1/batch", params=params, json=body
                    )
                if response.status_code not in (200, 202):
                    state["status"] = "failed" if method == "POST" else state["status"]
                    write_json(state_path, state)
                    raise CommandError(
                        f"Provider returned HTTP {response.status_code}; stopped without retry"
                    )
                result = redact(response.json(), key)
            except (httpx.HTTPError, ValueError) as exc:
                raise CommandError(
                    "Provider response unavailable; preserved job state, no automatic resubmission"
                ) from exc
            if method == "POST":
                if not isinstance(result, dict) or not result.get("id"):
                    raise CommandError(
                        "Submission did not return a job identity; reconcile before retry"
                    )
                state.update(job_id=result["id"], status="pending", last_poll=time.time())
            elif response.status_code == 200 and isinstance(result, dict) and "results" in result:
                state.update(status="complete", results=result["results"])
            write_json(state_path, state)
        if state["status"] != "complete":
            self.stdout.write("Batch pending. Rerun after at least 60 seconds to resume.")
            return
        received = datetime.now(UTC).isoformat()
        by_id = {str(r["id"]): r.get("result", {}).get("results", []) for r in state["results"]}
        records = []
        for opis_id in ids:
            station = audit.stations[opis_id]
            candidates = []
            for feature in by_id.get(opis_id, []):
                status, reasons = match_candidate(station["fields"], feature)
                candidates.append({"status": status, "reasons": reasons, "feature": feature})
            accepted = [c for c in candidates if c["status"] == "accepted"]
            status = (
                "accepted"
                if len(accepted) == 1
                else "review_required"
                if candidates
                else "unresolved"
            )
            chosen = accepted[0] if status == "accepted" else None
            records.append(
                {
                    "opis_id": opis_id,
                    "fingerprint": station["fingerprint"],
                    "status": status,
                    "source": "geoapify",
                    "latitude": chosen["feature"]["lat"] if chosen else None,
                    "longitude": chosen["feature"]["lon"] if chosen else None,
                    "evidence": {
                        "retrieved_at": received,
                        "identity_reason": chosen["reasons"] if chosen else [],
                        "candidates": candidates,
                    },
                }
            )
        write_json(
            options["output"],
            {"source_sha256": audit.sha256, "version": VERSION, "records": records},
        )
        self.stdout.write(
            json.dumps(
                {"accepted": sum(r["status"] == "accepted" for r in records), "total": len(records)}
            )
        )
