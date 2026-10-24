import csv
import hashlib
import json
import re
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from uuid import uuid5

from pydantic import BaseModel, TypeAdapter, ValidationError
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from credit_cabinet.core.demo import CALCULATION_DATE, DEMO_NAMESPACE
from credit_cabinet.core.security import hash_password
from credit_cabinet.models import (
    Company,
    CompanyFinancialMonth,
    CompanyMembership,
    CreditProduct,
    User,
)
from credit_cabinet.models.enums import Role
from credit_cabinet.schemas.seed import (
    BankRelationshipSeed,
    CompanySeed,
    CreditFacts,
    FinancialSeed,
    FixtureEntry,
    LegalFacts,
    Manifest,
    MembershipSeed,
    ProductSeed,
    ScenarioSeed,
    UserSeed,
)

CORE_FILES = {
    "companies.csv",
    "financial_months.csv",
    "memberships.csv",
    "demo_users.json",
    "credit_products.json",
    "fns_responses.json",
    "bki_responses.json",
    "scenarios.json",
}


class DatasetError(ValueError):
    pass


@dataclass
class SeedBundle:
    manifest: Manifest
    companies: list[CompanySeed]
    financials: list[FinancialSeed]
    users: list[UserSeed]
    memberships: list[MembershipSeed]
    products: list[ProductSeed]
    bank_relationships: list[BankRelationshipSeed] | None = None


def read_json(path: Path):
    def invalid_constant(_value):
        raise DatasetError("JSON must not contain NaN/Infinity")

    try:
        return json.loads(path.read_text(encoding="utf-8"), parse_constant=invalid_constant)
    except (ValueError, OSError) as exc:
        raise DatasetError(f"Cannot read valid JSON: {path.name}") from exc


def csv_models(path: Path, model: type[BaseModel]) -> list:
    with path.open(encoding="utf-8", newline="") as source:
        reader = csv.DictReader(source)
        if (
            reader.fieldnames is None
            or len(reader.fieldnames) != len(model.model_fields)
            or set(reader.fieldnames) != set(model.model_fields)
        ):
            raise DatasetError(f"Wrong CSV columns: {path.name}")
        return [
            model.model_validate(
                {key: None if value == "" else value for key, value in row.items()}
            )
            for row in reader
        ]


def unique(rows, key, label):
    values = [key(row) for row in rows]
    if len(set(values)) != len(values):
        raise DatasetError(f"Duplicate {label}")


def load_bundle(directory: Path) -> SeedBundle:
    root = directory.resolve()
    try:
        manifest = Manifest.model_validate(read_json(root / "manifest.json"))
        if any(
            not re.fullmatch(r"documents/[A-Za-z0-9_-]+\.csv", template.path)
            for template in manifest.document_templates
        ):
            raise DatasetError("Invalid document template path")
        if not CORE_FILES <= set(manifest.files):
            raise DatasetError("Manifest is missing required files")
        allowed = CORE_FILES | {template.path for template in manifest.document_templates}
        personal = manifest.dataset_version == "demo-0.3"
        if manifest.policy_version != ("demo-policy-0.3" if personal else "demo-policy-0.2"):
            raise DatasetError("Dataset and policy versions disagree")
        if personal:
            allowed.add("bank_relationships.json")
        if set(manifest.files) != allowed:
            raise DatasetError("Manifest contains unknown files")
        for name, checksum in manifest.files.items():
            path = (root / name).resolve()
            if not path.is_relative_to(root) or not re.fullmatch(r"[a-f0-9]{64}", checksum):
                raise DatasetError("Invalid path or checksum in manifest")
            if path.suffix not in {".csv", ".json"} or path.stat().st_size > 2 * 1024 * 1024:
                raise DatasetError("Dataset files must be small CSV/JSON files")
            content = path.read_bytes()
            if b"\r" in content:
                raise DatasetError(f"Save UTF-8 with LF line endings: {name}")
            if hashlib.sha256(content).hexdigest() != checksum:
                raise DatasetError(f"Checksum mismatch: {name}")
        companies = csv_models(root / "companies.csv", CompanySeed)
        financials = csv_models(root / "financial_months.csv", FinancialSeed)
        memberships = csv_models(root / "memberships.csv", MembershipSeed)
        users = TypeAdapter(list[UserSeed]).validate_python(read_json(root / "demo_users.json"))
        products = TypeAdapter(list[ProductSeed]).validate_python(
            read_json(root / "credit_products.json")
        )
        unique(companies, lambda row: row.company_key, "company key")
        unique(companies, lambda row: row.inn, "INN")
        unique(users, lambda row: row.user_key, "user key")
        unique(users, lambda row: row.email, "email")
        unique(financials, lambda row: (row.company_key, row.month), "financial month")
        unique(memberships, lambda row: (row.user_key, row.company_key), "membership")
        if len(products) != 1:
            raise DatasetError("Exactly one version of WC_DEMO is required")
        if products[0].policy_version != manifest.policy_version:
            raise DatasetError("Product and manifest policies disagree")
        company_map = {row.company_key: row for row in companies}
        user_map = {row.user_key: row for row in users}
        if set(company_map) != set(manifest.company_keys):
            raise DatasetError("Company keys differ from manifest")
        for row in financials:
            if (
                row.company_key not in company_map
                or row.month < company_map[row.company_key].registered_on
            ):
                raise DatasetError("Unknown company or finance before registration")
        for row in memberships:
            if row.company_key not in company_map or row.user_key not in user_map:
                raise DatasetError("Membership references an unknown key")
            if user_map[row.user_key].role != Role.CLIENT:
                raise DatasetError("Bank staff must not be assigned company membership")
        if {row.company_key for row in memberships} != set(company_map):
            raise DatasetError("Each company needs a client membership")
        if sum(row.role == Role.BANK_STAFF for row in users) < 2:
            raise DatasetError("At least two demo bank users are required")
        for filename, facts, source, version in [
            ("fns_responses.json", LegalFacts, "MOCK_FNS", "legal-mock-0.2"),
            ("bki_responses.json", CreditFacts, "MOCK_BKI", "bki-mock-0.2"),
        ]:
            responses = TypeAdapter(list[FixtureEntry]).validate_python(read_json(root / filename))
            unique(
                responses,
                lambda row: (row.company_key, row.revision_no, row.run_no),
                "fixture attempt",
            )
            # Lists may later contain multiple ordered technical responses per company.
            if {row.company_key for row in responses} != set(company_map):
                raise DatasetError("Fixture companies differ from manifest")
            for row in responses:
                if (
                    row.source_version != version
                    or row.provenance.source != source
                    or row.provenance.as_of_date != CALCULATION_DATE
                    or row.provenance.checked_at is not None
                ):
                    raise DatasetError("Wrong fixture provenance/version")
                if row.status == "SUCCESS":
                    facts.model_validate(row.normalized_data)
                elif row.normalized_data is not None:
                    raise DatasetError("Unavailable source must have normalized_data=null")
        scenarios = TypeAdapter(list[ScenarioSeed]).validate_python(
            read_json(root / "scenarios.json")
        )
        unique(scenarios, lambda row: row.scenario_key, "scenario key")
        if any(row.company_key not in company_map for row in scenarios):
            raise DatasetError("Scenario references unknown company")
        for template in manifest.document_templates:
            if (
                template.company_key not in company_map
                or manifest.files.get(template.path) != template.content_sha256
            ):
                raise DatasetError("Invalid document template metadata")
        relationships = None
        if personal:
            relationships = TypeAdapter(list[BankRelationshipSeed]).validate_python(
                read_json(root / "bank_relationships.json")
            )
            unique(relationships, lambda row: row.company_key, "bank relationship")
            if {row.company_key for row in relationships} != set(company_map):
                raise DatasetError("Bank relationship companies differ from manifest")
        return SeedBundle(
            manifest, companies, financials, users, memberships, products, relationships
        )
    except (ValidationError, OSError, csv.Error) as exc:
        # Do not echo arbitrary input values, including accidentally pasted credentials.
        raise DatasetError(
            "Dataset structure is invalid; check schemas and required fields"
        ) from exc


def import_bundle(db: Session, bundle: SeedBundle, password: str | None = None) -> dict:
    counts = {
        name: 0 for name in ("users", "companies", "financial_months", "memberships", "products")
    }
    try:
        if db.bind.dialect.name == "postgresql":
            # Serialize concurrent init jobs; UNIQUE constraints remain the final safeguard.
            db.execute(text("SELECT pg_advisory_xact_lock(742180201)"))
        existing_users = {
            row.email: row
            for row in db.scalars(
                select(User).where(User.email.in_([str(row.email) for row in bundle.users]))
            )
        }
        if any(str(row.email) not in existing_users for row in bundle.users):
            if not password or not 12 <= len(password) <= 1024:
                raise DatasetError("A 12–1024 character password is required for new demo users")
        user_map = {}
        for row in bundle.users:
            user = existing_users.get(str(row.email))
            if user is not None and user.role != row.role:
                raise DatasetError("Existing user role conflicts with dataset; nothing was changed")
            if user is None:
                user = User(
                    id=uuid5(DEMO_NAMESPACE, f"user:{row.user_key}"),
                    email=str(row.email),
                    display_name=row.display_name,
                    role=row.role,
                    is_active=row.is_active,
                    ui_context={},
                    password_hash=hash_password(password),
                )
                db.add(user)
                counts["users"] += 1
            user_map[row.user_key] = user
        db.flush()
        company_map = {}
        for row in bundle.companies:
            values = row.model_dump(exclude={"company_key"})
            company = db.scalar(select(Company).where(Company.inn == row.inn))
            if company is not None and any(
                getattr(company, key) != value for key, value in values.items()
            ):
                raise DatasetError("Existing company conflicts with dataset; nothing was changed")
            if company is None:
                company = Company(id=uuid5(DEMO_NAMESPACE, f"company:{row.company_key}"), **values)
                db.add(company)
                counts["companies"] += 1
            company_map[row.company_key] = company
        db.flush()
        for row in bundle.bank_relationships or []:
            company_map[
                row.company_key
            ].has_active_loan_in_our_bank = row.has_active_loan_in_our_bank
        for row in bundle.products:
            values = row.model_dump()
            values["annual_rate_percent"] = Decimal(values["annual_rate_percent"])
            # JSON keeps canonical decimal strings and string enum values.
            values["allowed_purposes"] = [purpose.value for purpose in row.allowed_purposes]
            product = db.scalar(
                select(CreditProduct).where(
                    CreditProduct.code == row.code, CreditProduct.version == row.version
                )
            )
            if product is not None and any(
                getattr(product, key) != value
                for key, value in values.items()
                if key != "is_active"
            ):
                raise DatasetError(
                    "Product version is immutable; create a new version for changed conditions"
                )
            if product is None:
                db.add(
                    CreditProduct(
                        id=uuid5(DEMO_NAMESPACE, f"product:{row.code}:{row.version}"), **values
                    )
                )
                counts["products"] += 1
        db.flush()
        for row in bundle.financials:
            company_id = company_map[row.company_key].id
            existing = db.scalar(
                select(CompanyFinancialMonth.id).where(
                    CompanyFinancialMonth.company_id == company_id,
                    CompanyFinancialMonth.month == row.month,
                )
            )
            if existing is None:
                db.add(
                    CompanyFinancialMonth(
                        id=uuid5(
                            DEMO_NAMESPACE, f"finance:{row.company_key}:{row.month.isoformat()}"
                        ),
                        company_id=company_id,
                        **row.model_dump(exclude={"company_key"}),
                    )
                )
                counts["financial_months"] += 1
        for row in bundle.memberships:
            user_id, company_id = user_map[row.user_key].id, company_map[row.company_key].id
            if (
                db.scalar(
                    select(CompanyMembership.id).where(
                        CompanyMembership.user_id == user_id,
                        CompanyMembership.company_id == company_id,
                    )
                )
                is None
            ):
                db.add(
                    CompanyMembership(
                        id=uuid5(DEMO_NAMESPACE, f"membership:{row.user_key}:{row.company_key}"),
                        user_id=user_id,
                        company_id=company_id,
                    )
                )
                counts["memberships"] += 1
        db.commit()
        return {
            "created": counts,
            "dataset_version": bundle.manifest.dataset_version,
            "subset": bundle.manifest.subset,
        }
    except Exception:
        db.rollback()
        raise
