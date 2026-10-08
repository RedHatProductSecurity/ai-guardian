//! Rust OpenShell supervisor middleware.
//!
//! OpenShell owns the external gRPC boundary. Scanner execution stays in the
//! long-lived AI Guardian daemon and is reached through its permission-protected
//! Unix socket (or explicit authenticated REST for remote deployments).

use std::env;
use std::fs;
use std::net::SocketAddr;
use std::path::{Path, PathBuf};
use std::pin::Pin;
use std::collections::HashMap;
use std::time::{SystemTime, UNIX_EPOCH};

use async_stream::try_stream;
use prost_types::{value::Kind, Struct};
use reqwest::header::{AUTHORIZATION, CONTENT_TYPE};
use serde::{Deserialize, Serialize};
use tokio::io::{AsyncReadExt, AsyncWriteExt};
use tokio::net::UnixStream;
use tokio_stream::Stream;
use tonic::{Request, Response, Status};
use tracing::{info, warn};

pub mod openshell {
    pub mod extension {
        pub mod v1 {
            tonic::include_proto!("openshell.extension.v1");
        }
    }

    pub mod middleware {
        pub mod v1 {
            tonic::include_proto!("openshell.middleware.v1");
        }
    }
}

use openshell::extension::v1::{PeerMetadata, ProtocolVersion};
use openshell::middleware::v1::http_response_pre_return_server::{
    HttpResponsePreReturn, HttpResponsePreReturnServer,
};
use openshell::middleware::v1::supervisor_middleware_server::{
    SupervisorMiddleware, SupervisorMiddlewareServer,
};
use openshell::middleware::v1::{
    self as pb, http_response_body_result, http_response_body_unit, http_response_event,
    http_response_event_result, http_response_preflight_result, web_socket_message,
    web_socket_session_event, web_socket_session_event_result, Decision, Finding,
    HttpRequestEvaluation, HttpRequestResult, HttpResponseBlockDelivery, HttpResponseBodyResult,
    HttpResponseBodyTransform, HttpResponseEvent, HttpResponseEventResult,
    HttpResponsePreflightInspect, HttpResponsePreflightResult, HttpResponseTrailersResult,
    MiddlewareBinding, MiddlewareDescribeRequest, MiddlewareManifest,
    SupervisorMiddlewareOperation, SupervisorMiddlewarePhase, ValidateConfigRequest,
    ValidateConfigResponse, WebSocketMessageResult, WebSocketPreflightAction,
    WebSocketPreflightDecision, WebSocketSessionEventResult,
};

const CONTRACT_CAPABILITY: &str = "openshell.supervisor-middleware.contract";
const IMPLEMENTATION_NAME: &str = "ai-guardian/rust-middleware";
const DEFAULT_MAX_PAYLOAD_BYTES: u64 = 256 * 1024;
const MAX_CONFIGURED_PAYLOAD_BYTES: u64 = 4 * 1024 * 1024;
const MAX_PAYLOAD_ENV: &str = "AI_GUARDIAN_MIDDLEWARE_MAX_PAYLOAD_BYTES";

#[derive(Debug, thiserror::Error)]
enum AppError {
    #[error("{0}")]
    Message(String),
    #[error(transparent)]
    Io(#[from] std::io::Error),
    #[error(transparent)]
    Json(#[from] serde_json::Error),
    #[error(transparent)]
    Http(#[from] reqwest::Error),
}

#[derive(Clone)]
struct DaemonClient {
    transport: DaemonTransport,
    project_dir: Option<String>,
    middleware_pause_file: PathBuf,
}

#[derive(Clone)]
enum DaemonTransport {
    Unix {
        path: PathBuf,
    },
    Http {
        http: reqwest::Client,
        base_url: String,
        token: String,
    },
}

#[derive(Debug, Serialize)]
struct CheckRequest<'a> {
    content: &'a str,
    checks: Vec<&'static str>,
    action: &'static str,
    correlation_id: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    project_dir: Option<&'a str>,
}

#[derive(Debug, Deserialize, Default)]
struct CheckResponse {
    #[serde(default)]
    clean: bool,
    #[serde(default)]
    blocked: bool,
    #[serde(default)]
    findings: Vec<DaemonFinding>,
    redacted: Option<String>,
    #[serde(default)]
    paused: bool,
    #[serde(default)]
    pause_source: String,
    #[serde(default)]
    pause_scope: String,
    #[serde(default)]
    pause_remaining_seconds: f64,
    #[serde(default)]
    reason_code: String,
    #[serde(default)]
    message: String,
}

#[derive(Debug, Deserialize, Default)]
struct DaemonPauseStatus {
    #[serde(default)]
    paused: bool,
    #[serde(default)]
    source: Option<String>,
    #[serde(default)]
    scope: Option<String>,
    #[serde(default)]
    remaining_seconds: f64,
    #[serde(default)]
    reason: Option<String>,
}

#[derive(Debug, Deserialize, Default)]
struct DaemonStatus {
    #[serde(default)]
    paused: bool,
    #[serde(default)]
    pause_remaining_seconds: f64,
    #[serde(default)]
    middleware_pause: Option<DaemonPauseStatus>,
}

#[derive(Debug, Deserialize, Default)]
struct PauseEntry {
    #[serde(default)]
    paused: bool,
    #[serde(default)]
    until: f64,
}

#[derive(Debug, Deserialize, Default)]
struct PauseDocument {
    #[serde(default)]
    global: Option<PauseEntry>,
    #[serde(default)]
    projects: HashMap<String, PauseEntry>,
    #[serde(default)]
    dirs: HashMap<String, PauseEntry>,
}

fn current_unix_seconds() -> f64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|duration| duration.as_secs_f64())
        .unwrap_or(0.0)
}

fn active_pause_entry(
    entry: &PauseEntry,
    scope: &str,
    now: f64,
) -> Option<CheckResponse> {
    if !entry.paused || (entry.until > 0.0 && now >= entry.until) {
        return None;
    }
    let remaining = if entry.until > 0.0 {
        entry.until - now
    } else {
        0.0
    };
    Some(paused_check_response(
        "middleware",
        scope,
        remaining,
        "operator_pause",
    ))
}

#[derive(Debug, Deserialize)]
struct DaemonSocketResponse {
    #[serde(rename = "type")]
    message_type: String,
    data: Option<serde_json::Value>,
    error: Option<String>,
}

#[derive(Debug, Clone, Deserialize)]
struct DaemonFinding {
    #[serde(rename = "type")]
    finding_type: String,
    #[serde(default)]
    should_block: Option<bool>,
    #[serde(default)]
    action_taken: Option<String>,
}

#[derive(Debug)]
struct Evaluation {
    blocked: bool,
    redacted: Option<String>,
    findings: Vec<Finding>,
    metadata: HashMap<String, String>,
    reason: String,
    reason_code: String,
}

#[derive(Clone, Debug)]
struct ScanPlan {
    checks: Vec<&'static str>,
    response_redaction: bool,
}

fn clean_check_response() -> CheckResponse {
    CheckResponse {
        clean: true,
        ..Default::default()
    }
}

fn finding_blocks(finding: &DaemonFinding) -> bool {
    // Older daemons do not include action metadata.  Treat those findings as
    // blocking so upgrading the middleware cannot weaken an existing policy.
    finding.should_block.unwrap_or_else(|| {
        !matches!(
            finding.action_taken.as_deref(),
            Some("warn") | Some("log") | Some("log-only")
        )
    })
}

fn response_has_blocking_findings(response: &CheckResponse) -> bool {
    if response.blocked {
        return true;
    }
    if response.findings.is_empty() {
        return !response.clean;
    }
    response.findings.iter().any(finding_blocks)
}

fn response_has_findings(response: &CheckResponse) -> bool {
    response.blocked || !response.clean || !response.findings.is_empty()
}

fn configured_max_payload_bytes() -> u64 {
    match env::var(MAX_PAYLOAD_ENV) {
        Ok(value) => match value.parse::<u64>() {
            Ok(value) if (1..=MAX_CONFIGURED_PAYLOAD_BYTES).contains(&value) => value,
            _ => {
                warn!(
                    value = %value,
                    default = DEFAULT_MAX_PAYLOAD_BYTES,
                    "invalid Rust middleware payload limit; using default"
                );
                DEFAULT_MAX_PAYLOAD_BYTES
            }
        },
        Err(_) => DEFAULT_MAX_PAYLOAD_BYTES,
    }
}

fn parse_socket_check_response(envelope: DaemonSocketResponse) -> Result<CheckResponse, AppError> {
    if envelope.message_type != "response" {
        return Err(AppError::Message(
            "unexpected daemon IPC response".to_string(),
        ));
    }
    if let Some(error) = envelope.error {
        return Err(AppError::Message(error));
    }
    let data = envelope
        .data
        .ok_or_else(|| AppError::Message("daemon IPC response has no data".to_string()))?;
    if let Some(error) = data.get("error").and_then(serde_json::Value::as_str) {
        return Err(AppError::Message(error.to_string()));
    }
    let check_data = data.get("data").unwrap_or(&data).clone();
    Ok(serde_json::from_value(check_data)?)
}

fn paused_check_response(
    source: &str,
    scope: &str,
    remaining_seconds: f64,
    reason: &str,
) -> CheckResponse {
    CheckResponse {
        clean: false,
        findings: Vec::new(),
        redacted: None,
        paused: true,
        pause_source: source.to_string(),
        pause_scope: scope.to_string(),
        pause_remaining_seconds: remaining_seconds.max(0.0),
        reason_code: "middleware_paused".to_string(),
        message: format!("AI Guardian middleware is paused ({reason})"),
    }
}

fn pause_status_response(status: DaemonPauseStatus) -> Option<CheckResponse> {
    if !status.paused {
        return None;
    }
    let source = status.source.as_deref().unwrap_or("daemon");
    let scope = status.scope.as_deref().unwrap_or("global");
    let reason = status.reason.as_deref().unwrap_or("daemon_pause");
    Some(paused_check_response(
        source,
        scope,
        status.remaining_seconds,
        reason,
    ))
}

fn daemon_status_response(status: DaemonStatus) -> Option<CheckResponse> {
    if let Some(pause) = status.middleware_pause {
        if pause.paused {
            return pause_status_response(pause);
        }
    }
    if status.paused {
        return Some(paused_check_response(
            "daemon",
            "global",
            status.pause_remaining_seconds,
            "daemon_pause",
        ));
    }
    None
}

fn pause_metadata(response: &CheckResponse) -> HashMap<String, String> {
    let mut metadata = HashMap::new();
    if !response.pause_source.is_empty() {
        metadata.insert("pause_source".to_string(), response.pause_source.clone());
    }
    if !response.pause_scope.is_empty() {
        metadata.insert("pause_scope".to_string(), response.pause_scope.clone());
    }
    metadata.insert(
        "pause_remaining_seconds".to_string(),
        format!("{:.3}", response.pause_remaining_seconds.max(0.0)),
    );
    metadata
}

fn middleware_project_dir_from_environment() -> Option<String> {
    let value = env::var("AI_GUARDIAN_MIDDLEWARE_PROJECT_DIR")
        .ok()
        .filter(|value| !value.trim().is_empty())?;
    let path = PathBuf::from(value);
    Some(
        fs::canonicalize(&path)
            .unwrap_or(path)
            .to_string_lossy()
            .into_owned(),
    )
}

impl DaemonClient {
    fn from_environment() -> Result<Self, AppError> {
        let project_dir = middleware_project_dir_from_environment();
        let middleware_pause_file = env::var_os("AI_GUARDIAN_MIDDLEWARE_PAUSE_FILE")
            .map(PathBuf::from)
            .unwrap_or_else(|| default_state_dir().join("middleware.paused"));
        if let Ok(value) = env::var("AI_GUARDIAN_DAEMON_URL") {
            if !value.trim().is_empty() {
                let token = daemon_token_from_environment()?;
                let http = reqwest::Client::builder()
                    .connect_timeout(std::time::Duration::from_secs(2))
                    .timeout(std::time::Duration::from_secs(10))
                    .build()?;
                return Ok(Self {
                    transport: DaemonTransport::Http {
                        http,
                        base_url: value.trim_end_matches('/').to_string(),
                        token,
                    },
                    project_dir,
                    middleware_pause_file,
                });
            }
        }
        Ok(Self {
            transport: DaemonTransport::Unix {
                path: env::var("AI_GUARDIAN_DAEMON_SOCKET")
                    .map(PathBuf::from)
                    .unwrap_or_else(|_| default_state_dir().join("daemon.sock")),
            },
            project_dir,
            middleware_pause_file,
        })
    }

    fn local_pause_response(&self) -> Option<CheckResponse> {
        let path = &self.middleware_pause_file;
        if !path.exists() {
            return None;
        }
        let raw = match fs::read_to_string(path) {
            Ok(value) => value,
            Err(error) => {
                warn!(path = %path.display(), %error, "middleware pause state is unreadable");
                return Some(paused_check_response(
                    "middleware",
                    "global",
                    0.0,
                    "middleware_pause_state_unavailable",
                ));
            }
        };
        let document: PauseDocument = match serde_json::from_str(&raw) {
            Ok(value) => value,
            Err(error) => {
                warn!(path = %path.display(), %error, "middleware pause state is invalid");
                return Some(paused_check_response(
                    "middleware",
                    "global",
                    0.0,
                    "middleware_pause_state_unavailable",
                ));
            }
        };
        let now = current_unix_seconds();
        if let Some(entry) = document.global.as_ref() {
            if let Some(response) = active_pause_entry(entry, "global", now) {
                return Some(response);
            }
        }
        if let Some(project_dir) = self.project_dir.as_deref() {
            for entries in [&document.projects, &document.dirs] {
                if let Some(entry) = entries.get(project_dir) {
                    if let Some(response) = active_pause_entry(entry, "project", now) {
                        return Some(response);
                    }
                }
            }
        }
        None
    }

    async fn check(
        &self,
        content: &str,
        request_id: &str,
        checks: Vec<&'static str>,
    ) -> Result<CheckResponse, AppError> {
        let body = CheckRequest {
            content,
            checks,
            action: "block",
            correlation_id: request_id.to_string(),
            project_dir: self.project_dir.as_deref(),
        };
        if content.is_empty() {
            return Ok(self
                .pause_status()
                .await?
                .unwrap_or_else(clean_check_response));
        }
        if let Some(response) = self.local_pause_response() {
            return Ok(response);
        }
        match &self.transport {
            DaemonTransport::Unix { path } => self.check_unix(path, &body).await,
            DaemonTransport::Http {
                http,
                base_url,
                token,
            } => {
                let response = http
                    .post(format!("{base_url}/api/check"))
                    .header(AUTHORIZATION, format!("Bearer {token}"))
                    .header(CONTENT_TYPE, "application/json")
                    .json(&body)
                    .send()
                    .await?;
                if !response.status().is_success() {
                    return Err(AppError::Message(format!(
                        "AI Guardian daemon /api/check returned {}",
                        response.status()
                    )));
                }
                Ok(response.json().await?)
            }
        }
    }

    async fn pause_status(&self) -> Result<Option<CheckResponse>, AppError> {
        if let Some(response) = self.local_pause_response() {
            return Ok(Some(response));
        }
        match &self.transport {
            DaemonTransport::Unix { path } => self.pause_status_unix(path).await,
            DaemonTransport::Http {
                http,
                base_url,
                token,
            } => {
                let mut request = http
                    .get(format!("{base_url}/api/middleware/status"))
                    .header(AUTHORIZATION, format!("Bearer {token}"));
                if let Some(project_dir) = self.project_dir.as_deref() {
                    request = request.query(&[("project_dir", project_dir)]);
                }
                let response = request.send().await?;
                if !response.status().is_success() {
                    return Err(AppError::Message(format!(
                        "AI Guardian daemon /api/middleware/status returned {}",
                        response.status()
                    )));
                }
                let status: DaemonPauseStatus = response.json().await?;
                Ok(pause_status_response(status))
            }
        }
    }

    async fn check_unix(
        &self,
        path: &Path,
        body: &CheckRequest<'_>,
    ) -> Result<CheckResponse, AppError> {
        tokio::time::timeout(
            std::time::Duration::from_secs(10),
            self.check_unix_inner(path, body),
        )
        .await
        .map_err(|_| AppError::Message("daemon IPC request timed out".to_string()))?
    }

    async fn check_unix_inner(
        &self,
        path: &Path,
        body: &CheckRequest<'_>,
    ) -> Result<CheckResponse, AppError> {
        let envelope = serde_json::json!({
            "version": 1,
            "type": "sdk_check",
            "data": {
                "check_type": "middleware",
                "text": body.content,
                "checks": body.checks,
                "action": body.action,
                "correlation_id": body.correlation_id,
                "project_dir": body.project_dir,
            }
        });
        let envelope = self.unix_request(path, envelope).await?;
        parse_socket_check_response(envelope)
    }

    async fn pause_status_unix(&self, path: &Path) -> Result<Option<CheckResponse>, AppError> {
        tokio::time::timeout(
            std::time::Duration::from_secs(10),
            self.pause_status_unix_inner(path),
        )
        .await
        .map_err(|_| AppError::Message("daemon status request timed out".to_string()))?
    }

    async fn pause_status_unix_inner(
        &self,
        path: &Path,
    ) -> Result<Option<CheckResponse>, AppError> {
        let envelope = serde_json::json!({
            "version": 1,
            "type": "status",
            "data": {
                "project_dir": self.project_dir,
            }
        });
        let envelope = self.unix_request(path, envelope).await?;
        let data = envelope
            .data
            .ok_or_else(|| AppError::Message("daemon IPC response has no data".to_string()))?;
        let status_data = data.get("data").unwrap_or(&data).clone();
        let status: DaemonStatus = serde_json::from_value(status_data)?;
        Ok(daemon_status_response(status))
    }

    async fn unix_request(
        &self,
        path: &Path,
        envelope: serde_json::Value,
    ) -> Result<DaemonSocketResponse, AppError> {
        let mut stream = UnixStream::connect(path).await.map_err(|error| {
            AppError::Message(format!(
                "cannot connect to daemon socket {}: {error}",
                path.display()
            ))
        })?;
        let payload = serde_json::to_vec(&envelope)?;
        let length = u32::try_from(payload.len())
            .map_err(|_| AppError::Message("daemon IPC request is too large".to_string()))?;
        stream.write_u32(length).await?;
        stream.write_all(&payload).await?;
        stream.flush().await?;
        let response_length = stream.read_u32().await?;
        if response_length > 10 * 1024 * 1024 {
            return Err(AppError::Message(
                "daemon IPC response is too large".to_string(),
            ));
        }
        let mut response = vec![0_u8; response_length as usize];
        stream.read_exact(&mut response).await?;
        Ok(serde_json::from_slice(&response)?)
    }
}

fn daemon_token_from_environment() -> Result<String, AppError> {
    let token = match env::var("AI_GUARDIAN_DAEMON_TOKEN") {
        Ok(value) if !value.is_empty() => value,
        _ => {
            let token_path = env::var("AI_GUARDIAN_DAEMON_TOKEN_FILE")
                .map(PathBuf::from)
                .unwrap_or_else(|_| default_state_dir().join("daemon.token"));
            fs::read_to_string(token_path)?.trim().to_string()
        }
    };
    if token.is_empty() {
        return Err(AppError::Message(
            "AI Guardian daemon REST token is empty".to_string(),
        ));
    }
    Ok(token)
}

#[derive(Clone)]
struct MiddlewareService {
    daemon: DaemonClient,
    registration_name: String,
    max_payload_bytes: u64,
}

impl MiddlewareService {
    fn findings(findings: &[DaemonFinding]) -> Vec<Finding> {
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

    fn paused_evaluation(response: CheckResponse) -> Evaluation {
        let reason_code = if response.reason_code.is_empty() {
            "middleware_paused".to_string()
        } else {
            response.reason_code
        };
        Evaluation {
            blocked: true,
            redacted: None,
            findings: Vec::new(),
            metadata: pause_metadata(&response),
            reason: if response.message.is_empty() {
                "AI Guardian middleware is paused".to_string()
            } else {
                response.message
            },
            reason_code,
        }
    }

    async fn evaluate(
        &self,
        content: &str,
        request_id: &str,
        plan: &ScanPlan,
        block_all_findings: bool,
    ) -> Result<Evaluation, AppError> {
        if plan.checks.is_empty() {
            if let Some(response) = self.daemon.pause_status().await? {
                return Ok(Self::paused_evaluation(response));
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
        // path can fail independently; it must not hide a valid prompt-
        // injection denial behind a generic middleware failure.
        let semantic_checks: Vec<_> = plan
            .checks
            .iter()
            .copied()
            .filter(|check| {
                matches!(*check, "injection" | "context_poisoning" | "canary")
            })
            .collect();
        let semantic = if semantic_checks.is_empty() {
            clean_check_response()
        } else {
            self.daemon
                .check(content, request_id, semantic_checks)
                .await?
        };
        if semantic.paused {
            return Ok(Self::paused_evaluation(semantic));
        }
        let semantic_blocking = response_has_blocking_findings(&semantic);
        if semantic_blocking {
            return Ok(Evaluation {
                blocked: true,
                redacted: None,
                findings: Self::findings(&semantic.findings),
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
            self.daemon
                .check(content, request_id, sensitive_checks)
                .await?
        };
        if sensitive.paused {
            return Ok(Self::paused_evaluation(sensitive));
        }
        let combined_findings: Vec<_> = semantic
            .findings
            .iter()
            .chain(sensitive.findings.iter())
            .cloned()
            .collect();
        let findings = Self::findings(&combined_findings);
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

    fn validate_gateway(gateway: Option<PeerMetadata>) -> Result<(), Status> {
        let gateway = gateway.ok_or_else(|| {
            Status::failed_precondition("gateway did not provide protocol metadata")
        })?;
        let version = gateway
            .protocol_version
            .ok_or_else(|| Status::failed_precondition("gateway protocol version is missing"))?;
        if version.major != 1 {
            return Err(Status::failed_precondition(format!(
                "unsupported OpenShell protocol {}.{}",
                version.major, version.minor
            )));
        }
        if !gateway
            .supported_capabilities
            .iter()
            .any(|value| value == CONTRACT_CAPABILITY)
        {
            return Err(Status::failed_precondition(
                "gateway does not support supervisor-middleware contract",
            ));
        }
        Ok(())
    }

    fn scan_plan(config: Option<&Struct>) -> Result<ScanPlan, Status> {
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
        let ownership =
            config
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
}

#[tonic::async_trait]
impl SupervisorMiddleware for MiddlewareService {
    type EvaluateWebSocketSessionStream =
        Pin<Box<dyn Stream<Item = Result<pb::WebSocketSessionEventResult, Status>> + Send>>;

    async fn describe(
        &self,
        request: Request<MiddlewareDescribeRequest>,
    ) -> Result<Response<MiddlewareManifest>, Status> {
        Self::validate_gateway(request.into_inner().gateway)?;
        let supported_capabilities = vec![
            CONTRACT_CAPABILITY.to_string(),
            "openshell.middleware.request-scanning".to_string(),
            "openshell.middleware.response-redaction".to_string(),
            "openshell.middleware.semantic-scanning".to_string(),
            "openshell.middleware.websocket-text".to_string(),
        ];
        Ok(Response::new(MiddlewareManifest {
            name: IMPLEMENTATION_NAME.to_string(),
            service_version: env!("CARGO_PKG_VERSION").to_string(),
            bindings: vec![
                MiddlewareBinding {
                    operation: SupervisorMiddlewareOperation::HttpRequest as i32,
                    phase: SupervisorMiddlewarePhase::PreCredentials as i32,
                    max_payload_bytes: self.max_payload_bytes,
                    request_timeout: None,
                },
                MiddlewareBinding {
                    operation: SupervisorMiddlewareOperation::HttpResponse as i32,
                    phase: SupervisorMiddlewarePhase::PreReturn as i32,
                    max_payload_bytes: self.max_payload_bytes,
                    request_timeout: None,
                },
                MiddlewareBinding {
                    operation: SupervisorMiddlewareOperation::WebsocketMessage as i32,
                    phase: SupervisorMiddlewarePhase::PreCredentials as i32,
                    max_payload_bytes: self.max_payload_bytes,
                    request_timeout: None,
                },
            ],
            expected_audience: String::new(),
            extension: Some(PeerMetadata {
                protocol_version: Some(ProtocolVersion { major: 1, minor: 0 }),
                implementation_name: IMPLEMENTATION_NAME.to_string(),
                implementation_version: env!("CARGO_PKG_VERSION").to_string(),
                supported_capabilities,
                required_capabilities: vec![CONTRACT_CAPABILITY.to_string()],
            }),
        }))
    }

    async fn validate_config(
        &self,
        request: Request<ValidateConfigRequest>,
    ) -> Result<Response<ValidateConfigResponse>, Status> {
        let request = request.into_inner();
        if !request.middleware_name.is_empty() && request.middleware_name != self.registration_name
        {
            return Ok(Response::new(ValidateConfigResponse {
                valid: false,
                reason: "middleware registration name does not match".to_string(),
            }));
        }
        if let Err(error) = Self::scan_plan(request.config.as_ref()) {
            return Ok(Response::new(ValidateConfigResponse {
                valid: false,
                reason: error.message().to_string(),
            }));
        }
        Ok(Response::new(ValidateConfigResponse {
            valid: true,
            reason: String::new(),
        }))
    }

    async fn evaluate_http_request(
        &self,
        request: Request<HttpRequestEvaluation>,
    ) -> Result<Response<HttpRequestResult>, Status> {
        let request = request.into_inner();
        let request_id = request
            .context
            .as_ref()
            .map(|value| value.request_id.as_str())
            .unwrap_or("");
        let host = request
            .target
            .as_ref()
            .map(|target| target.host.as_str())
            .unwrap_or("");
        let method = request
            .target
            .as_ref()
            .map(|target| target.method.as_str())
            .unwrap_or("");
        let body_bytes = request.body.len();
        if request.phase != SupervisorMiddlewarePhase::PreCredentials as i32 {
            warn!(
                request_id,
                host,
                method,
                phase = request.phase,
                body_bytes,
                "Rust middleware rejected unsupported request phase"
            );
            return Err(Status::invalid_argument("unsupported HTTP request phase"));
        }
        if body_bytes > self.max_payload_bytes as usize {
            return Ok(Response::new(HttpRequestResult {
                decision: Decision::Deny as i32,
                reason: "AI Guardian middleware payload limit exceeded".to_string(),
                reason_code: "payload_limit_exceeded".to_string(),
                ..Default::default()
            }));
        }
        let content = String::from_utf8(request.body)
            .map_err(|_| Status::invalid_argument("request body must be UTF-8"))?;
        let request_id = request_id.to_string();
        let plan = if content.is_empty() {
            ScanPlan {
                checks: Vec::new(),
                response_redaction: false,
            }
        } else {
            Self::scan_plan(request.config.as_ref())?
        };
        let result = match self
            .evaluate(&content, &request_id, &plan, true)
            .await
        {
            Ok(result) => result,
            Err(error) => {
                warn!(
                    request_id = %request_id,
                    host,
                    method,
                    "Rust middleware control plane unavailable; denying request: {error}"
                );
                return Ok(Response::new(HttpRequestResult {
                    decision: Decision::Deny as i32,
                    reason: "AI Guardian middleware control plane unavailable".to_string(),
                    reason_code: "middleware_control_plane_unavailable".to_string(),
                    ..Default::default()
                }));
            }
        };
        info!(
            request_id = %request_id,
            host,
            method,
            body_bytes,
            blocked = result.blocked,
            reason_code = %result.reason_code,
            finding_count = result.findings.len(),
            "Rust middleware request decision"
        );
        Ok(Response::new(HttpRequestResult {
            decision: if result.blocked {
                Decision::Deny as i32
            } else {
                Decision::Allow as i32
            },
            reason: result.reason,
            reason_code: result.reason_code,
            findings: result.findings,
            metadata: result.metadata,
            ..Default::default()
        }))
    }

    async fn evaluate_web_socket_session(
        &self,
        request: Request<tonic::Streaming<pb::WebSocketSessionEvent>>,
    ) -> Result<Response<Self::EvaluateWebSocketSessionStream>, Status> {
        let mut events = request.into_inner();
        let service = self.clone();
        let stream = try_stream! {
            let mut preflight_seen = false;
            let mut started = false;
            let mut skipped = false;
            let mut sequence = 0_u64;
            let mut request_id = String::new();
            let mut target_host = String::new();
            let mut middleware_name = String::new();
            let mut plan = ScanPlan {
                checks: Vec::new(),
                response_redaction: false,
            };

            while let Some(event) = events.message().await? {
                match event.event {
                    Some(web_socket_session_event::Event::Preflight(preflight)) => {
                        if preflight_seen || started {
                            Err(Status::failed_precondition(
                                "duplicate WebSocket preflight",
                            ))?;
                        }
                        if preflight.phase
                            != SupervisorMiddlewarePhase::PreCredentials as i32
                        {
                            Err(Status::invalid_argument("unsupported WebSocket phase"))?;
                        }
                        let context = preflight.context.as_ref().ok_or_else(|| {
                            Status::failed_precondition(
                                "WebSocket preflight context is required",
                            )
                        })?;
                        let target = preflight.target.as_ref().ok_or_else(|| {
                            Status::failed_precondition(
                                "WebSocket preflight target is required",
                            )
                        })?;
                        request_id = context.request_id.clone();
                        target_host = target.host.clone();
                        middleware_name = preflight.middleware_name.clone();
                        plan = MiddlewareService::scan_plan(preflight.config.as_ref())?;
                        preflight_seen = true;
                        match service.daemon.pause_status().await {
                            Ok(Some(response)) => {
                                let metadata = pause_metadata(&response);
                                yield WebSocketSessionEventResult {
                                    result: Some(
                                        web_socket_session_event_result::Result::PreflightDecision(
                                            WebSocketPreflightDecision {
                                                action: WebSocketPreflightAction::Deny as i32,
                                                reason: response.message,
                                                reason_code: response.reason_code,
                                                metadata,
                                                ..Default::default()
                                            },
                                        ),
                                    ),
                                };
                                return;
                            }
                            Ok(None) => {}
                            Err(error) => {
                                warn!(
                                    request_id = %request_id,
                                    host = %target_host,
                                    "Rust middleware control plane unavailable; denying WebSocket upgrade: {error}"
                                );
                                yield WebSocketSessionEventResult {
                                    result: Some(
                                        web_socket_session_event_result::Result::PreflightDecision(
                                            WebSocketPreflightDecision {
                                                action: WebSocketPreflightAction::Deny as i32,
                                                reason: "AI Guardian middleware control plane unavailable".to_string(),
                                                reason_code: "middleware_control_plane_unavailable".to_string(),
                                                metadata: HashMap::new(),
                                                ..Default::default()
                                            },
                                        ),
                                    ),
                                };
                                return;
                            }
                        }
                        if plan.checks.is_empty() {
                            skipped = true;
                            yield WebSocketSessionEventResult {
                                result: Some(
                                    web_socket_session_event_result::Result::PreflightDecision(
                                        WebSocketPreflightDecision {
                                            action: WebSocketPreflightAction::Skip as i32,
                                            ..Default::default()
                                        },
                                    ),
                                ),
                            };
                        } else {
                            yield WebSocketSessionEventResult {
                                result: Some(
                                    web_socket_session_event_result::Result::PreflightDecision(
                                        WebSocketPreflightDecision {
                                            action: WebSocketPreflightAction::Inspect as i32,
                                            ..Default::default()
                                        },
                                    ),
                                ),
                            };
                        }
                    }
                    Some(web_socket_session_event::Event::SessionStart(_)) => {
                        if !preflight_seen || skipped || started {
                            Err(Status::failed_precondition(
                                "invalid WebSocket session lifecycle",
                            ))?;
                        }
                        started = true;
                    }
                    Some(web_socket_session_event::Event::Message(message)) => {
                        if !preflight_seen || skipped || !started {
                            Err(Status::failed_precondition(
                                "WebSocket message before session start",
                            ))?;
                        }
                        if message.sequence == 0 || message.sequence <= sequence {
                            Err(Status::invalid_argument(
                                "WebSocket message sequence must increase",
                            ))?;
                        }
                        sequence = message.sequence;
                        let payload = message.payload.ok_or_else(|| {
                            Status::invalid_argument("WebSocket payload is required")
                        })?;
                        let text = match payload {
                            web_socket_message::Payload::Text(text) => text,
                            web_socket_message::Payload::Binary(_) => {
                                info!(
                                    request_id = %request_id,
                                    host = %target_host,
                                    middleware = %middleware_name,
                                    sequence,
                                    "Rust middleware denied binary WebSocket message"
                                );
                                yield WebSocketSessionEventResult {
                                    result: Some(
                                        web_socket_session_event_result::Result::MessageResult(
                                            WebSocketMessageResult {
                                                sequence,
                                                decision: Decision::Deny as i32,
                                                reason: "binary WebSocket payloads are unsupported"
                                                    .to_string(),
                                                reason_code: "unsupported_websocket_payload"
                                                    .to_string(),
                                                ..Default::default()
                                            },
                                        ),
                                    ),
                                };
                                return;
                            }
                        };
                        if text.len() > service.max_payload_bytes as usize {
                            info!(
                                request_id = %request_id,
                                host = %target_host,
                                middleware = %middleware_name,
                                sequence,
                                body_bytes = text.len(),
                                "Rust middleware denied oversized WebSocket message"
                            );
                            yield WebSocketSessionEventResult {
                                result: Some(
                                    web_socket_session_event_result::Result::MessageResult(
                                        WebSocketMessageResult {
                                            sequence,
                                            decision: Decision::Deny as i32,
                                            reason: "WebSocket payload exceeds configured limit"
                                                .to_string(),
                                            reason_code: "payload_limit_exceeded".to_string(),
                                            ..Default::default()
                                        },
                                    ),
                                ),
                            };
                            return;
                        }
                        let result = match service
                            .evaluate(&text, &request_id, &plan, true)
                            .await
                        {
                            Ok(result) => result,
                            Err(error) => {
                                warn!(
                                    request_id = %request_id,
                                    host = %target_host,
                                    middleware = %middleware_name,
                                    sequence,
                                    "Rust middleware control plane unavailable; denying WebSocket message: {error}"
                                );
                                yield WebSocketSessionEventResult {
                                    result: Some(
                                        web_socket_session_event_result::Result::MessageResult(
                                            WebSocketMessageResult {
                                                sequence,
                                                decision: Decision::Deny as i32,
                                                reason: "AI Guardian middleware control plane unavailable".to_string(),
                                                reason_code: "middleware_control_plane_unavailable".to_string(),
                                                ..Default::default()
                                            },
                                        ),
                                    ),
                                };
                                return;
                            }
                        };
                        let blocked = result.blocked;
                        let reason_code = if blocked {
                            result.reason_code.clone()
                        } else {
                            String::new()
                        };
                        info!(
                            request_id = %request_id,
                            host = %target_host,
                            middleware = %middleware_name,
                            sequence,
                            blocked,
                            reason_code = %reason_code,
                            finding_count = result.findings.len(),
                            "Rust middleware WebSocket message decision"
                        );
                        yield WebSocketSessionEventResult {
                            result: Some(
                                web_socket_session_event_result::Result::MessageResult(
                                    WebSocketMessageResult {
                                        sequence,
                                        decision: if blocked {
                                            Decision::Deny as i32
                                        } else {
                                            Decision::Allow as i32
                                        },
                                        reason: result.reason,
                                        reason_code,
                                        findings: result.findings,
                                        metadata: result.metadata,
                                        ..Default::default()
                                    },
                                ),
                            ),
                        };
                        if blocked {
                            return;
                        }
                    }
                    Some(web_socket_session_event::Event::SessionEnd(_)) => return,
                    None => Err(Status::invalid_argument("WebSocket event is required"))?,
                }
            }
        };
        Ok(Response::new(Box::pin(stream)))
    }
}

#[tonic::async_trait]
impl HttpResponsePreReturn for MiddlewareService {
    type EvaluateStream =
        Pin<Box<dyn Stream<Item = Result<HttpResponseEventResult, Status>> + Send>>;

    async fn evaluate(
        &self,
        request: Request<tonic::Streaming<HttpResponseEvent>>,
    ) -> Result<Response<Self::EvaluateStream>, Status> {
        let mut events = request.into_inner();
        let service = self.clone();
        let stream = try_stream! {
            let mut request_id = String::new();
            let mut body = Vec::new();
            let mut plan = ScanPlan {
                checks: vec!["injection", "context_poisoning", "secrets", "pii"],
                response_redaction: true,
            };
            let mut body_mode = pb::HttpResponseBodyMode::WholeBodyBytes as i32;
            while let Some(event) = events.message().await? {
                match event.event {
                    Some(http_response_event::Event::Preflight(preflight)) => {
                        request_id = preflight.context.as_ref().map(|value| value.request_id.clone()).unwrap_or_default();
                        let pause_response = match service.daemon.pause_status().await {
                            Ok(response) => response,
                            Err(error) => {
                                warn!(
                                    request_id = %request_id,
                                    "Rust middleware control plane unavailable; blocking response: {error}"
                                );
                                yield HttpResponseEventResult {
                                    result: Some(http_response_event_result::Result::PreflightResult(
                                        HttpResponsePreflightResult {
                                            action: Some(http_response_preflight_result::Action::BlockDelivery(
                                                HttpResponseBlockDelivery {},
                                            )),
                                            reason: "AI Guardian middleware control plane unavailable".to_string(),
                                            reason_code: "middleware_control_plane_unavailable".to_string(),
                                            ..Default::default()
                                        },
                                    )),
                                };
                                return;
                            }
                        };
                        if let Some(response) = pause_response {
                            let metadata = pause_metadata(&response);
                            yield HttpResponseEventResult {
                                result: Some(http_response_event_result::Result::PreflightResult(
                                    HttpResponsePreflightResult {
                                        action: Some(http_response_preflight_result::Action::BlockDelivery(
                                            HttpResponseBlockDelivery {},
                                        )),
                                        reason: response.message,
                                        reason_code: response.reason_code,
                                        metadata,
                                        ..Default::default()
                                    },
                                )),
                            };
                            return;
                        }
                        plan = MiddlewareService::scan_plan(preflight.config.as_ref())?;
                        body_mode = if preflight
                            .permitted_body_modes
                            .iter()
                            .any(|mode| *mode == pb::HttpResponseBodyMode::WholeBodyBytes as i32)
                        {
                            pb::HttpResponseBodyMode::WholeBodyBytes as i32
                        } else if preflight
                            .permitted_body_modes
                            .iter()
                            .any(|mode| *mode == pb::HttpResponseBodyMode::StreamBytes as i32)
                        {
                            pb::HttpResponseBodyMode::StreamBytes as i32
                        } else {
                            Err(Status::failed_precondition(
                                "stream or whole-body response inspection is required",
                            ))?
                        };
                        yield HttpResponseEventResult {
                            result: Some(http_response_event_result::Result::PreflightResult(
                                HttpResponsePreflightResult {
                                    action: Some(http_response_preflight_result::Action::Inspect(
                                        HttpResponsePreflightInspect {
                                            body_mode,
                                            header_mutations: Vec::new(),
                                        },
                                    )),
                                    ..Default::default()
                                },
                            )),
                        };
                    }
                    Some(http_response_event::Event::Body(unit)) => {
                        let body_sequence = unit.sequence;
                        let data = match unit.payload {
                            Some(http_response_body_unit::Payload::Data(data)) => data,
                            None => Vec::new(),
                        };
                        let content_bytes = if body_mode
                            == pb::HttpResponseBodyMode::StreamBytes as i32
                        {
                            if data.len() > service.max_payload_bytes as usize {
                                yield HttpResponseEventResult {
                                    result: Some(http_response_event_result::Result::BodyResult(
                                        HttpResponseBodyResult {
                                            sequence: body_sequence,
                                            action: Some(
                                                http_response_body_result::Action::BlockDelivery(
                                                    HttpResponseBlockDelivery {},
                                                ),
                                            ),
                                            reason: "AI Guardian middleware payload limit exceeded"
                                                .to_string(),
                                            reason_code: "payload_limit_exceeded".to_string(),
                                            ..Default::default()
                                        },
                                    )),
                                };
                                return;
                            }
                            data
                        } else {
                            body.extend(data);
                            if body.len() > service.max_payload_bytes as usize {
                                yield HttpResponseEventResult {
                                    result: Some(http_response_event_result::Result::BodyResult(
                                        HttpResponseBodyResult {
                                            sequence: body_sequence,
                                            action: Some(
                                                http_response_body_result::Action::BlockDelivery(
                                                    HttpResponseBlockDelivery {},
                                                ),
                                            ),
                                            reason: "AI Guardian middleware payload limit exceeded"
                                                .to_string(),
                                            reason_code: "payload_limit_exceeded".to_string(),
                                            ..Default::default()
                                        },
                                    )),
                                };
                                return;
                            }
                            if !unit.end_of_stream {
                                continue;
                            }
                            body.clone()
                        };
                        let content = String::from_utf8(content_bytes)
                            .map_err(|_| Status::invalid_argument("response body must be UTF-8"))?;
                        let result = match service
                            .evaluate(&content, &request_id, &plan, false)
                            .await
                        {
                            Ok(result) => result,
                            Err(error) => {
                                warn!(
                                    request_id = %request_id,
                                    "Rust middleware control plane unavailable; blocking response: {error}"
                                );
                                yield HttpResponseEventResult {
                                    result: Some(http_response_event_result::Result::BodyResult(
                                        HttpResponseBodyResult {
                                            sequence: body_sequence,
                                            action: Some(
                                                http_response_body_result::Action::BlockDelivery(
                                                    HttpResponseBlockDelivery {},
                                                ),
                                            ),
                                            reason: "AI Guardian middleware control plane unavailable".to_string(),
                                            reason_code: "middleware_control_plane_unavailable".to_string(),
                                            ..Default::default()
                                        },
                                    )),
                                };
                                return;
                            }
                        };
                        info!(
                            request_id = %request_id,
                            blocked = result.blocked,
                            reason_code = %result.reason_code,
                            finding_count = result.findings.len(),
                            "Rust middleware response decision"
                        );
                        let action = if result.blocked {
                            http_response_body_result::Action::BlockDelivery(
                                HttpResponseBlockDelivery {},
                            )
                        } else if let Some(redacted) = result.redacted {
                            http_response_body_result::Action::Transform(
                                HttpResponseBodyTransform {
                                    replacement: Some(
                                        pb::http_response_body_transform::Replacement::Data(
                                            redacted.into_bytes(),
                                        ),
                                    ),
                                },
                            )
                        } else {
                            http_response_body_result::Action::PassThrough(
                                pb::HttpResponseBodyPassThrough {},
                            )
                        };
                        let blocked = result.blocked;
                        yield HttpResponseEventResult {
                            result: Some(http_response_event_result::Result::BodyResult(
                                HttpResponseBodyResult {
                                    sequence: body_sequence,
                                    action: Some(action),
                                    reason: result.reason,
                                    reason_code: result.reason_code,
                                    findings: result.findings,
                                    metadata: result.metadata,
                                    ..Default::default()
                                },
                            )),
                        };
                        if blocked {
                            return;
                        }
                    }
                    Some(http_response_event::Event::Trailers(_)) => {
                        yield HttpResponseEventResult {
                            result: Some(http_response_event_result::Result::TrailersResult(
                                HttpResponseTrailersResult::default(),
                            )),
                        };
                    }
                    Some(http_response_event::Event::SessionEnd(_)) => break,
                    None => Err(Status::invalid_argument("response event is required"))?,
                }
            }
        };
        Ok(Response::new(Box::pin(stream)))
    }
}

fn default_state_dir() -> PathBuf {
    env::var_os("AI_GUARDIAN_STATE_DIR")
        .map(PathBuf::from)
        .or_else(|| {
            env::var_os("XDG_STATE_HOME").map(|path| PathBuf::from(path).join("ai-guardian"))
        })
        .or_else(|| {
            if cfg!(windows) {
                env::var_os("LOCALAPPDATA")
                    .map(|path| PathBuf::from(path).join("ai-guardian/state"))
                    .or_else(|| {
                        env::var_os("USERPROFILE")
                            .map(|path| PathBuf::from(path).join("AppData/Local/ai-guardian/state"))
                    })
            } else {
                env::var_os("HOME").map(|path| PathBuf::from(path).join(".local/state/ai-guardian"))
            }
        })
        .unwrap_or_else(|| PathBuf::from(".ai-guardian"))
}

#[tokio::main]
async fn main() -> Result<(), Box<dyn std::error::Error>> {
    tracing_subscriber::fmt()
        .with_env_filter(
            tracing_subscriber::EnvFilter::try_from_default_env().unwrap_or_else(|_| "info".into()),
        )
        .init();

    let bind =
        env::var("AI_GUARDIAN_MIDDLEWARE_BIND").unwrap_or_else(|_| "127.0.0.1:50051".to_string());
    let address: SocketAddr = bind.parse()?;
    let service = MiddlewareService {
        daemon: DaemonClient::from_environment()?,
        registration_name: env::var("AI_GUARDIAN_MIDDLEWARE_REGISTRATION")
            .unwrap_or_else(|_| "content-guard-test".to_string()),
        max_payload_bytes: configured_max_payload_bytes(),
    };

    info!(%address, "Rust OpenShell middleware listening");
    let result = tonic::transport::Server::builder()
        .add_service(SupervisorMiddlewareServer::new(service.clone()))
        .add_service(HttpResponsePreReturnServer::new(service))
        .serve_with_shutdown(address, shutdown_signal())
        .await;
    remove_pid_file_if_owned();
    result?;
    Ok(())
}

async fn shutdown_signal() {
    #[cfg(unix)]
    {
        let mut terminate =
            tokio::signal::unix::signal(tokio::signal::unix::SignalKind::terminate())
                .expect("install SIGTERM handler");
        tokio::select! {
            _ = tokio::signal::ctrl_c() => {}
            _ = terminate.recv() => {}
        }
    }
    #[cfg(not(unix))]
    {
        let _ = tokio::signal::ctrl_c().await;
    }
}

fn remove_pid_file_if_owned() {
    let Some(path) = env::var_os("AI_GUARDIAN_MIDDLEWARE_PID_FILE") else {
        return;
    };
    let path = PathBuf::from(path);
    let Ok(raw) = fs::read_to_string(&path) else {
        return;
    };
    let Ok(value) = serde_json::from_str::<serde_json::Value>(&raw) else {
        return;
    };
    if value.get("pid").and_then(|pid| pid.as_u64()) == Some(std::process::id() as u64) {
        let _ = fs::remove_file(path);
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::collections::BTreeMap;

    #[test]
    fn gateway_metadata_requires_contract_capability() {
        let error = MiddlewareService::validate_gateway(Some(PeerMetadata {
            protocol_version: Some(ProtocolVersion { major: 1, minor: 0 }),
            supported_capabilities: Vec::new(),
            ..Default::default()
        }))
        .expect_err("missing contract capability");
        assert!(error.message().contains("supervisor-middleware contract"));
    }

    #[test]
    fn scanner_plan_routes_supported_keys_and_rejects_local_only_scanners() {
        let config = Struct {
            fields: BTreeMap::from([(
                "scanner_ownership".to_string(),
                prost_types::Value {
                    kind: Some(Kind::StructValue(Struct {
                        fields: BTreeMap::from([
                            (
                                "prompt_injection".to_string(),
                                prost_types::Value {
                                    kind: Some(Kind::StringValue("middleware".to_string())),
                                },
                            ),
                            (
                                "supply_chain".to_string(),
                                prost_types::Value {
                                    kind: Some(Kind::StringValue("middleware".to_string())),
                                },
                            ),
                        ]),
                    })),
                },
            )]),
        };
        let error = MiddlewareService::scan_plan(Some(&config)).expect_err("local-only scanner");
        assert!(error.message().contains("supply_chain"));
    }

    #[test]
    fn scanner_plan_routes_canary_and_skips_hook_owned_scanners() {
        let config = Struct {
            fields: BTreeMap::from([(
                "scanner_ownership".to_string(),
                prost_types::Value {
                    kind: Some(Kind::StructValue(Struct {
                        fields: BTreeMap::from([
                            (
                                "canary_detection".to_string(),
                                prost_types::Value {
                                    kind: Some(Kind::StringValue("middleware".to_string())),
                                },
                            ),
                            (
                                "prompt_injection".to_string(),
                                prost_types::Value {
                                    kind: Some(Kind::StringValue("middleware".to_string())),
                                },
                            ),
                            (
                                "scan_pii".to_string(),
                                prost_types::Value {
                                    kind: Some(Kind::StringValue("hooks".to_string())),
                                },
                            ),
                        ]),
                    })),
                },
            )]),
        };

        let plan = MiddlewareService::scan_plan(Some(&config)).expect("valid scan plan");
        assert!(plan.checks.contains(&"injection"));
        assert!(plan.checks.contains(&"canary"));
        assert!(!plan.checks.contains(&"pii"));
    }

    #[test]
    fn scanner_plan_rejects_both_with_actionable_runtime_message() {
        let config = Struct {
            fields: BTreeMap::from([(
                "scanner_ownership".to_string(),
                prost_types::Value {
                    kind: Some(Kind::StructValue(Struct {
                        fields: BTreeMap::from([(
                            "prompt_injection".to_string(),
                            prost_types::Value {
                                kind: Some(Kind::StringValue("both".to_string())),
                            },
                        ]),
                    })),
                },
            )]),
        };

        let error = MiddlewareService::scan_plan(Some(&config)).expect_err("both must fail");
        assert!(error
            .message()
            .contains("scanner ownership 'both' is not supported by Rust middleware"));
        assert!(error.message().contains("prompt_injection"));
    }

    #[test]
    fn daemon_warning_metadata_does_not_block() {
        let finding: DaemonFinding = serde_json::from_value(serde_json::json!({
            "type": "prompt_injection",
            "should_block": false,
            "action_taken": "warn"
        }))
        .expect("warning finding");
        assert!(!finding_blocks(&finding));
        assert!(!response_has_blocking_findings(&CheckResponse {
            clean: false,
            blocked: false,
            findings: vec![finding],
            ..Default::default()
        }));
    }

    #[tokio::test]
    async fn describe_advertises_text_websocket_binding() {
        let service = MiddlewareService {
            daemon: DaemonClient {
                transport: DaemonTransport::Unix {
                    path: PathBuf::from("/unused/daemon.sock"),
                },
                project_dir: None,
                middleware_pause_file: PathBuf::from("/unused/middleware.paused"),
            },
            registration_name: "content-guard-test".to_string(),
            max_payload_bytes: DEFAULT_MAX_PAYLOAD_BYTES,
        };
        let response = SupervisorMiddleware::describe(
            &service,
            Request::new(MiddlewareDescribeRequest {
                gateway: Some(PeerMetadata {
                    protocol_version: Some(ProtocolVersion { major: 1, minor: 0 }),
                    supported_capabilities: vec![CONTRACT_CAPABILITY.to_string()],
                    ..Default::default()
                }),
            }),
        )
        .await
        .expect("compatible gateway metadata")
        .into_inner();

        assert!(response
            .extension
            .expect("extension metadata")
            .supported_capabilities
            .iter()
            .any(|capability| capability == "openshell.middleware.websocket-text"));
        assert!(response.bindings.iter().any(|binding| {
            binding.operation == SupervisorMiddlewareOperation::WebsocketMessage as i32
                && binding.phase == SupervisorMiddlewarePhase::PreCredentials as i32
        }));
    }

    #[test]
    fn parses_nested_daemon_socket_check_response() {
        let envelope: DaemonSocketResponse = serde_json::from_value(serde_json::json!({
            "type": "response",
            "data": {
                "data": {
                    "clean": true,
                    "findings": []
                }
            }
        }))
        .expect("valid daemon response envelope");
        let response = parse_socket_check_response(envelope).expect("nested check result");
        assert!(response.clean);
        assert!(response.findings.is_empty());
    }

    #[test]
    fn parses_paused_daemon_check_response() {
        let envelope: DaemonSocketResponse = serde_json::from_value(serde_json::json!({
            "type": "response",
            "data": {
                "data": {
                    "clean": false,
                    "findings": [],
                    "paused": true,
                    "reason_code": "middleware_paused",
                    "pause_source": "daemon",
                    "pause_scope": "global",
                    "pause_remaining_seconds": 30.0
                }
            }
        }))
        .expect("valid paused daemon response envelope");
        let response = parse_socket_check_response(envelope).expect("paused check result");
        assert!(response.paused);
        assert_eq!(response.reason_code, "middleware_paused");
        assert_eq!(response.pause_source, "daemon");
        assert_eq!(response.pause_remaining_seconds, 30.0);
    }
}
