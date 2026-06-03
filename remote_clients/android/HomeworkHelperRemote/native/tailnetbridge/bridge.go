package tailnetbridge

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net"
	"net/http"
	"strconv"
	"strings"
	"sync"
	"time"

	"tailscale.com/ipn/ipnstate"
	"tailscale.com/tsnet"
)

const (
	defaultConnectTimeout = 15 * time.Second
	defaultReadTimeout    = 30 * time.Second
	maxReadBytes          = 64 * 1024
)

// Bridge exposes the minimal tsnet surface the Android app needs over gomobile.
type Bridge struct {
	mu sync.Mutex

	stateDir   string
	hostname   string
	controlURL string

	server  *tsnet.Server
	started bool

	lastAuthURL string
	lastMessage string
	nextConnID  int64
	conns       map[int64]net.Conn
}

type bridgeStatus struct {
	Status       string   `json:"status"`
	Message      string   `json:"message"`
	AuthURL      string   `json:"auth_url,omitempty"`
	BackendState string   `json:"backend_state,omitempty"`
	SelfIPs      []string `json:"self_ips,omitempty"`
}

type bridgeHTTPResponse struct {
	Code int    `json:"code"`
	Body string `json:"body"`
}

// NewBridge constructs a reusable tsnet bridge instance.
func NewBridge() *Bridge {
	return &Bridge{
		conns: make(map[int64]net.Conn),
	}
}

// Configure sets persistent node identity and state before Start or Up.
func (b *Bridge) Configure(stateDir, hostname, controlURL string) error {
	b.mu.Lock()
	defer b.mu.Unlock()

	if strings.TrimSpace(stateDir) == "" {
		return errors.New("stateDir is required")
	}
	if b.server != nil {
		_ = b.closeLocked()
	}
	b.stateDir = strings.TrimSpace(stateDir)
	b.hostname = strings.TrimSpace(hostname)
	b.controlURL = strings.TrimSpace(controlURL)
	b.lastAuthURL = ""
	b.lastMessage = ""
	return nil
}

// Start initializes the tsnet server without waiting for login completion.
func (b *Bridge) Start() error {
	_, err := b.serverForUse(true)
	return err
}

// EnsureConnectedJson starts tsnet, waits until Running, and returns Android-facing status JSON.
func (b *Bridge) EnsureConnectedJson(timeoutMillis int64) (string, error) {
	server, err := b.serverForUse(true)
	if err != nil {
		return "", err
	}

	ctx, cancel := context.WithTimeout(context.Background(), durationOrDefault(timeoutMillis, defaultConnectTimeout))
	defer cancel()

	status, err := server.Up(ctx)
	if err != nil {
		fallbackCtx, fallbackCancel := context.WithTimeout(context.Background(), 2*time.Second)
		defer fallbackCancel()
		if fallback, fallbackErr := b.statusFromLocal(fallbackCtx, server, "tsnet 연결 대기 중입니다: "+err.Error()); fallbackErr == nil {
			return encodeStatus(fallback)
		}
		return encodeStatus(b.statusFromError("unavailable", err))
	}
	return encodeStatus(b.statusFromIPN(status, "tsnet tailnet에 연결되었습니다."))
}

// StatusJson returns the current tsnet LocalAPI status without forcing Running.
func (b *Bridge) StatusJson(timeoutMillis int64) (string, error) {
	server, err := b.serverForUse(true)
	if err != nil {
		return "", err
	}
	ctx, cancel := context.WithTimeout(context.Background(), durationOrDefault(timeoutMillis, 5*time.Second))
	defer cancel()

	status, err := b.statusFromLocal(ctx, server, "")
	if err != nil {
		return encodeStatus(b.statusFromError("unavailable", err))
	}
	return encodeStatus(status)
}

// RequestJson sends one HTTP request over the embedded tailnet path.
func (b *Bridge) RequestJson(method, rawURL, headersJSON, body string, connectTimeoutMillis, readTimeoutMillis int64) (string, error) {
	server, err := b.serverForUse(true)
	if err != nil {
		return "", err
	}

	headers, err := parseHeaders(headersJSON)
	if err != nil {
		return "", err
	}
	connectTimeout := durationOrDefault(connectTimeoutMillis, defaultConnectTimeout)
	readTimeout := durationOrDefault(readTimeoutMillis, defaultReadTimeout)
	transport := &http.Transport{
		Proxy: http.ProxyFromEnvironment,
		DialContext: func(ctx context.Context, network, address string) (net.Conn, error) {
			dialCtx, cancel := context.WithTimeout(ctx, connectTimeout)
			defer cancel()
			return server.Dial(dialCtx, network, address)
		},
	}
	defer transport.CloseIdleConnections()

	client := &http.Client{
		Transport: transport,
		Timeout:   connectTimeout + readTimeout,
	}
	var requestBody io.Reader
	if body != "" {
		requestBody = strings.NewReader(body)
	}
	req, err := http.NewRequest(strings.ToUpper(strings.TrimSpace(method)), rawURL, requestBody)
	if err != nil {
		return "", err
	}
	for key, value := range headers {
		req.Header.Set(key, value)
	}

	resp, err := client.Do(req)
	if err != nil {
		return "", err
	}
	defer resp.Body.Close()

	responseBody, err := io.ReadAll(resp.Body)
	if err != nil {
		return "", err
	}
	return encodeHTTPResponse(bridgeHTTPResponse{Code: resp.StatusCode, Body: string(responseBody)})
}

// OpenTcp opens one raw TCP stream over tsnet and returns an opaque connection handle.
func (b *Bridge) OpenTcp(host string, port int64, timeoutMillis int64) (int64, error) {
	server, err := b.serverForUse(true)
	if err != nil {
		return 0, err
	}
	address := net.JoinHostPort(strings.TrimSpace(host), strconv.FormatInt(port, 10))
	ctx, cancel := context.WithTimeout(context.Background(), durationOrDefault(timeoutMillis, defaultConnectTimeout))
	defer cancel()

	conn, err := server.Dial(ctx, "tcp", address)
	if err != nil {
		return 0, err
	}

	b.mu.Lock()
	defer b.mu.Unlock()
	b.nextConnID++
	id := b.nextConnID
	b.conns[id] = conn
	return id, nil
}

// Read reads up to maxBytes from a connection handle. EOF is returned as an empty buffer.
func (b *Bridge) Read(connID int64, maxBytes int64, timeoutMillis int64) ([]byte, error) {
	conn, err := b.conn(connID)
	if err != nil {
		return nil, err
	}
	size := int(maxBytes)
	if size <= 0 || size > maxReadBytes {
		size = maxReadBytes
	}
	if timeoutMillis > 0 {
		if err := conn.SetReadDeadline(time.Now().Add(time.Duration(timeoutMillis) * time.Millisecond)); err != nil {
			return nil, err
		}
	} else {
		if err := conn.SetReadDeadline(time.Time{}); err != nil {
			return nil, err
		}
	}
	buf := make([]byte, size)
	n, err := conn.Read(buf)
	if err != nil {
		if errors.Is(err, io.EOF) {
			return []byte{}, nil
		}
		return nil, err
	}
	return buf[:n], nil
}

// Write writes data to a connection handle and returns the byte count.
func (b *Bridge) Write(connID int64, data []byte) (int64, error) {
	conn, err := b.conn(connID)
	if err != nil {
		return 0, err
	}
	n, err := conn.Write(data)
	return int64(n), err
}

// CloseConn closes and forgets a connection handle.
func (b *Bridge) CloseConn(connID int64) error {
	b.mu.Lock()
	conn := b.conns[connID]
	delete(b.conns, connID)
	b.mu.Unlock()
	if conn == nil {
		return nil
	}
	return conn.Close()
}

// Stop closes active sockets and the embedded tsnet server.
func (b *Bridge) Stop() error {
	b.mu.Lock()
	defer b.mu.Unlock()
	return b.closeLocked()
}

func (b *Bridge) serverForUse(start bool) (*tsnet.Server, error) {
	b.mu.Lock()
	if strings.TrimSpace(b.stateDir) == "" {
		b.mu.Unlock()
		return nil, errors.New("bridge is not configured")
	}
	if b.server == nil {
		b.server = &tsnet.Server{
			Dir:        b.stateDir,
			Hostname:   b.hostname,
			ControlURL: b.controlURL,
			Ephemeral:  false,
			UserLogf:   b.captureUserLogf,
		}
		b.started = false
	}
	server := b.server
	needsStart := start && !b.started
	if needsStart {
		b.started = true
	}
	b.mu.Unlock()

	if needsStart {
		if err := server.Start(); err != nil {
			b.mu.Lock()
			if b.server == server {
				b.started = false
			}
			b.mu.Unlock()
			return nil, err
		}
	}
	return server, nil
}

func (b *Bridge) conn(connID int64) (net.Conn, error) {
	b.mu.Lock()
	defer b.mu.Unlock()
	conn := b.conns[connID]
	if conn == nil {
		return nil, fmt.Errorf("connection %d is not open", connID)
	}
	return conn, nil
}

func (b *Bridge) closeLocked() error {
	var firstErr error
	for id, conn := range b.conns {
		if err := conn.Close(); err != nil && firstErr == nil {
			firstErr = err
		}
		delete(b.conns, id)
	}
	if b.server != nil {
		if err := b.server.Close(); err != nil && firstErr == nil {
			firstErr = err
		}
	}
	b.server = nil
	b.started = false
	return firstErr
}

func (b *Bridge) captureUserLogf(format string, args ...any) {
	message := fmt.Sprintf(format, args...)
	b.mu.Lock()
	defer b.mu.Unlock()
	b.lastMessage = message
	if idx := strings.Index(message, "https://"); idx >= 0 {
		fields := strings.Fields(message[idx:])
		if len(fields) > 0 {
			b.lastAuthURL = strings.TrimSpace(fields[0])
		}
	}
}

func (b *Bridge) statusFromLocal(ctx context.Context, server *tsnet.Server, prefix string) (bridgeStatus, error) {
	client, err := server.LocalClient()
	if err != nil {
		return bridgeStatus{}, err
	}
	status, err := client.Status(ctx)
	if err != nil {
		return bridgeStatus{}, err
	}
	message := prefix
	if message == "" {
		message = "tsnet 상태를 확인했습니다."
	}
	return b.statusFromIPN(status, message), nil
}

func (b *Bridge) statusFromIPN(status *ipnstate.Status, message string) bridgeStatus {
	b.mu.Lock()
	lastAuthURL := b.lastAuthURL
	b.mu.Unlock()

	selfIPs := make([]string, 0, len(status.TailscaleIPs))
	for _, ip := range status.TailscaleIPs {
		selfIPs = append(selfIPs, ip.String())
	}
	authURL := strings.TrimSpace(status.AuthURL)
	if authURL == "" {
		authURL = lastAuthURL
	}

	state := "unavailable"
	switch status.BackendState {
	case "Running":
		if len(selfIPs) > 0 {
			state = "connected"
		} else {
			state = "degraded"
		}
	case "Starting":
		state = "connecting"
	case "NoState", "NeedsLogin", "NeedsMachineAuth":
		state = "needs_auth"
	case "Stopped":
		state = "disabled"
	default:
		if authURL != "" {
			state = "needs_auth"
		} else if len(selfIPs) > 0 {
			state = "degraded"
		}
	}

	if authURL != "" && state == "needs_auth" {
		message = "Tailscale 인증이 필요합니다."
	} else if status.BackendState != "" {
		message = fmt.Sprintf("%s backend=%s", message, status.BackendState)
		if len(selfIPs) > 0 {
			message += " ips=" + strings.Join(selfIPs, ",")
		}
	}
	return bridgeStatus{
		Status:       state,
		Message:      message,
		AuthURL:      authURL,
		BackendState: status.BackendState,
		SelfIPs:      selfIPs,
	}
}

func (b *Bridge) statusFromError(status string, err error) bridgeStatus {
	b.mu.Lock()
	lastAuthURL := b.lastAuthURL
	lastMessage := b.lastMessage
	b.mu.Unlock()
	message := err.Error()
	if lastMessage != "" {
		message = lastMessage + " / " + message
	}
	if lastAuthURL != "" && status == "unavailable" {
		status = "needs_auth"
	}
	return bridgeStatus{
		Status:  status,
		Message: message,
		AuthURL: lastAuthURL,
	}
}

func durationOrDefault(timeoutMillis int64, fallback time.Duration) time.Duration {
	if timeoutMillis <= 0 {
		return fallback
	}
	return time.Duration(timeoutMillis) * time.Millisecond
}

func parseHeaders(raw string) (map[string]string, error) {
	headers := make(map[string]string)
	if strings.TrimSpace(raw) == "" {
		return headers, nil
	}
	if err := json.Unmarshal([]byte(raw), &headers); err != nil {
		return nil, err
	}
	return headers, nil
}

func encodeStatus(status bridgeStatus) (string, error) {
	var buf bytes.Buffer
	encoder := json.NewEncoder(&buf)
	encoder.SetEscapeHTML(false)
	if err := encoder.Encode(status); err != nil {
		return "", err
	}
	return strings.TrimSpace(buf.String()), nil
}

func encodeHTTPResponse(response bridgeHTTPResponse) (string, error) {
	var buf bytes.Buffer
	encoder := json.NewEncoder(&buf)
	encoder.SetEscapeHTML(false)
	if err := encoder.Encode(response); err != nil {
		return "", err
	}
	return strings.TrimSpace(buf.String()), nil
}
