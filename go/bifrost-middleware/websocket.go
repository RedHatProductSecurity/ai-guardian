package main

import (
	"context"
	"errors"
	"strings"
	"sync"
	"time"
)

const (
	defaultWebSocketMaxMessages = 256
	defaultWebSocketIdleTimeout = 5 * time.Minute
)

var errRealtimeUnsupported = errors.New("Bifrost native realtime/WebSocket hooks are not verified")

// webSocketDecision is returned before a frame is released to its peer. The
// adapter must not write the payload until Allowed is true.
type webSocketDecision struct {
	Allowed  bool
	Sequence uint64
	Code     string
	Message  string
}

type webSocketCheck func(string) (daemonResponse, error)

// webSocketSession is the bounded enforcement contract for a future native
// Bifrost realtime adapter. It deliberately owns no socket and never forwards
// a frame; the host adapter must apply the decision atomically.
type webSocketSession struct {
	mu           sync.Mutex
	check        webSocketCheck
	maxPayload   int
	maxMessages  int
	idleTimeout  time.Duration
	failClosed   bool
	opened       bool
	closed       bool
	sequence     uint64
	messages     int
	lastActivity time.Time
}

func newWebSocketSession(client *daemonClient) *webSocketSession {
	maxPayload := client.maxPayload
	if maxPayload <= 0 {
		maxPayload = defaultMaxPayloadBytes
	}
	return &webSocketSession{
		check:       client.check,
		maxPayload:  maxPayload,
		maxMessages: defaultWebSocketMaxMessages,
		idleTimeout: defaultWebSocketIdleTimeout,
		failClosed:  client.failClosed,
	}
}

func newTestWebSocketSession(check webSocketCheck) *webSocketSession {
	return &webSocketSession{
		check:       check,
		maxPayload:  defaultMaxPayloadBytes,
		maxMessages: defaultWebSocketMaxMessages,
		idleTimeout: defaultWebSocketIdleTimeout,
		failClosed:  true,
	}
}

// open performs the pre-upgrade gate. A denied or failed preflight closes the
// session so callers cannot retry around the security decision.
func (s *webSocketSession) open(ctx context.Context, target string) webSocketDecision {
	s.mu.Lock()
	defer s.mu.Unlock()
	if s.opened || s.closed {
		return webSocketDecision{Code: "session_lifecycle_error", Message: "WebSocket session is not available"}
	}
	if err := contextError(ctx); err != nil {
		s.closed = true
		return webSocketDecision{Code: "session_cancelled", Message: err.Error()}
	}
	target = strings.TrimSpace(target)
	if query := strings.IndexByte(target, '?'); query >= 0 {
		target = target[:query]
	}
	if target == "" {
		s.closed = true
		return webSocketDecision{Code: "malformed_websocket_target", Message: "WebSocket target is required"}
	}
	if len(target) > s.maxPayload {
		s.closed = true
		return webSocketDecision{Code: "payload_limit_exceeded", Message: "WebSocket target exceeds configured limit"}
	}
	decision := s.evaluate(ctx, target)
	if !decision.Allowed {
		s.closed = true
		return decision
	}
	s.opened = true
	s.lastActivity = time.Now()
	return decision
}

// message checks one complete, reconstructed frame. Calls are serialized to
// preserve sequence ordering and to bound the state retained per session.
func (s *webSocketSession) message(ctx context.Context, payload []byte, binary bool) webSocketDecision {
	s.mu.Lock()
	defer s.mu.Unlock()
	if !s.opened || s.closed {
		return webSocketDecision{Code: "session_lifecycle_error", Message: "WebSocket session is not open"}
	}
	if err := contextError(ctx); err != nil {
		s.closed = true
		return webSocketDecision{Code: "session_cancelled", Message: err.Error()}
	}
	if time.Since(s.lastActivity) > s.idleTimeout {
		s.closed = true
		return webSocketDecision{Code: "session_expired", Message: "WebSocket session expired"}
	}
	if binary {
		s.closed = true
		return webSocketDecision{Code: "unsupported_websocket_payload", Message: "binary WebSocket payloads are unsupported"}
	}
	if len(payload) > s.maxPayload {
		s.closed = true
		return webSocketDecision{Code: "payload_limit_exceeded", Message: "WebSocket payload exceeds configured limit"}
	}
	if s.messages >= s.maxMessages {
		s.closed = true
		return webSocketDecision{Code: "session_limit_exceeded", Message: "WebSocket message limit exceeded"}
	}

	decision := s.evaluate(ctx, string(payload))
	s.sequence++
	decision.Sequence = s.sequence
	if !decision.Allowed {
		s.closed = true
		return decision
	}
	s.messages++
	s.lastActivity = time.Now()
	return decision
}

func (s *webSocketSession) close() {
	s.mu.Lock()
	s.closed = true
	s.mu.Unlock()
}

func (s *webSocketSession) evaluate(ctx context.Context, content string) webSocketDecision {
	if err := contextError(ctx); err != nil {
		return webSocketDecision{Code: "session_cancelled", Message: err.Error()}
	}
	verdict, err := s.check(content)
	if err != nil {
		if !s.failClosed {
			return webSocketDecision{Allowed: true, Code: "ai_guardian_fail_open", Message: "AI Guardian check unavailable; failure-open mode is active"}
		}
		return webSocketDecision{Code: "ai_guardian_unavailable", Message: "AI Guardian daemon unavailable"}
	}
	if verdict.Blocked {
		return webSocketDecision{Code: "ai_guardian_denied", Message: "AI Guardian denied the WebSocket payload"}
	}
	if err := validateVerdict(verdict); err != nil {
		if !s.failClosed {
			return webSocketDecision{Allowed: true, Code: "ai_guardian_fail_open", Message: "AI Guardian verdict invalid; failure-open mode is active"}
		}
		return webSocketDecision{Code: "ai_guardian_invalid_verdict", Message: err.Error()}
	}
	if verdict.Redacted != "" {
		return webSocketDecision{Code: "ai_guardian_redaction_unsupported", Message: "WebSocket redaction cannot be applied atomically"}
	}
	return webSocketDecision{Allowed: true, Code: verdict.Reason, Message: verdict.Message}
}

func contextError(ctx context.Context) error {
	if ctx == nil {
		return nil
	}
	select {
	case <-ctx.Done():
		return ctx.Err()
	default:
		return nil
	}
}
