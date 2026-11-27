package main

import (
	"context"
	"errors"
	"testing"
	"time"
)

func TestWebSocketSessionAllowsOnlyAfterCleanVerdict(t *testing.T) {
	var checked []string
	session := newTestWebSocketSession(func(content string) (daemonResponse, error) {
		checked = append(checked, content)
		return daemonResponse{Clean: true}, nil
	})

	if decision := session.open(context.Background(), "wss://provider.example/realtime?opaque=value"); !decision.Allowed {
		t.Fatalf("open denied: %+v", decision)
	}
	decision := session.message(context.Background(), []byte("hello"), false)
	if !decision.Allowed || decision.Sequence != 1 {
		t.Fatalf("message decision = %+v", decision)
	}
	if len(checked) != 2 || checked[0] != "wss://provider.example/realtime" || checked[1] != "hello" {
		t.Fatalf("checked payloads = %#v", checked)
	}
}

func TestWebSocketSessionDenialTerminatesSession(t *testing.T) {
	session := newTestWebSocketSession(func(string) (daemonResponse, error) {
		return daemonResponse{Blocked: true}, nil
	})

	decision := session.open(context.Background(), "wss://provider.example/realtime")
	if decision.Allowed || decision.Code != "ai_guardian_denied" {
		t.Fatalf("open decision = %+v", decision)
	}
	if next := session.message(context.Background(), []byte("later"), false); next.Code != "session_lifecycle_error" {
		t.Fatalf("denied session remained usable: %+v", next)
	}
}

func TestWebSocketSessionFailureModeAndExplicitDenial(t *testing.T) {
	session := newTestWebSocketSession(func(string) (daemonResponse, error) {
		return daemonResponse{}, errors.New("daemon unavailable")
	})
	session.failClosed = false
	if decision := session.open(context.Background(), "wss://provider.example/realtime"); !decision.Allowed {
		t.Fatalf("failure-open preflight denied: %+v", decision)
	}

	denied := newTestWebSocketSession(func(string) (daemonResponse, error) {
		return daemonResponse{Blocked: true}, nil
	})
	denied.failClosed = false
	if decision := denied.open(context.Background(), "wss://provider.example/realtime"); decision.Allowed {
		t.Fatal("explicit security denial must remain blocking")
	}
}

func TestWebSocketSessionHandlesPauseMalformedAndCancellation(t *testing.T) {
	session := newTestWebSocketSession(func(string) (daemonResponse, error) {
		return daemonResponse{Clean: true, Reason: "daemon_paused"}, nil
	})
	if decision := session.open(context.Background(), "wss://provider.example/realtime"); !decision.Allowed || decision.Code != "daemon_paused" {
		t.Fatalf("paused decision = %+v", decision)
	}
	if decision := session.message(context.Background(), []byte("binary"), true); decision.Code != "unsupported_websocket_payload" {
		t.Fatalf("binary decision = %+v", decision)
	}

	malformed := newTestWebSocketSession(func(string) (daemonResponse, error) {
		return daemonResponse{Clean: true}, nil
	})
	if decision := malformed.open(context.Background(), " "); decision.Code != "malformed_websocket_target" {
		t.Fatalf("malformed target decision = %+v", decision)
	}

	cancelled := newTestWebSocketSession(func(string) (daemonResponse, error) {
		return daemonResponse{Clean: true}, nil
	})
	ctx, cancel := context.WithCancel(context.Background())
	cancel()
	if decision := cancelled.open(ctx, "wss://provider.example/realtime"); decision.Code != "session_cancelled" {
		t.Fatalf("cancelled decision = %+v", decision)
	}
}

func TestWebSocketSessionBoundsPayloadMessagesAndLifetime(t *testing.T) {
	session := newTestWebSocketSession(func(string) (daemonResponse, error) {
		return daemonResponse{Clean: true}, nil
	})
	session.maxPayload = 3
	session.maxMessages = 1
	session.idleTimeout = time.Second
	if decision := session.open(context.Background(), "ok"); !decision.Allowed {
		t.Fatalf("open denied: %+v", decision)
	}
	if decision := session.message(context.Background(), []byte("1234"), false); decision.Code != "payload_limit_exceeded" {
		t.Fatalf("oversized message decision = %+v", decision)
	}

	bounded := newTestWebSocketSession(func(string) (daemonResponse, error) {
		return daemonResponse{Clean: true}, nil
	})
	bounded.maxMessages = 1
	if decision := bounded.open(context.Background(), "ok"); !decision.Allowed {
		t.Fatalf("bounded open denied: %+v", decision)
	}
	if decision := bounded.message(context.Background(), []byte("one"), false); !decision.Allowed {
		t.Fatalf("first message denied: %+v", decision)
	}
	if decision := bounded.message(context.Background(), []byte("two"), false); decision.Code != "session_limit_exceeded" {
		t.Fatalf("message limit decision = %+v", decision)
	}

	expired := newTestWebSocketSession(func(string) (daemonResponse, error) {
		return daemonResponse{Clean: true}, nil
	})
	expired.idleTimeout = time.Second
	if decision := expired.open(context.Background(), "ok"); !decision.Allowed {
		t.Fatalf("expired open denied: %+v", decision)
	}
	expired.lastActivity = time.Now().Add(-time.Minute)
	if decision := expired.message(context.Background(), []byte("late"), false); decision.Code != "session_expired" {
		t.Fatalf("expiry decision = %+v", decision)
	}
}
