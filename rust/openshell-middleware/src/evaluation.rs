//! Daemon-backed content evaluation and OpenShell finding conversion.

use std::collections::HashMap;

use super::daemon::{
    clean_check_response, pause_metadata, CheckResponse, DaemonClient, DaemonFinding,
};
use super::openshell::middleware::v1::Finding;
use super::policy::ScanPlan;
use super::AppError;

#[derive(Debug)]
pub(super) struct Evaluation {
    pub(super) blocked: bool,
    pub(super) redacted: Option<String>,
    pub(super) findings: Vec<Finding>,
    pub(super) metadata: HashMap<String, String>,
    pub(super) reason: String,
    pub(super) reason_code: String,
}

pub(super) fn findings(findings: &[DaemonFinding]) -> Vec<Finding> {
    findings
        .iter()
        .map(|finding| Finding {
            r#type: finding.finding_type.clone(),
            label: "AI Guardian finding".to_string(),
            count: 1,
            confidence: "high".to_string(),
            severity: "high".to_string(),
        })
        .collect()
}

pub(super) fn finding_blocks(finding: &DaemonFinding) -> bool {
    // Older daemons do not include action metadata. Treat those findings as
    // blocking so upgrading the middleware cannot weaken an existing policy.
    finding.should_block.unwrap_or_else(|| {
        !matches!(
            finding.action_taken.as_deref(),
            Some("warn") | Some("log") | Some("log-only")
        )
    })
}

pub(super) fn response_has_blocking_findings(response: &CheckResponse) -> bool {
    if response.blocked {
        return true;
    }
    if response.findings.is_empty() {
        return !response.clean;
    }
    response.findings.iter().any(finding_blocks)
}

pub(super) fn response_has_findings(response: &CheckResponse) -> bool {
    response.blocked || !response.clean || !response.findings.is_empty()
}

pub(super) fn paused_evaluation(response: CheckResponse) -> Evaluation {
    // A daemon pause means scanning is suspended, not that the network path
    // should be denied.  Preserve the pause details as audit-safe metadata
    // while allowing the request/response to continue.
    Evaluation {
        blocked: false,
        redacted: None,
        findings: Vec::new(),
        metadata: pause_metadata(&response),
        reason: String::new(),
        reason_code: String::new(),
    }
}

pub(super) async fn evaluate(
    daemon: &DaemonClient,
    content: &str,
    request_id: &str,
    plan: &ScanPlan,
    block_all_findings: bool,
) -> Result<Evaluation, AppError> {
    if plan.checks.is_empty() {
        if let Some(response) = daemon.pause_status().await? {
            return Ok(paused_evaluation(response));
        }
        return Ok(Evaluation {
            blocked: false,
            redacted: None,
            findings: Vec::new(),
            metadata: HashMap::new(),
            reason: String::new(),
            reason_code: String::new(),
        });
    }
    // Run semantic checks first. The daemon's legacy combined secrets/PII
    // path can fail independently; it must not hide a valid prompt-injection
    // denial behind a generic middleware failure.
    let semantic_checks: Vec<_> = plan
        .checks
        .iter()
        .copied()
        .filter(|check| matches!(*check, "injection" | "context_poisoning" | "canary"))
        .collect();
    let semantic = if semantic_checks.is_empty() {
        clean_check_response()
    } else {
        daemon.check(content, request_id, semantic_checks).await?
    };
    if semantic.paused {
        return Ok(paused_evaluation(semantic));
    }
    let semantic_blocking = response_has_blocking_findings(&semantic);
    if semantic_blocking {
        return Ok(Evaluation {
            blocked: true,
            redacted: None,
            findings: findings(&semantic.findings),
            metadata: HashMap::new(),
            reason: "AI Guardian finding".to_string(),
            reason_code: "semantic_content_blocked".to_string(),
        });
    }

    let sensitive_checks: Vec<_> = plan
        .checks
        .iter()
        .copied()
        .filter(|check| matches!(*check, "secrets" | "pii" | "offensive"))
        .collect();
    let sensitive = if sensitive_checks.is_empty() {
        clean_check_response()
    } else {
        daemon.check(content, request_id, sensitive_checks).await?
    };
    if sensitive.paused {
        return Ok(paused_evaluation(sensitive));
    }
    let combined_findings: Vec<_> = semantic
        .findings
        .iter()
        .chain(sensitive.findings.iter())
        .cloned()
        .collect();
    let findings = findings(&combined_findings);
    let blocking = response_has_blocking_findings(&sensitive);
    let redacted = if plan.response_redaction {
        sensitive.redacted.clone()
    } else {
        None
    };
    let sensitive_findings = response_has_findings(&sensitive);
    let blocked = if !sensitive_findings {
        false
    } else if block_all_findings {
        blocking
    } else {
        blocking && redacted.is_none()
    };
    Ok(Evaluation {
        blocked,
        redacted,
        findings,
        metadata: HashMap::new(),
        reason: if sensitive.clean {
            String::new()
        } else {
            "AI Guardian finding".to_string()
        },
        reason_code: if sensitive.clean {
            String::new()
        } else if blocking {
            "semantic_content_blocked".to_string()
        } else {
            "sensitive_content_detected".to_string()
        },
    })
}
