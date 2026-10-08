//! Authenticated AI Guardian daemon transports and pause state.

use std::collections::HashMap;
use std::env;
use std::fs;
use std::path::{Path, PathBuf};
use std::time::Duration;

use reqwest::header::{AUTHORIZATION, CONTENT_TYPE};
use serde::{Deserialize, Serialize};
use tokio::io::{AsyncReadExt, AsyncWriteExt};
use tokio::net::UnixStream;

use super::AppError;

#[derive(Clone)]
pub(super) struct DaemonClient {
    pub(super) transport: DaemonTransport,
    pub(super) project_dir: Option<String>,
}

#[derive(Clone)]
pub(super) enum DaemonTransport {
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
pub(super) struct CheckResponse {
    #[serde(default)]
    pub(super) clean: bool,
    #[serde(default)]
    pub(super) blocked: bool,
    #[serde(default)]
    pub(super) findings: Vec<DaemonFinding>,
    pub(super) redacted: Option<String>,
    #[serde(default)]
    pub(super) paused: bool,
    #[serde(default)]
    pub(super) pause_source: String,
    #[serde(default)]
    pub(super) pause_scope: String,
    #[serde(default)]
    pub(super) pause_remaining_seconds: f64,
    #[serde(default)]
    pub(super) reason_code: String,
    #[serde(default)]
    pub(super) message: String,
}

#[derive(Debug, Deserialize, Default)]
pub(super) struct DaemonPauseStatus {
    #[serde(default)]
    pub(super) paused: bool,
    #[serde(default)]
    pub(super) source: Option<String>,
    #[serde(default)]
    pub(super) scope: Option<String>,
    #[serde(default)]
    pub(super) remaining_seconds: f64,
    #[serde(default)]
    pub(super) reason: Option<String>,
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

#[derive(Debug, Deserialize)]
pub(super) struct DaemonSocketResponse {
    #[serde(rename = "type")]
    message_type: String,
    data: Option<serde_json::Value>,
    error: Option<String>,
}

#[derive(Debug, Clone, Deserialize)]
pub(super) struct DaemonFinding {
    #[serde(rename = "type")]
    pub(super) finding_type: String,
    #[serde(default)]
    pub(super) should_block: Option<bool>,
    #[serde(default)]
    pub(super) action_taken: Option<String>,
}

impl DaemonTransport {
    #[cfg(test)]
    pub(super) fn unix(path: PathBuf) -> Self {
        Self::Unix { path }
    }
}

pub(super) fn default_state_dir() -> PathBuf {
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

pub(super) fn clean_check_response() -> CheckResponse {
    CheckResponse {
        clean: true,
        ..Default::default()
    }
}

pub(super) fn parse_socket_check_response(
    envelope: DaemonSocketResponse,
) -> Result<CheckResponse, AppError> {
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

pub(super) fn paused_check_response(
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
        ..Default::default()
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

pub(super) fn pause_metadata(response: &CheckResponse) -> HashMap<String, String> {
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
    pub(super) fn from_environment() -> Result<Self, AppError> {
        let project_dir = middleware_project_dir_from_environment();
        if let Ok(value) = env::var("AI_GUARDIAN_DAEMON_URL") {
            if !value.trim().is_empty() {
                let token = daemon_token_from_environment()?;
                let http = reqwest::Client::builder()
                    .connect_timeout(Duration::from_secs(2))
                    .timeout(Duration::from_secs(10))
                    .build()?;
                return Ok(Self {
                    transport: DaemonTransport::Http {
                        http,
                        base_url: value.trim_end_matches('/').to_string(),
                        token,
                    },
                    project_dir,
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
        })
    }

    pub(super) async fn check(
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

    pub(super) async fn pause_status(&self) -> Result<Option<CheckResponse>, AppError> {
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
            Duration::from_secs(10),
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
            Duration::from_secs(10),
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
