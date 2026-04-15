from __future__ import annotations

from datetime import datetime, timezone
import re
from typing import Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session

from api.models import PLCTestExecutionProfileRecord
from api.services.plc.contracts import (
    PLCExecutionProfileModel,
    PLCExecutionSetupRequirementsModel,
    PLCExecutionTimeoutPolicyModel,
    PLCTestCaseModel,
)


def _normalize_profile_fragment(value: str | None) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "-", str(value or "").strip().lower()).strip("-")
    return normalized or "default"


def derive_execution_profile_key(case: PLCTestCaseModel) -> str:
    if case.execution_profile_key:
        return case.execution_profile_key
    if case.memory_profile_key:
        return _normalize_profile_fragment(case.memory_profile_key)
    return "--".join(
        [
            _normalize_profile_fragment(case.instruction_name),
            _normalize_profile_fragment(case.input_type),
            _normalize_profile_fragment(case.output_type),
        ]
    )


def build_execution_profile_model(case: PLCTestCaseModel) -> PLCExecutionProfileModel:
    notes = case.description or (
        f"Prepared execution profile scaffold for {case.instruction_name} "
        f"({case.input_type} -> {case.output_type})."
    )
    return PLCExecutionProfileModel(
        key=derive_execution_profile_key(case),
        memory_profile_key=case.memory_profile_key,
        instruction_name=case.instruction_name,
        input_type=case.input_type,
        output_type=case.output_type,
        profile_version=None,
        timeout_policy=PLCExecutionTimeoutPolicyModel(
            default_timeout_ms=case.timeout_ms
        ),
        setup_requirements=PLCExecutionSetupRequirementsModel(),
        notes=notes,
        address_contract_json={
            "placeholder": True,
            "status": "unbound",
            "adapter_contract": "future-plc-address-contract",
        },
    )


def attach_execution_profile(case: PLCTestCaseModel) -> PLCTestCaseModel:
    profile = case.execution_profile or build_execution_profile_model(case)
    return case.model_copy(
        update={
            "execution_profile_key": profile.key,
            "execution_profile": profile,
        }
    )


def serialize_execution_profile_record(
    record: PLCTestExecutionProfileRecord,
) -> dict[str, object]:
    return {
        "key": record.key,
        "memory_profile_key": record.memory_profile_key,
        "instruction_name": record.instruction_name,
        "input_type": record.input_type,
        "output_type": record.output_type,
        "profile_version": record.profile_version,
        "timeout_policy": record.timeout_policy_json,
        "setup_requirements": record.setup_requirements_json,
        "notes": record.notes,
        "address_contract_json": record.address_contract_json,
    }


def execution_profile_model_from_record(
    record: PLCTestExecutionProfileRecord,
) -> PLCExecutionProfileModel:
    return PLCExecutionProfileModel.model_validate(
        serialize_execution_profile_record(record)
    )


def list_execution_profile_models(
    session: Session, *, keys: Iterable[str]
) -> dict[str, PLCExecutionProfileModel]:
    unique_keys = sorted({key for key in keys if key})
    if not unique_keys:
        return {}
    records = session.scalars(
        select(PLCTestExecutionProfileRecord).where(
            PLCTestExecutionProfileRecord.key.in_(unique_keys)
        )
    ).all()
    return {
        record.key: execution_profile_model_from_record(record) for record in records
    }


def ensure_execution_profiles(
    session: Session, *, cases: Iterable[PLCTestCaseModel]
) -> dict[str, PLCExecutionProfileModel]:
    attached_cases = [attach_execution_profile(case) for case in cases]
    keys = [
        case.execution_profile_key
        for case in attached_cases
        if case.execution_profile_key
    ]
    existing = {
        record.key: record
        for record in session.scalars(
            select(PLCTestExecutionProfileRecord).where(
                PLCTestExecutionProfileRecord.key.in_(keys)
            )
        ).all()
    }
    now = datetime.now(timezone.utc)
    for case in attached_cases:
        profile = case.execution_profile
        if profile is None:
            continue
        record = existing.get(profile.key)
        if record is None:
            record = PLCTestExecutionProfileRecord(
                key=profile.key,
                memory_profile_key=profile.memory_profile_key,
                instruction_name=profile.instruction_name,
                input_type=profile.input_type,
                output_type=profile.output_type,
                profile_version=profile.profile_version,
                timeout_policy_json=profile.timeout_policy.model_dump(mode="json"),
                setup_requirements_json=profile.setup_requirements.model_dump(
                    mode="json"
                ),
                notes=profile.notes,
                address_contract_json=profile.address_contract_json,
                is_active=True,
                updated_at=now,
            )
            session.add(record)
            existing[profile.key] = record
            continue

        record.memory_profile_key = profile.memory_profile_key
        record.instruction_name = profile.instruction_name
        record.input_type = profile.input_type
        record.output_type = profile.output_type
        record.profile_version = profile.profile_version
        record.timeout_policy_json = profile.timeout_policy.model_dump(mode="json")
        record.setup_requirements_json = profile.setup_requirements.model_dump(
            mode="json"
        )
        record.notes = profile.notes
        record.address_contract_json = profile.address_contract_json
        record.updated_at = now

    session.flush()
    return {
        key: execution_profile_model_from_record(record)
        for key, record in existing.items()
    }
