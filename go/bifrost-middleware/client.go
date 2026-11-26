package main

import (
	"bufio"
	"bytes"
	"crypto/rand"
	"encoding/binary"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net"
	"net/http"
	"os"
	"path/filepath"
	"strings"
	"time"
)

const (
	defaultMaxPayloadBytes = 262144
	maxDaemonResponseBytes = 10 * 1024 * 1024
	defaultTimeout         = 10 * time.Second
)

var checks = []string{"injection", "context_poisoning", "secrets", "pii"}

type daemonRequest struct {
	Content       string   `json:"content"`
	Checks        []string `json:"checks"`
	Action        string   `json:"action"`
	CorrelationID string   `json:"correlation_id"`
	ProjectDir    string   `json:"project_dir,omitempty"`
}

type daemonResponse struct {
	Clean    bool            `json:"clean"`
	Blocked  bool            `json:"blocked"`
	Redacted string          `json:"redacted"`
	Reason   string          `json:"reason_code"`
	Message  string          `json:"message"`
	Findings json.RawMessage `json:"findings"`
}

type socketEnvelope struct {
	Type  string          `json:"type"`
	Data  json.RawMessage `json:"data"`
	Error string          `json:"error"`
}

type socketCheckRequest struct {
	CheckType     string   `json:"check_type"`
	Text          string   `json:"text"`
	Checks        []string `json:"checks"`
	Action        string   `json:"action"`
	CorrelationID string   `json:"correlation_id"`
	ProjectDir    string   `json:"project_dir,omitempty"`
}

type daemonClient struct {
	url        string
	token      string
	socket     string
	projectDir string
	maxPayload int
	timeout    time.Duration
	failClosed bool
	httpClient *http.Client
}

func newDaemonClientFromEnvironment() (*daemonClient, error) {
	maxPayload := defaultMaxPayloadBytes
	if value := os.Getenv("AI_GUARDIAN_MIDDLEWARE_MAX_PAYLOAD_BYTES"); value != "" {
		if _, err := fmt.Sscanf(value, "%d", &maxPayload); err != nil || maxPayload <= 0 {
			return nil, fmt.Errorf("invalid AI_GUARDIAN_MIDDLEWARE_MAX_PAYLOAD_BYTES")
		}
	}
	projectDir := os.Getenv("AI_GUARDIAN_MIDDLEWARE_PROJECT_DIR")
	if projectDir != "" {
		absolute, err := filepath.Abs(projectDir)
		if err != nil {
			return nil, fmt.Errorf("resolve project directory: %w", err)
		}
		projectDir = absolute
	}

	client := &daemonClient{
		projectDir: projectDir,
		maxPayload: maxPayload,
		timeout:    defaultTimeout,
		failClosed: true,
		httpClient: &http.Client{Timeout: defaultTimeout},
	}
	if mode := os.Getenv("AI_GUARDIAN_BIFROST_FAILURE_MODE"); mode != "" {
		switch mode {
		case "fail_closed":
		case "fail_open":
			client.failClosed = false
		default:
			return nil, fmt.Errorf("invalid AI_GUARDIAN_BIFROST_FAILURE_MODE")
		}
	}
	if endpoint := strings.TrimRight(os.Getenv("AI_GUARDIAN_DAEMON_URL"), "/"); endpoint != "" {
		if !strings.HasPrefix(endpoint, "https://") {
			return nil, errors.New("AI_GUARDIAN_DAEMON_URL must use HTTPS")
		}
		token, err := daemonToken()
		if err != nil {
			return nil, err
		}
		client.url, client.token = endpoint, token
		return client, nil
	}
	stateDir := os.Getenv("AI_GUARDIAN_STATE_DIR")
	if stateDir == "" {
		stateDir = os.Getenv("XDG_STATE_HOME")
		if stateDir != "" {
			stateDir = filepath.Join(stateDir, "ai-guardian")
		} else if home, err := os.UserHomeDir(); err == nil {
			stateDir = filepath.Join(home, ".local", "state", "ai-guardian")
		}
	}
	client.socket = os.Getenv("AI_GUARDIAN_DAEMON_SOCKET")
	if client.socket == "" {
		client.socket = filepath.Join(stateDir, "daemon.sock")
	}
	return client, nil
}

func daemonToken() (string, error) {
	if token := os.Getenv("AI_GUARDIAN_DAEMON_TOKEN"); token != "" {
		return token, nil
	}
	path := os.Getenv("AI_GUARDIAN_DAEMON_TOKEN_FILE")
	if path == "" {
		if state := os.Getenv("AI_GUARDIAN_STATE_DIR"); state != "" {
			path = filepath.Join(state, "daemon.token")
		}
	}
	if path == "" {
		return "", errors.New("AI Guardian daemon token is not configured")
	}
	token, err := os.ReadFile(path)
	if err != nil {
		return "", fmt.Errorf("read AI Guardian daemon token: %w", err)
	}
	if strings.TrimSpace(string(token)) == "" {
		return "", errors.New("AI Guardian daemon token is empty")
	}
	return strings.TrimSpace(string(token)), nil
}

func (c *daemonClient) check(content string) (daemonResponse, error) {
	if len(content) > c.maxPayload {
		return daemonResponse{}, fmt.Errorf("payload exceeds configured limit")
	}
	id, err := correlationID()
	if err != nil {
		return daemonResponse{}, err
	}
	body := daemonRequest{Content: content, Checks: checks, Action: "block", CorrelationID: id, ProjectDir: c.projectDir}
	if c.url != "" {
		return c.checkHTTP(body)
	}
	return c.checkUnix(body)
}

func (c *daemonClient) checkHTTP(body daemonRequest) (daemonResponse, error) {
	payload, err := json.Marshal(body)
	if err != nil {
		return daemonResponse{}, err
	}
	request, err := http.NewRequest(http.MethodPost, c.url+"/api/check", bytes.NewReader(payload))
	if err != nil {
		return daemonResponse{}, err
	}
	request.Header.Set("Authorization", "Bearer "+c.token)
	request.Header.Set("Content-Type", "application/json")
	response, err := c.httpClient.Do(request)
	if err != nil {
		return daemonResponse{}, err
	}
	defer response.Body.Close()
	if response.StatusCode < 200 || response.StatusCode >= 300 {
		return daemonResponse{}, fmt.Errorf("daemon /api/check returned HTTP %d", response.StatusCode)
	}
	return decodeDaemonResponse(io.LimitReader(response.Body, maxDaemonResponseBytes))
}

func (c *daemonClient) checkUnix(body daemonRequest) (daemonResponse, error) {
	timeout := c.timeout
	if timeout <= 0 {
		timeout = defaultTimeout
	}
	payload, err := json.Marshal(struct {
		Version int                `json:"version"`
		Type    string             `json:"type"`
		Data    socketCheckRequest `json:"data"`
	}{
		Version: 1,
		Type:    "sdk_check",
		Data: socketCheckRequest{
			CheckType:     "middleware",
			Text:          body.Content,
			Checks:        body.Checks,
			Action:        body.Action,
			CorrelationID: body.CorrelationID,
			ProjectDir:    body.ProjectDir,
		},
	})
	if err != nil {
		return daemonResponse{}, err
	}
	connection, err := net.DialTimeout("unix", c.socket, timeout)
	if err != nil {
		return daemonResponse{}, err
	}
	defer connection.Close()
	_ = connection.SetDeadline(time.Now().Add(timeout))
	if err := binary.Write(connection, binary.BigEndian, uint32(len(payload))); err != nil {
		return daemonResponse{}, err
	}
	if _, err := connection.Write(payload); err != nil {
		return daemonResponse{}, err
	}
	reader := bufio.NewReader(io.LimitReader(connection, maxDaemonResponseBytes+4))
	var length uint32
	if err := binary.Read(reader, binary.BigEndian, &length); err != nil {
		return daemonResponse{}, err
	}
	if length > maxDaemonResponseBytes {
		return daemonResponse{}, errors.New("daemon response exceeds maximum size")
	}
	response := make([]byte, length)
	if _, err := io.ReadFull(reader, response); err != nil {
		return daemonResponse{}, err
	}
	var envelope socketEnvelope
	if err := json.Unmarshal(response, &envelope); err != nil {
		return daemonResponse{}, err
	}
	if envelope.Type != "response" || envelope.Error != "" {
		return daemonResponse{}, errors.New("invalid daemon IPC response")
	}
	var data struct {
		Data daemonResponse `json:"data"`
	}
	if err := json.Unmarshal(envelope.Data, &data); err != nil {
		return daemonResponse{}, err
	}
	return data.Data, nil
}

func decodeDaemonResponse(reader io.Reader) (daemonResponse, error) {
	var response daemonResponse
	if err := json.NewDecoder(reader).Decode(&response); err != nil {
		return daemonResponse{}, err
	}
	return response, nil
}

func correlationID() (string, error) {
	var value [16]byte
	if _, err := rand.Read(value[:]); err != nil {
		return "", err
	}
	return hex.EncodeToString(value[:]), nil
}
