//! HTTP response inspection and redaction capability.

use async_stream::try_stream;
use tokio_stream::{Stream, StreamExt};
use tonic::{Request, Response, Status};
use tracing::{info, warn};

use super::daemon::pause_metadata;
use super::openshell::middleware::v1::{
    self as pb, http_response_body_result, http_response_body_unit, http_response_event,
    http_response_event_result, http_response_preflight_result, HttpResponseBlockDelivery,
    HttpResponseBodyResult, HttpResponseBodyTransform, HttpResponseEventResult,
    HttpResponsePreflightInspect, HttpResponsePreflightResult, HttpResponsePreflightSkip,
    HttpResponseTrailersResult,
};
use super::MiddlewareService;

fn inspection_body_mode(preflight: &pb::HttpResponsePreflight) -> Option<pb::HttpResponseBodyMode> {
    let bodyless = preflight
        .target
        .as_ref()
        .is_some_and(|target| target.method == "HEAD")
        || matches!(preflight.status_code, 204 | 304);
    // V1 forbids retaining STREAM_BYTES input across units. Scanning or
    // redacting each arbitrary unit separately misses cross-unit findings and
    // cannot safely decode split UTF-8, so require a complete body instead.
    let mode = if bodyless {
        pb::HttpResponseBodyMode::HeadersOnly
    } else {
        pb::HttpResponseBodyMode::WholeBodyBytes
    };
    preflight
        .permitted_body_modes
        .contains(&(mode as i32))
        .then_some(mode)
}

impl MiddlewareService {
    pub(super) async fn evaluate_response_rpc(
        &self,
        request: Request<tonic::Streaming<pb::HttpResponseEvent>>,
    ) -> Result<Response<super::ResponseStream>, Status> {
        Ok(Response::new(
            self.evaluate_response_events(request.into_inner()),
        ))
    }

    fn evaluate_response_events(
        &self,
        mut events: impl Stream<Item = Result<pb::HttpResponseEvent, Status>> + Send + Unpin + 'static,
    ) -> super::ResponseStream {
        let service = self.clone();
        let stream = try_stream! {
            let mut request_id = String::new();
            let mut plan = super::policy::ScanPlan {
                checks: vec!["injection", "context_poisoning", "secrets", "pii"],
                response_redaction: true,
            };
            let mut body_mode = None;
            while let Some(event) = events.next().await {
                let event = event?;
                match event.event {
                    Some(http_response_event::Event::Preflight(preflight)) => {
                        request_id = preflight
                            .context
                            .as_ref()
                            .map(|value| value.request_id.clone())
                            .unwrap_or_default();
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
                                        action: Some(http_response_preflight_result::Action::Skip(
                                            HttpResponsePreflightSkip {},
                                        )),
                                        reason: if response.message.is_empty() {
                                            "AI Guardian middleware is paused".to_string()
                                        } else {
                                            response.message
                                        },
                                        reason_code: String::new(),
                                        metadata,
                                        ..Default::default()
                                    },
                                )),
                            };
                            return;
                        }
                        plan = MiddlewareService::scan_plan(preflight.config.as_ref())?;
                        let Some(mode) = inspection_body_mode(&preflight) else {
                            yield HttpResponseEventResult {
                                result: Some(http_response_event_result::Result::PreflightResult(
                                    HttpResponsePreflightResult {
                                        action: Some(http_response_preflight_result::Action::BlockDelivery(
                                            HttpResponseBlockDelivery {},
                                        )),
                                        reason: "AI Guardian requires whole-body response inspection".to_string(),
                                        reason_code: "response_inspection_unavailable".to_string(),
                                        ..Default::default()
                                    },
                                )),
                            };
                            return;
                        };
                        body_mode = Some(mode);
                        yield HttpResponseEventResult {
                            result: Some(http_response_event_result::Result::PreflightResult(
                                HttpResponsePreflightResult {
                                    action: Some(http_response_preflight_result::Action::Inspect(
                                        HttpResponsePreflightInspect {
                                            body_mode: mode as i32,
                                            header_mutations: Vec::new(),
                                        },
                                    )),
                                    ..Default::default()
                                },
                            )),
                        };
                    }
                    Some(http_response_event::Event::Body(unit)) => {
                        if body_mode.take() != Some(pb::HttpResponseBodyMode::WholeBodyBytes) {
                            Err(Status::invalid_argument("body event requires whole-body response inspection"))?;
                        }
                        if unit.sequence != 1 || !unit.end_of_stream {
                            Err(Status::invalid_argument("whole-body response must be one final unit"))?;
                        }
                        let body_sequence = unit.sequence;
                        let data = match unit.payload {
                            Some(http_response_body_unit::Payload::Data(data)) => data,
                            None => Vec::new(),
                        };
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
                        let content = String::from_utf8(data)
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
        Box::pin(stream)
    }
}

#[cfg(test)]
mod tests {
    use super::super::daemon::{DaemonClient, DaemonTransport};
    use super::*;
    use serde_json::{json, Value};
    use std::path::PathBuf;
    use std::sync::{
        atomic::{AtomicUsize, Ordering},
        Arc, Mutex,
    };
    use tokio::io::{AsyncReadExt, AsyncWriteExt};
    use tokio::net::UnixListener;
    use tokio::task::JoinHandle;

    struct MockDaemon {
        service: MiddlewareService,
        requests: Arc<Mutex<Vec<Value>>>,
        path: PathBuf,
        task: JoinHandle<()>,
    }

    impl MockDaemon {
        fn new(paused: bool) -> Self {
            static NEXT_SOCKET: AtomicUsize = AtomicUsize::new(0);
            let path = std::env::temp_dir().join(format!(
                "aigr-{:x}-{:x}.sock",
                std::process::id(),
                NEXT_SOCKET.fetch_add(1, Ordering::Relaxed),
            ));
            let listener = UnixListener::bind(&path).expect("isolated mock daemon socket");
            let requests = Arc::new(Mutex::new(Vec::new()));
            let recorded = requests.clone();
            let task = tokio::spawn(async move {
                loop {
                    let (mut socket, _) = listener.accept().await.expect("daemon request");
                    let length = socket.read_u32().await.expect("request length");
                    let mut bytes = vec![0; length as usize];
                    socket.read_exact(&mut bytes).await.expect("request bytes");
                    let request: Value = serde_json::from_slice(&bytes).expect("request JSON");
                    recorded.lock().unwrap().push(request.clone());
                    let data = if request["type"] == "status" {
                        json!({"paused": paused, "pause_remaining_seconds": 60.0})
                    } else if request["data"]["text"] == "blocked-test-marker" {
                        json!({"clean": false, "blocked": true,
                            "findings": [{"type": "prompt_injection", "should_block": true}]})
                    } else if request["data"]["text"] == "sensitive-test-marker"
                        && request["data"]["checks"]
                            .as_array()
                            .unwrap()
                            .contains(&json!("secrets"))
                    {
                        json!({"clean": false, "blocked": true, "redacted": "[REDACTED]",
                            "findings": [{"type": "secret", "should_block": true}]})
                    } else {
                        json!({"clean": true, "findings": []})
                    };
                    let reply = serde_json::to_vec(&json!({"type": "response", "data": data}))
                        .expect("response JSON");
                    socket
                        .write_u32(reply.len() as u32)
                        .await
                        .expect("response length");
                    socket.write_all(&reply).await.expect("response bytes");
                }
            });
            Self {
                service: MiddlewareService {
                    daemon: DaemonClient {
                        transport: DaemonTransport::unix(path.clone()),
                        project_dir: None,
                    },
                    registration_name: "unit-test".to_string(),
                    max_payload_bytes: super::super::DEFAULT_MAX_PAYLOAD_BYTES,
                },
                requests,
                path,
                task,
            }
        }

        fn scan_requests(&self) -> Vec<Value> {
            self.requests
                .lock()
                .unwrap()
                .iter()
                .filter(|request| request["type"] == "sdk_check")
                .cloned()
                .collect()
        }
    }

    impl Drop for MockDaemon {
        fn drop(&mut self) {
            self.task.abort();
            std::fs::remove_file(&self.path).expect("remove mock daemon socket");
        }
    }

    fn preflight(
        method: &str,
        status_code: u32,
        modes: &[pb::HttpResponseBodyMode],
    ) -> pb::HttpResponseEvent {
        pb::HttpResponseEvent {
            event: Some(http_response_event::Event::Preflight(
                pb::HttpResponsePreflight {
                    context: Some(pb::RequestContext {
                        request_id: "request-test".to_string(),
                        ..Default::default()
                    }),
                    target: Some(pb::HttpRequestTarget {
                        method: method.to_string(),
                        ..Default::default()
                    }),
                    status_code,
                    permitted_body_modes: modes.iter().map(|mode| *mode as i32).collect(),
                    max_payload_bytes: super::super::DEFAULT_MAX_PAYLOAD_BYTES,
                    ..Default::default()
                },
            )),
        }
    }

    fn body(sequence: u64, data: &[u8], end_of_stream: bool) -> pb::HttpResponseEvent {
        pb::HttpResponseEvent {
            event: Some(http_response_event::Event::Body(pb::HttpResponseBodyUnit {
                sequence,
                payload: Some(http_response_body_unit::Payload::Data(data.to_vec())),
                end_of_stream,
            })),
        }
    }

    async fn results(
        service: &MiddlewareService,
        events: Vec<pb::HttpResponseEvent>,
    ) -> Vec<HttpResponseEventResult> {
        let stream =
            service.evaluate_response_events(tokio_stream::iter(events.into_iter().map(Ok)));
        tokio::time::timeout(
            std::time::Duration::from_secs(5),
            stream.collect::<Result<Vec<_>, _>>(),
        )
        .await
        .expect("response processing must not wait for another unit")
        .expect("valid response event stream")
    }

    fn preflight_result(result: &HttpResponseEventResult) -> &HttpResponsePreflightResult {
        match result.result.as_ref().unwrap() {
            http_response_event_result::Result::PreflightResult(result) => result,
            _ => panic!("expected preflight result"),
        }
    }

    fn body_result(result: &HttpResponseEventResult) -> &HttpResponseBodyResult {
        match result.result.as_ref().unwrap() {
            http_response_event_result::Result::BodyResult(result) => result,
            _ => panic!("expected body result"),
        }
    }

    #[tokio::test]
    async fn streaming_only_response_is_blocked_before_split_content_is_delivered() {
        // V1 cannot hold an earlier unit for scanning or redaction with the next.
        for (first, second) in [
            (&b"blocked-test-"[..], &b"marker"[..]),
            (&b"sensitive-test-"[..], &b"marker"[..]),
            (&b"\xe6"[..], &b"\x97\xa5"[..]),
        ] {
            let daemon = MockDaemon::new(false);
            let decisions = results(
                &daemon.service,
                vec![
                    preflight(
                        "GET",
                        200,
                        &[
                            pb::HttpResponseBodyMode::HeadersOnly,
                            pb::HttpResponseBodyMode::StreamBytes,
                        ],
                    ),
                    body(1, first, false),
                    body(2, second, true),
                ],
            )
            .await;
            assert_eq!(decisions.len(), 1);
            let decision = preflight_result(&decisions[0]);
            assert!(matches!(
                decision.action,
                Some(http_response_preflight_result::Action::BlockDelivery(_))
            ));
            assert_eq!(decision.reason_code, "response_inspection_unavailable");
            assert!(daemon.scan_requests().is_empty());
        }
    }

    #[tokio::test]
    async fn bodyless_responses_accept_headers_only_inspection() {
        for (method, status) in [("HEAD", 200), ("GET", 204), ("GET", 304)] {
            let daemon = MockDaemon::new(false);
            let decisions = results(
                &daemon.service,
                vec![preflight(
                    method,
                    status,
                    &[pb::HttpResponseBodyMode::HeadersOnly],
                )],
            )
            .await;
            assert_eq!(decisions.len(), 1);
            assert!(matches!(preflight_result(&decisions[0]).action,
                Some(http_response_preflight_result::Action::Inspect(ref inspect))
                    if inspect.body_mode == pb::HttpResponseBodyMode::HeadersOnly as i32));
            assert!(daemon.scan_requests().is_empty());
        }
    }

    #[tokio::test]
    async fn headers_only_does_not_silently_skip_body_bearing_responses() {
        let daemon = MockDaemon::new(false);
        let decisions = results(
            &daemon.service,
            vec![preflight(
                "GET",
                200,
                &[pb::HttpResponseBodyMode::HeadersOnly],
            )],
        )
        .await;
        assert!(matches!(
            preflight_result(&decisions[0]).action,
            Some(http_response_preflight_result::Action::BlockDelivery(_))
        ));
        assert_eq!(
            preflight_result(&decisions[0]).reason_code,
            "response_inspection_unavailable"
        );
    }

    #[tokio::test]
    async fn whole_body_is_preferred_and_unicode_is_scanned_intact() {
        let daemon = MockDaemon::new(false);
        let content = "clean response 日本語";
        let decisions = results(
            &daemon.service,
            vec![
                preflight(
                    "GET",
                    200,
                    &[
                        pb::HttpResponseBodyMode::StreamBytes,
                        pb::HttpResponseBodyMode::WholeBodyBytes,
                        pb::HttpResponseBodyMode::HeadersOnly,
                    ],
                ),
                body(1, content.as_bytes(), true),
                pb::HttpResponseEvent {
                    event: Some(http_response_event::Event::Trailers(
                        pb::HttpResponseTrailers::default(),
                    )),
                },
            ],
        )
        .await;
        assert_eq!(decisions.len(), 3);
        assert!(matches!(preflight_result(&decisions[0]).action,
            Some(http_response_preflight_result::Action::Inspect(ref inspect))
                if inspect.body_mode == pb::HttpResponseBodyMode::WholeBodyBytes as i32));
        let decision = body_result(&decisions[1]);
        assert_eq!(decision.sequence, 1);
        assert!(matches!(
            decision.action,
            Some(http_response_body_result::Action::PassThrough(_))
        ));
        let checks = daemon.scan_requests();
        assert_eq!(checks.len(), 2);
        assert!(checks
            .iter()
            .all(|request| request["data"]["text"] == content));
        assert!(matches!(
            decisions[2].result,
            Some(http_response_event_result::Result::TrailersResult(_))
        ));
    }

    #[tokio::test]
    async fn whole_body_findings_are_blocked_or_redacted_before_delivery() {
        for (content, redaction) in [
            ("blocked-test-marker", false),
            ("sensitive-test-marker", true),
        ] {
            let daemon = MockDaemon::new(false);
            let decisions = results(
                &daemon.service,
                vec![
                    preflight("GET", 200, &[pb::HttpResponseBodyMode::WholeBodyBytes]),
                    body(1, content.as_bytes(), true),
                ],
            )
            .await;
            let decision = body_result(&decisions[1]);
            if redaction {
                assert!(matches!(decision.action,
                    Some(http_response_body_result::Action::Transform(ref transform))
                        if transform.replacement == Some(pb::http_response_body_transform::Replacement::Data(b"[REDACTED]".to_vec()))));
            } else {
                assert!(matches!(
                    decision.action,
                    Some(http_response_body_result::Action::BlockDelivery(_))
                ));
            }
            assert!(!decision.findings.is_empty());
        }
    }

    #[tokio::test]
    async fn whole_body_over_payload_limit_is_blocked_without_scanning() {
        let mut daemon = MockDaemon::new(false);
        daemon.service.max_payload_bytes = 4;
        let decisions = results(
            &daemon.service,
            vec![
                preflight("GET", 200, &[pb::HttpResponseBodyMode::WholeBodyBytes]),
                body(1, b"12345", true),
            ],
        )
        .await;
        let decision = body_result(&decisions[1]);
        assert!(matches!(
            decision.action,
            Some(http_response_body_result::Action::BlockDelivery(_))
        ));
        assert_eq!(decision.reason_code, "payload_limit_exceeded");
        assert!(daemon.scan_requests().is_empty());
    }

    #[tokio::test]
    async fn paused_daemon_still_skips_streaming_response_inspection() {
        let daemon = MockDaemon::new(true);
        let decisions = results(
            &daemon.service,
            vec![preflight(
                "GET",
                200,
                &[pb::HttpResponseBodyMode::StreamBytes],
            )],
        )
        .await;
        let decision = preflight_result(&decisions[0]);
        assert!(matches!(
            decision.action,
            Some(http_response_preflight_result::Action::Skip(_))
        ));
        assert_eq!(
            decision.metadata.get("pause_source").map(String::as_str),
            Some("daemon")
        );
        assert!(daemon.scan_requests().is_empty());
    }

    #[tokio::test]
    async fn control_plane_failure_blocks_even_bodyless_responses() {
        let daemon = MockDaemon::new(false);
        let service = daemon.service.clone();
        drop(daemon);
        let decisions = results(
            &service,
            vec![preflight(
                "HEAD",
                200,
                &[pb::HttpResponseBodyMode::HeadersOnly],
            )],
        )
        .await;
        let decision = preflight_result(&decisions[0]);
        assert!(matches!(
            decision.action,
            Some(http_response_preflight_result::Action::BlockDelivery(_))
        ));
        assert_eq!(decision.reason_code, "middleware_control_plane_unavailable");
    }

    #[tokio::test]
    async fn invalid_whole_body_units_fail_without_waiting_or_scanning() {
        for (sequence, final_unit) in [(0, true), (2, true), (1, false)] {
            let daemon = MockDaemon::new(false);
            let stream = daemon
                .service
                .evaluate_response_events(tokio_stream::iter(vec![
                    Ok(preflight(
                        "GET",
                        200,
                        &[pb::HttpResponseBodyMode::WholeBodyBytes],
                    )),
                    Ok(body(sequence, b"clean", final_unit)),
                ]));
            let decisions = tokio::time::timeout(
                std::time::Duration::from_secs(5),
                stream.collect::<Vec<_>>(),
            )
            .await
            .expect("must not wait for another unit");
            assert_eq!(decisions.len(), 2);
            let error = decisions[1].as_ref().expect_err("invalid whole-body unit");
            assert_eq!(error.code(), tonic::Code::InvalidArgument);
            assert_eq!(
                error.message(),
                "whole-body response must be one final unit"
            );
            assert!(daemon.scan_requests().is_empty());
        }
    }

    #[tokio::test]
    async fn body_events_without_body_inspection_are_rejected() {
        let daemon = MockDaemon::new(false);
        let stream = daemon
            .service
            .evaluate_response_events(tokio_stream::iter(vec![
                Ok(preflight(
                    "HEAD",
                    200,
                    &[pb::HttpResponseBodyMode::HeadersOnly],
                )),
                Ok(body(1, b"unexpected body", true)),
            ]));
        let decisions = stream.collect::<Vec<_>>().await;
        let error = decisions[1]
            .as_ref()
            .expect_err("headers-only mode has no body units");
        assert_eq!(error.code(), tonic::Code::InvalidArgument);
        assert_eq!(
            error.message(),
            "body event requires whole-body response inspection"
        );
        assert!(daemon.scan_requests().is_empty());
    }

    #[tokio::test]
    async fn empty_whole_body_passes_without_content_scanning() {
        let daemon = MockDaemon::new(false);
        let decisions = results(
            &daemon.service,
            vec![
                preflight("GET", 200, &[pb::HttpResponseBodyMode::WholeBodyBytes]),
                body(1, b"", true),
            ],
        )
        .await;
        assert!(matches!(
            body_result(&decisions[1]).action,
            Some(http_response_body_result::Action::PassThrough(_))
        ));
        assert!(daemon.scan_requests().is_empty());
    }

    #[tokio::test]
    async fn scanner_failure_blocks_whole_body_delivery() {
        let daemon = MockDaemon::new(false);
        let mut stream = daemon
            .service
            .evaluate_response_events(tokio_stream::iter(vec![
                Ok(preflight(
                    "GET",
                    200,
                    &[pb::HttpResponseBodyMode::WholeBodyBytes],
                )),
                Ok(body(1, b"clean", true)),
            ]));
        stream.next().await.unwrap().expect("preflight accepted");
        drop(daemon);
        let decision = stream.next().await.unwrap().expect("explicit body denial");
        assert!(matches!(
            body_result(&decision).action,
            Some(http_response_body_result::Action::BlockDelivery(_))
        ));
        assert_eq!(
            body_result(&decision).reason_code,
            "middleware_control_plane_unavailable"
        );
        assert!(stream.next().await.is_none());
    }
}
