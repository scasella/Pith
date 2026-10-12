#!/usr/bin/env python3
"""
obligations/boundary/generate.py — a reviewed, TEMPLATE-SPECIFIC generator. Frozen.

Derived mechanically from the kernel: datatype shapes (kernel/spec/AuthSpec.dfy), the obligation tag
list, enum wire names (constructor upper-cased), observable atoms (kernel/glossary.yaml).
AUTHORED here and only reviewed, not derived: the API routes, the event vocabulary, and the monitor's
checks (monitor.template.py). Changing a postcondition in the spec does not change the monitor;
changing a datatype does. The gate regenerates and diffs the outputs so they cannot be hand-edited,
which guarantees consistency with this generator, not with the proof.

Writes gen/out/{openapi.yaml, events.schema.json, monitor.py}.
"""
import re, json, pathlib, yaml

ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
SPEC = (ROOT / "kernel" / "spec" / "AuthSpec.dfy").read_text() + (ROOT / "kernel" / "spec" / "PostingSpec.dfy").read_text()
GLOSS = yaml.safe_load((ROOT / "kernel" / "glossary.yaml").read_text())
OUT = ROOT / "gen" / "out"; OUT.mkdir(parents=True, exist_ok=True)

# ---- parse datatypes from the Dafny spec ------------------------------------
def split_top(s):
    """Split on commas not nested inside <...>."""
    out, depth, cur = [], 0, ""
    for ch in s:
        if ch == "<": depth += 1
        if ch == ">": depth -= 1
        if ch == "," and depth == 0:
            out.append(cur.strip()); cur = ""
        else:
            cur += ch
    if cur.strip(): out.append(cur.strip())
    return out

def parse_datatypes(src):
    types = {}
    for m in re.finditer(r"datatype\s+(\w+)\s*=\s*([^\n]+)", src):
        name, body = m.group(1), m.group(2).split("//")[0].strip()
        ctors = [c.strip() for c in body.split("|")]
        if all("(" not in c for c in ctors):
            types[name] = {"enum": ctors}
        else:
            c = ctors[0]; cname = c[:c.index("(")]
            fields = split_top(c[c.index("(") + 1:c.rindex(")")])
            types[name] = {"ctor": cname, "fields": [(f.split(":")[0].strip(), f.split(":", 1)[1].strip()) for f in fields]}
    return types

DAFNY_TO_JSON = {"nat": {"type": "integer", "minimum": 0, "maximum": 2**53 - 1}, "ReqId": {"type": "integer", "minimum": 0, "maximum": 2**53 - 1}}
def json_type(t):
    if t in DAFNY_TO_JSON: return dict(DAFNY_TO_JSON[t])
    if t.startswith("map<"):
        return {"type": "object", "description": f"Dafny {t}; keys are request ids as strings", "additionalProperties": True}
    return {"$ref": f"#/components/schemas/{t}"}

types = parse_datatypes(SPEC)
schemas = {}
for name, t in types.items():
    if "enum" in t:
        schemas[name] = {"type": "string", "enum": [c.upper() for c in t["enum"]],
                         "description": f"Dafny {name} constructors {t['enum']}, upper-cased on the wire"}
    else:
        schemas[name] = {"type": "object", "required": [f for f, _ in t["fields"]],
                         "properties": {f: json_type(ty) for f, ty in t["fields"]}}

# ---- obligations that are observable at the boundary (from the spec tags + glossary) ----
tags = sorted(set(re.findall(r"\[([A-Z0-9']+)\]", SPEC)))
observables = {k: v["observed"] for k, v in GLOSS["atoms"].items()}

# ---- OpenAPI -----------------------------------------------------------------
openapi = {
  "openapi": "3.0.3",
  "info": {"title": "authorization-core service", "version": "1",
           "description": "Generated from kernel/spec/AuthSpec.dfy and kernel/glossary.yaml by obligations/boundary/generate.py. Do not edit.\n"
                          "Requirement: " + GLOSS["requirement"].strip()},
  "paths": {
    "/accounts": {"post": {"summary": "Create account", "requestBody": {"required": True, "content": {"application/json": {"schema": {
        "type": "object", "required": ["id", "limit"], "properties": {"id": {"type": "integer"}, "limit": json_type("nat")}}}}},
        "responses": {"201": {"description": "created"}}}},
    "/accounts/{id}": {"get": {"summary": "Account state (Account datatype plus derived available)", "parameters": [{"name": "id", "in": "path", "required": True, "schema": {"type": "integer"}}],
        "responses": {"200": {"description": "ok", "content": {"application/json": {"schema": {"$ref": "#/components/schemas/AccountView"}}}}}}},
    "/accounts/{id}/authorize": {"post": {"summary": "Decide(a, Request(request_id, amount)); request_id is the idempotency key",
        "parameters": [{"name": "id", "in": "path", "required": True, "schema": {"type": "integer"}}],
        "requestBody": {"required": True, "content": {"application/json": {"schema": {"$ref": "#/components/schemas/AuthorizeRequest"}}}},
        "responses": {"200": {"description": "decided (or replayed)", "content": {"application/json": {"schema": {"$ref": "#/components/schemas/AuthorizeResponse"}}}}}}},
    "/accounts/{id}/release": {"post": {"summary": "Release(a, request_id)",
        "parameters": [{"name": "id", "in": "path", "required": True, "schema": {"type": "integer"}}],
        "requestBody": {"required": True, "content": {"application/json": {"schema": {"type": "object", "required": ["request_id"], "properties": {"request_id": json_type("ReqId")}}}}},
        "responses": {"200": {"description": "released or no-op"}}}},
    "/accounts/{id}/capture": {"post": {"summary": "Capture(a, request_id): post the held amount in full (posting kernel); idempotent for a captured request",
        "parameters": [{"name": "id", "in": "path", "required": True, "schema": {"type": "integer"}}],
        "requestBody": {"required": True, "content": {"application/json": {"schema": {"type": "object", "required": ["request_id"], "additionalProperties": False, "properties": {"request_id": json_type("ReqId")}}}}},
        "responses": {"200": {"description": "captured, replayed, or no-op", "content": {"application/json": {"schema": {"$ref": "#/components/schemas/CaptureResponse"}}}}}}},
    "/events": {"get": {"summary": "Event stream the monitor reads", "parameters": [{"name": "since", "in": "query", "schema": {"type": "integer"}}],
        "responses": {"200": {"description": "events", "content": {"application/json": {"schema": {"type": "array", "items": {"$ref": "#/components/schemas/Event"}}}}}}}},
  },
  "components": {"schemas": {**schemas,
    "AuthorizeRequest": {"type": "object", "required": ["request_id", "amount"], "additionalProperties": False,
        "properties": {"request_id": {"type": "integer", "minimum": 0, "maximum": 2**53 - 1}, "amount": {"type": "integer", "minimum": 1, "maximum": 2**53 - 1}}},
    "AuthorizeResponse": {"type": "object", "required": ["request_id", "decision"], "properties": {
        "request_id": json_type("ReqId"), "decision": {"type": "string", "enum": ["AUTHORIZED", "DECLINED"]},
        "available_at_decision": {"type": "integer"}, "replayed": {"type": "boolean"}}, "additionalProperties": False},
    "CaptureResponse": {"type": "object", "required": ["request_id", "captured"], "additionalProperties": False, "properties": {
        "request_id": json_type("ReqId"), "captured": {"type": "boolean"}, "amount": json_type("nat"), "replayed": {"type": "boolean"}}},
    "AccountView": {"type": "object", "required": ["id", "limit", "posted", "available", "holds", "status"], "properties": {
        "id": {"type": "integer"}, "limit": json_type("nat"), "posted": json_type("nat"), "available": {"type": "integer"},
        "holds": {"type": "object", "additionalProperties": {"type": "integer", "minimum": 1}},
        "status": {"type": "object", "additionalProperties": schemas["Status"]}}, "additionalProperties": False},
    "Event": {"$ref": "events.schema.json"}}},
  "x-obligations": tags,
}
(OUT / "openapi.yaml").write_text(yaml.safe_dump(openapi, sort_keys=False))

# ---- event schema ---------------------------------------------------------------
events = {
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "title": "auth-service events", "description": "Generated from glossary.yaml observables. Do not edit.",
  "oneOf": [
    {"type": "object", "required": ["type", "account_id", "limit", "producer", "op_id", "prev_hash", "hash"], "properties": {"type": {"const": "account.created"}, "account_id": {"type": "integer", "minimum": 0}, "limit": json_type("nat"), "producer": {"type": "string"}}},
    {"type": "object", "required": ["type", "account_id", "op", "producer", "state_after", "op_id", "prev_hash", "hash"],
     "properties": {"type": {"const": "op.committed"}, "account_id": {"type": "integer", "minimum": 0}, "request_id": {"type": ["integer", "null"], "minimum": 0},
                    "op": {"type": "string", "enum": ["create_account", "authorize", "release", "capture"]}, "producer": {"type": "string"},
                    "state_after": {"type": "object", "required": ["limit", "posted", "reserved"], "properties": {"limit": json_type("nat"), "posted": json_type("nat"), "reserved": json_type("nat")}}}},
    {"type": "object", "required": ["type", "account_id", "request_id", "amount", "available_at_decision", "decision", "producer", "op_id", "prev_hash", "hash"],
     "properties": {"type": {"const": "auth.decided"}, "account_id": {"type": "integer"}, "request_id": json_type("ReqId"), "amount": {"type": "integer", "minimum": 1, "maximum": 2**53 - 1},
                    "available_at_decision": {"type": "integer"}, "decision": {"type": "string", "enum": ["AUTHORIZED", "DECLINED"]}, "producer": {"type": "string"}}},
    {"type": "object", "required": ["type", "account_id", "request_id", "amount", "producer", "op_id", "prev_hash", "hash"],
     "properties": {"type": {"const": "reservation.created"}, "account_id": {"type": "integer"}, "request_id": json_type("ReqId"), "amount": {"type": "integer", "minimum": 1, "maximum": 2**53 - 1}, "producer": {"type": "string"}}},
    {"type": "object", "required": ["type", "account_id", "request_id", "amount", "producer", "op_id", "prev_hash", "hash"],
     "properties": {"type": {"const": "capture.posted"}, "account_id": {"type": "integer"}, "request_id": json_type("ReqId"), "amount": {"type": "integer", "minimum": 1, "maximum": 2**53 - 1}, "producer": {"type": "string"}}},
    {"type": "object", "required": ["type", "account_id", "request_id", "producer", "op_id", "prev_hash", "hash"],
     "properties": {"type": {"const": "reservation.released"}, "account_id": {"type": "integer"}, "request_id": json_type("ReqId"), "producer": {"type": "string"}}},
  ],
  "x-observables": observables,
  "x-event-contract": "each write operation emits its events then exactly one op.committed carrying state_after; seq is a total order; (account_id, request_id) identifies a request; every event carries prev_hash and hash (sha256 of the canonical event without hash)",
  "x-operations": "every event carries op_id; the events of one operation are contiguous and end with exactly one op.committed; required composition: create_account=[account.created], authorize=[auth.decided (+ reservation.created iff AUTHORIZED)], release=[reservation.released], capture=[capture.posted]",
  "x-chain": {"required": ["prev_hash", "hash"], "canonical": "json.dumps(sort_keys=True, separators=(',', ':')) over the event without 'hash' and without 'seq'"},
}
(OUT / "events.schema.json").write_text(json.dumps(events, indent=2))

# ---- monitor ---------------------------------------------------------------------
monitor = (pathlib.Path(__file__).parent / "monitor.template.py").read_text().replace("__TAGS__", str(tags))
(OUT / "monitor.py").write_text(monitor)
print("generated:", *[p.name for p in sorted(OUT.iterdir())])
