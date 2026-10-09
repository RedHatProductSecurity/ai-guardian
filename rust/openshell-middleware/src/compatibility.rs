//! Shared OpenShell release and supervisor-protocol compatibility checks.

use std::env;

use serde::Deserialize;

use super::{AppError, OPENSHELL_VERSION_ENV};

const COMPATIBILITY_POLICY: &str = include_str!(
    "../../../src/ai_guardian/middleware/openshell/compatibility.json"
);

#[derive(Debug, Deserialize)]
pub(super) struct ReleaseCompatibility {
    pub(super) major: u32,
    pub(super) minor: u32,
    pub(super) minimum_patch: u32,
}

#[derive(Debug, Deserialize)]
pub(super) struct ProtocolCompatibility {
    pub(super) major: u32,
    pub(super) minor: u32,
}

#[derive(Debug, Deserialize)]
pub(super) struct CompatibilityPolicy {
    pub(super) openshell_release: ReleaseCompatibility,
    pub(super) supervisor_protocol: ProtocolCompatibility,
    pub(super) runtime_version: String,
}

pub(super) fn compatibility_policy() -> Result<CompatibilityPolicy, AppError> {
    let policy: CompatibilityPolicy = serde_json::from_str(COMPATIBILITY_POLICY)?;
    let runtime_version = parse_openshell_version(&policy.runtime_version)?;
    let release = &policy.openshell_release;
    if runtime_version != (release.major, release.minor, release.minimum_patch) {
        return Err(AppError::Message(format!(
            "embedded OpenShell compatibility policy runtime_version must match {}.{}.{}",
            release.major, release.minor, release.minimum_patch
        )));
    }
    Ok(policy)
}

fn parse_openshell_version(value: &str) -> Result<(u32, u32, u32), AppError> {
    let trimmed = value.trim();
    let without_prefix = trimmed.strip_prefix('v').unwrap_or(trimmed);
    let core = without_prefix
        .split(|character| character == '-' || character == '+')
        .next()
        .unwrap_or(without_prefix);
    let components: Vec<&str> = core.split('.').collect();
    if components.len() != 3 || components.iter().any(|component| component.is_empty()) {
        return Err(AppError::Message(format!(
            "OpenShell version must be a semantic version such as 0.1.2: {value}"
        )));
    }
    let parsed: Result<Vec<u32>, _> = components
        .iter()
        .map(|component| component.parse::<u32>())
        .collect();
    let parsed = parsed.map_err(|_| {
        AppError::Message(format!(
            "OpenShell version must be a semantic version such as 0.1.2: {value}"
        ))
    })?;
    Ok((parsed[0], parsed[1], parsed[2]))
}

pub(super) fn validate_openshell_release(value: &str) -> Result<(), AppError> {
    let policy = compatibility_policy()?;
    let (major, minor, patch) = parse_openshell_version(value)?;
    let release = &policy.openshell_release;
    if major != release.major
        || minor != release.minor
        || patch < release.minimum_patch
    {
        return Err(AppError::Message(format!(
            "unsupported OpenShell release {value}; Rust middleware supports {}.{}.x from {}.{}.{}",
            release.major,
            release.minor,
            release.major,
            release.minor,
            release.minimum_patch
        )));
    }
    Ok(())
}

pub(super) fn validate_runtime_compatibility() -> Result<(), AppError> {
    let release = env::var(OPENSHELL_VERSION_ENV).map_err(|_| {
        AppError::Message(format!(
            "{OPENSHELL_VERSION_ENV} is required; set it to the installed OpenShell release before starting the service (for example, use `openshell --version`)"
        ))
    })?;
    validate_openshell_release(&release)
}
