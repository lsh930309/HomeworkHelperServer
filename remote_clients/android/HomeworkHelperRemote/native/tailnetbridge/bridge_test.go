package tailnetbridge

import (
	"encoding/json"
	"testing"
	"time"
)

func TestParseHeaders(t *testing.T) {
	headers, err := parseHeaders(`{"Authorization":"Bearer test","Accept":"application/json"}`)
	if err != nil {
		t.Fatal(err)
	}
	if headers["Authorization"] != "Bearer test" || headers["Accept"] != "application/json" {
		t.Fatalf("unexpected headers: %#v", headers)
	}
}

func TestEncodeStatusKeepsAuthURLReadable(t *testing.T) {
	raw, err := encodeStatus(bridgeStatus{Status: "needs_auth", Message: "login", AuthURL: "https://login.tailscale.com/a/b?c=d&e=f"})
	if err != nil {
		t.Fatal(err)
	}
	var decoded bridgeStatus
	if err := json.Unmarshal([]byte(raw), &decoded); err != nil {
		t.Fatal(err)
	}
	if decoded.AuthURL != "https://login.tailscale.com/a/b?c=d&e=f" {
		t.Fatalf("auth URL was mangled: %q", decoded.AuthURL)
	}
}

func TestDurationOrDefault(t *testing.T) {
	if got := durationOrDefault(1200, time.Second); got != 1200*time.Millisecond {
		t.Fatalf("timeout duration = %v", got)
	}
	if got := durationOrDefault(0, time.Second); got != time.Second {
		t.Fatalf("fallback duration = %v", got)
	}
}
