"""Local, read-only FNS/BKI simulation; no network or request-count state."""

import csv
import hashlib
import io
import json
from copy import deepcopy
from pathlib import Path

from pydantic import TypeAdapter, ValidationError

from credit_cabinet.core.demo import CALCULATION_DATE
from credit_cabinet.core.security import utc_now
from credit_cabinet.models.enums import CheckSource, CheckStatus
from credit_cabinet.schemas.seed import CreditFacts, FixtureEntry, LegalFacts
from credit_cabinet.services.policy import SourceResult


class FixtureSources:
    def __init__(self, directory: Path):
        self.directory = directory

    def check(self, inn: str, source: CheckSource, revision_no: int, run_no: int) -> SourceResult:
        started = utc_now()
        version = "legal-mock-0.2" if source == CheckSource.FNS else "bki-mock-0.2"
        expected_source = "MOCK_FNS" if source == CheckSource.FNS else "MOCK_BKI"
        filename = "fns_responses.json" if source == CheckSource.FNS else "bki_responses.json"

        def result(status, data=None, error=None):
            return SourceResult(source, status, data, error, version, started, utc_now())

        try:
            manifest = json.loads((self.directory / "manifest.json").read_text(encoding="utf-8"))
            if manifest["schema_version"] != 2 or manifest["policy_version"] not in (
                "demo-policy-0.2",
                "demo-policy-0.3",
            ):
                raise ValueError("Unsupported fixture contract")

            def read(name):
                path = self.directory / name
                if path.stat().st_size > 2 * 1024 * 1024:
                    raise ValueError("Fixture too large")
                content = path.read_bytes()
                if hashlib.sha256(content).hexdigest() != manifest["files"][name]:
                    raise ValueError("Checksum mismatch")
                return content.decode("utf-8")

            companies = list(csv.DictReader(io.StringIO(read("companies.csv"))))
            keys = [row["company_key"] for row in companies if row["inn"] == inn]
            if len(keys) != 1:
                return result(CheckStatus.NO_DATA)
            rows = TypeAdapter(list[FixtureEntry]).validate_json(read(filename))
            choices = [
                row
                for row in rows
                if row.company_key == keys[0]
                and row.revision_no in (None, revision_no)
                and row.run_no <= run_no
            ]
            if not choices:
                return result(CheckStatus.NO_DATA)
            # Explicit revision wins over a reusable profile; latest attempt persists.
            selected = max(choices, key=lambda row: (row.revision_no is not None, row.run_no))
            if (
                selected.source_version != version
                or selected.provenance.source != expected_source
                or selected.provenance.as_of_date != CALCULATION_DATE
            ):
                raise ValueError("Wrong source/version/date")
            if selected.status != CheckStatus.SUCCESS:
                if selected.normalized_data is not None:
                    raise ValueError("Unavailable fixture has facts")
                return result(selected.status, error=selected.error_code)
            data = deepcopy(selected.normalized_data)
            if not isinstance(data, dict):
                raise ValueError("Missing facts")
            if source == CheckSource.FNS:
                # Unknown fact stays unknown, never silently becomes false.
                data.setdefault("is_bankrupt", None)
            normalized = (
                (LegalFacts if source == CheckSource.FNS else CreditFacts)
                .model_validate(data)
                .model_dump(mode="json")
            )
            normalized["provenance"] = {
                "source": expected_source,
                "as_of_date": CALCULATION_DATE.isoformat(),
                "checked_at": utc_now().isoformat(),
            }
            response = result(CheckStatus.SUCCESS, normalized)
            normalized["provenance"]["checked_at"] = response.completed_at.isoformat()
            return response
        except OSError:
            return result(CheckStatus.ERROR, error="FIXTURE_UNAVAILABLE")
        except (ValueError, KeyError, TypeError, ValidationError):
            return result(CheckStatus.ERROR, error="SOURCE_RESPONSE_INVALID")
