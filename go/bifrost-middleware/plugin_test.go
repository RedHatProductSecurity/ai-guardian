package main

import (
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"testing"

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
