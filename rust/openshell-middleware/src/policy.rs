//! OpenShell middleware policy validation and scanner ownership planning.

use prost_types::{value::Kind, Struct};
use tonic::Status;

#[derive(Clone, Debug)]
pub(super) struct ScanPlan {
    pub(super) checks: Vec<&'static str>,
    pub(super) response_redaction: bool,
}

pub(super) fn scan_plan(config: Option<&Struct>) -> Result<ScanPlan, Status> {
    let Some(config) = config else {
        return Ok(ScanPlan {
            checks: vec!["injection", "context_poisoning", "secrets", "pii"],
            response_redaction: true,
        });
    };
    let response_redaction = config
        .fields
        .get("response_redaction")
        .and_then(|value| match value.kind.as_ref() {
            Some(Kind::BoolValue(value)) => Some(*value),
            _ => None,
        })
        .unwrap_or(true);
    let ownership = config
        .fields
        .get("scanner_ownership")
        .and_then(|value| match value.kind.as_ref() {
            Some(Kind::StructValue(value)) => Some(&value.fields),
            _ => None,
        });
    let mut checks = Vec::new();
    let mut redaction_owned = ownership.is_none();
    if let Some(values) = ownership {
        for (scanner, value) in values {
            let mode = match value.kind.as_ref() {
                Some(Kind::StringValue(value)) => value.as_str(),
                _ => {
                    return Err(Status::invalid_argument(format!(
                        "scanner ownership for {scanner} must be a string"
                    )))
                }
            };
            if mode == "hooks" {
                continue;
            }
            if mode == "both" {
                return Err(Status::failed_precondition(format!(
                    "scanner ownership 'both' is not supported by Rust middleware for {scanner}"
                )));
            }
            if mode != "middleware" && mode != "auto" {
                return Err(Status::invalid_argument(format!(
                    "unsupported scanner ownership mode for {scanner}: {mode}"
                )));
            }
            match scanner.as_str() {
                "prompt_injection" => checks.push("injection"),
                "context_poisoning" => checks.push("context_poisoning"),
                "secret_scanning" => checks.push("secrets"),
                "scan_pii" => checks.push("pii"),
                "scan_offensive" => checks.push("offensive"),
                "canary_detection" => checks.push("canary"),
                "secret_redaction" => redaction_owned = true,
                "supply_chain" | "config_file_scanning" => {
                    return Err(Status::failed_precondition(format!(
                        "scanner {scanner} is not available through daemon REST middleware"
                    )));
                }
                _ => {
                    return Err(Status::invalid_argument(format!(
                        "unknown scanner ownership entry: {scanner}"
                    )));
                }
            }
        }
    } else {
        checks.extend(["injection", "context_poisoning", "secrets", "pii"]);
    }
    Ok(ScanPlan {
        checks,
        response_redaction: response_redaction && redaction_owned,
    })
}
