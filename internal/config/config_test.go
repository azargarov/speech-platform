package config

import (
	"os"
	"strings"
	"testing"
)

func TestConfig(t *testing.T) {
	raw, e := os.ReadFile("../../configs/gateway.yaml")
	if e != nil {
		t.Fatal(e)
	}
	t.Setenv("SPEECH_LISTEN_PORT", "")
	for name, body := range map[string]string{"valid": string(raw), "unknown": string(raw) + "unknown: true\n", "missing": "listen_port: 80\n", "port_low": strings.Replace(string(raw), "8080", "0", 1), "port_high": strings.Replace(string(raw), "8080", "65536", 1), "limit": strings.Replace(string(raw), "26214400", "0", 1), "limit_above_contract": strings.Replace(string(raw), "26214400", "26214401", 1), "header_limit": strings.Replace(string(raw), "1048576", "0", 1), "timeout": strings.Replace(string(raw), "30s", "0s", 1), "stt_timeout_zero": strings.Replace(string(raw), "180s", "0s", 1), "stt_timeout_too_long": strings.Replace(string(raw), "180s", "11m", 1), "malformed_stt_url": strings.Replace(string(raw), "http://stt:8081", "https://user:secret@outside", 1), "multiple": string(raw) + "---\n{}\n", "duplicate": string(raw) + "listen_port: 4\n", "malformed_host": strings.Replace(string(raw), "0.0.0.0", "http://localhost", 1), "host_whitespace": strings.Replace(string(raw), "0.0.0.0", "bad host", 1), "malformed_ipv4": strings.Replace(string(raw), "0.0.0.0", "256.0.0.1", 1)} {
		t.Run(name, func(t *testing.T) {
			p := t.TempDir() + "/config.yaml"
			if e := os.WriteFile(p, []byte(body), 0600); e != nil {
				t.Fatal(e)
			}
			_, e := Load(p)
			if (e == nil) != (name == "valid") {
				t.Fatalf("error=%v", e)
			}
		})
	}
	t.Run("request_limit_boundary", func(t *testing.T) {
		for _, limit := range []string{"1", "26214400"} {
			body := strings.Replace(string(raw), "26214400", limit, 1)
			p := t.TempDir() + "/config.yaml"
			if err := os.WriteFile(p, []byte(body), 0600); err != nil {
				t.Fatal(err)
			}
			if _, err := Load(p); err != nil {
				t.Fatalf("limit %s: %v", limit, err)
			}
		}
	})
	t.Run("port_boundaries", func(t *testing.T) {
		for _, port := range []string{"1", "65535"} {
			t.Setenv("SPEECH_LISTEN_PORT", port)
			if _, err := Load("../../configs/gateway.yaml"); err != nil {
				t.Fatalf("port %s: %v", port, err)
			}
		}
	})
	t.Run("port_override", func(t *testing.T) {
		t.Setenv("SPEECH_LISTEN_PORT", "8765")
		c, err := Load("../../configs/gateway.yaml")
		if err != nil || c.ListenPort != 8765 {
			t.Fatalf("config=%+v error=%v", c, err)
		}
	})
	t.Run("invalid_port_override", func(t *testing.T) {
		for _, port := range []string{"bad", "0", "65536"} {
			t.Setenv("SPEECH_LISTEN_PORT", port)
			if _, err := Load("../../configs/gateway.yaml"); err == nil {
				t.Fatalf("accepted port %q", port)
			}
		}
	})
}

func TestValidHost(t *testing.T) {
	for _, host := range []string{"localhost", "worker.internal", "::1"} {
		if !validHost(host) {
			t.Errorf("validHost(%q) = false", host)
		}
	}
	for _, host := range []string{"[::1]", "256.0.0.1", "host:8080", "bad_host"} {
		if validHost(host) {
			t.Errorf("validHost(%q) = true", host)
		}
	}
}
