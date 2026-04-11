# ADR 0001: Use the database as the system of record for PLC suites and runs

## Status

Accepted

## Context

PLC testcases currently originate from spreadsheets, but spreadsheet-only ownership makes change tracking, run history, and reviewer access hard to manage.

## Decision

Imported PLC suites are normalized into a database-backed suite record, and PLC run state remains anchored in the existing `jobs` table.

## Consequences

- reviewers and APIs read one consistent source of truth
- queue and result history stay queryable without revisiting the original file
- raw workbook blobs are not treated as the primary model
- future normalization into additional tables remains possible
