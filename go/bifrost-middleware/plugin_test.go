package main

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"testing"
	"time"

	"github.com/maximhq/bifrost/core/schemas"
)

func TestPreLLMHookBlocksWithoutFallback(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(writer http.ResponseWriter, request *http.Request) {
		_, _ = writer.Write([]byte(`{"clean":false,"blocked":true,"reason_code":"secret"}`))
	}))
	defer server.Close()

	activeClient = &daemonClient{url: server.URL, token: "token", maxPayload: 1024, httpClient: server.Client()}
	defer func() { activeClient = nil }()
	request := &schemas.BifrostRequest{ChatRequest: &schemas.BifrostChatRequest{Model: "test-model", Input: []schemas.ChatMessage{{}}}}
	_, shortCircuit, err := PreLLMHook(nil, request)
	if err != nil {
		t.Fatal(err)
	}
	if shortCircuit == nil || shortCircuit.Error == nil {
		t.Fatal("expected security short-circuit")
	}
	if shortCircuit.Error.AllowFallbacks == nil || *shortCircuit.Error.AllowFallbacks {
		t.Fatal("security denial must disable provider fallback")
	}
}

func TestPostLLMHookBlocksResponseBeforeDelivery(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(writer http.ResponseWriter, request *http.Request) {
		var body daemonRequest
		if err := json.NewDecoder(request.Body).Decode(&body); err != nil {
			t.Fatal(err)
		}
		if body.Action != "block" {
			t.Fatalf("action = %q, want block", body.Action)
		}
		_, _ = writer.Write([]byte(`{"clean":false,"blocked":true}`))
	}))
	defer server.Close()

	activeClient = &daemonClient{url: server.URL, token: "token", maxPayload: 1024, httpClient: server.Client()}
	defer func() { activeClient = nil }()
	response := &schemas.BifrostResponse{ChatResponse: &schemas.BifrostChatResponse{Model: "test-model"}}
	_, bifrostErr, err := PostLLMHook(nil, response, nil)
	if err != nil {
		t.Fatal(err)
	}
	if bifrostErr == nil || bifrostErr.AllowFallbacks == nil || *bifrostErr.AllowFallbacks {
		t.Fatal("expected terminal response denial")
	}
}

func TestDaemonFailureCanBeExplicitlyFailOpen(t *testing.T) {
	activeClient = &daemonClient{
		url:        "http://127.0.0.1:1",
		maxPayload: 1024,
		failClosed: false,
		httpClient: &http.Client{},
	}
	defer func() { activeClient = nil }()

	request := &schemas.BifrostRequest{ChatRequest: &schemas.BifrostChatRequest{Model: "test-model"}}
	_, shortCircuit, err := PreLLMHook(nil, request)
	if err != nil {
		t.Fatal(err)
	}
	if shortCircuit != nil {
		t.Fatal("explicit fail-open mode should not short-circuit daemon unavailability")
	}
}

func TestHTTPTransportStreamChunkHookBlocksBeforeDelivery(t *testing.T) {
	chunk := &schemas.BifrostStreamChunk{
		BifrostChatResponse: &schemas.BifrostChatResponse{Object: "chat.completion.chunk"},
	}

	result, err := HTTPTransportStreamChunkHook(nil, nil, chunk)
	if result != nil {
		t.Fatal("streaming content must not be returned before inspection")
	}
	assertStreamError(t, err, "ai_guardian_stream_unsupported")
}

func TestHTTPTransportStreamChunkHookDoesNotEmitSplitUTF8Fragments(t *testing.T) {
	ctx := schemas.NewBifrostContext(context.Background(), time.Time{})
	defer ctx.Cancel()
	chunks := []*schemas.BifrostStreamChunk{
		{BifrostChatResponse: &schemas.BifrostChatResponse{Object: "chat.completion.chunk"}},
		{BifrostChatResponse: &schemas.BifrostChatResponse{Object: "chat.completion.chunk"}},
	}

	for _, chunk := range chunks {
		result, err := HTTPTransportStreamChunkHook(ctx, nil, chunk)
		if result != nil {
			t.Fatal("split UTF-8 content must not be emitted")
		}
		assertStreamError(t, err, "ai_guardian_stream_unsupported")
	}
}

func TestHTTPTransportStreamChunkHookStopsOnCancellation(t *testing.T) {
	ctx := schemas.NewBifrostContext(context.Background(), time.Time{})
	ctx.Cancel()

	result, err := HTTPTransportStreamChunkHook(ctx, nil, &schemas.BifrostStreamChunk{})
	if result != nil {
		t.Fatal("cancelled stream must not emit a chunk")
	}
	assertStreamError(t, err, "ai_guardian_stream_cancelled")
}

func assertStreamError(t *testing.T, err error, code string) {
	t.Helper()
	interception, ok := err.(*schemas.StreamInterceptionError)
	if !ok || interception.BifrostError == nil || interception.BifrostError.Error == nil || interception.BifrostError.Error.Code == nil {
		t.Fatalf("error = %#v, want structured stream interception error", err)
	}
	if *interception.BifrostError.Error.Code != code {
		t.Fatalf("error code = %q, want %q", *interception.BifrostError.Error.Code, code)
	}
}
