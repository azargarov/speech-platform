package config

import (
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func TestConfig(t *testing.T) {
	raw, e := os.ReadFile("../../configs/gateway.yaml")
	if e != nil {
		t.Fatal(e)
	}
	t.Setenv("GROQ_STT_API_KEY", "")
	t.Setenv("SPEECH_API_TOKEN", "offline-test-token-0123456789abcdef")
	t.Setenv("SPEECH_LISTEN_PORT", "")
	withoutWarmup := strings.Replace(string(raw), "warmup_timeout: 180s\n", "", 1)
	pathWithoutWarmup := t.TempDir() + "/gateway.yaml"
	if err := os.WriteFile(pathWithoutWarmup, []byte(withoutWarmup), 0600); err != nil {
		t.Fatal(err)
	}
	if loaded, err := Load(pathWithoutWarmup); err != nil || loaded.WarmupTimeout != "180s" {
		t.Fatalf("backward-compatible warmup default=%q err=%v", loaded.WarmupTimeout, err)
	}
	for name, body := range map[string]string{"valid": string(raw), "unknown": string(raw) + "unknown: true\n", "missing": "listen_port: 80\n", "port_low": strings.Replace(string(raw), "8080", "0", 1), "port_high": strings.Replace(string(raw), "8080", "65536", 1), "limit": strings.Replace(string(raw), "26214400", "0", 1), "limit_above_contract": strings.Replace(string(raw), "26214400", "26214401", 1), "header_limit": strings.Replace(string(raw), "1048576", "0", 1), "timeout": strings.Replace(string(raw), "30s", "0s", 1), "stt_timeout_zero": strings.Replace(string(raw), "stt_timeout: 180s", "stt_timeout: 0s", 1), "stt_timeout_too_long": strings.Replace(string(raw), "stt_timeout: 180s", "stt_timeout: 11m", 1), "warmup_timeout_zero": strings.Replace(string(raw), "warmup_timeout: 180s", "warmup_timeout: 0s", 1), "warmup_timeout_too_long": strings.Replace(string(raw), "warmup_timeout: 180s", "warmup_timeout: 11m", 1), "warmup_exceeds_write_timeout": strings.Replace(string(raw), "write_timeout: 610s", "write_timeout: 100s", 1), "malformed_stt_url": strings.Replace(string(raw), "http://stt:8081", "https://user:secret@outside", 1), "multiple": string(raw) + "---\n{}\n", "duplicate": string(raw) + "listen_port: 4\n", "malformed_host": strings.Replace(string(raw), "0.0.0.0", "http://localhost", 1), "host_whitespace": strings.Replace(string(raw), "0.0.0.0", "bad host", 1), "malformed_ipv4": strings.Replace(string(raw), "0.0.0.0", "256.0.0.1", 1)} {
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

func TestGroqSTTConfigurationDefaultsAndValidation(t *testing.T) {
	t.Setenv("SPEECH_LISTEN_PORT", "")
	t.Setenv("SPEECH_API_TOKEN", "offline-test-token-0123456789abcdef")
	raw, err := os.ReadFile("../../configs/gateway.yaml")
	if err != nil {
		t.Fatal(err)
	}
	path := func(content string) string {
		t.Helper()
		name := t.TempDir() + "/gateway.yaml"
		if err := os.WriteFile(name, []byte(content), 0600); err != nil {
			t.Fatal(err)
		}
		return name
	}
	c, err := Load(path(string(raw)))
	if err != nil {
		t.Fatal(err)
	}
	if c.GroqSTT.Enabled || c.GroqSTT.Capacity == nil || *c.GroqSTT.Capacity != 2 || c.GroqSTT.Model != "whisper-large-v3-turbo" || c.GroqSTT.APIKeyEnv != "GROQ_STT_API_KEY" {
		t.Fatalf("unexpected Groq defaults: %+v", c.GroqSTT)
	}
	for name, body := range map[string]string{
		"capacity zero":       strings.Replace(string(raw), "capacity: 2", "capacity: 0", 1),
		"capacity over limit": strings.Replace(string(raw), "capacity: 2", "capacity: 3", 1),
		"unsupported model":   strings.Replace(string(raw), "whisper-large-v3-turbo", "other-model", 1),
		"invalid env name":    strings.Replace(string(raw), "GROQ_STT_API_KEY", "bad-name", 1),
	} {
		t.Run(name, func(t *testing.T) {
			if _, err := Load(path(body)); err == nil {
				t.Fatal("invalid Groq configuration was accepted")
			}
		})
	}
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

func TestTextTransformExampleAndStrictNestedConfig(t *testing.T) {
	t.Setenv("SPEECH_LISTEN_PORT", "")
	t.Setenv("SPEECH_API_TOKEN", "offline-test-token-0123456789abcdef")
	t.Setenv("GROQ_API_KEY", "")
	raw, err := os.ReadFile("../../configs/gateway-text.example.yaml")
	if err != nil {
		t.Fatal(err)
	}
	valid := string(raw)
	configured, err := Load("../../configs/gateway-text.example.yaml")
	if err != nil {
		t.Fatal(err)
	}
	wantPrompt, err := filepath.Abs("../../configs/prompts/text-transformation-system.txt")
	if err != nil || configured.TextTransform.PromptFile != wantPrompt {
		t.Fatalf("resolved prompt path=%q, want %q; err=%v", configured.TextTransform.PromptFile, wantPrompt, err)
	}
	withoutWarmupKeepAlive := strings.Replace(valid, "  warmup_keep_alive: 60s\n", "", 1)
	defaultPath := t.TempDir() + "/gateway-default.yaml"
	if err := os.WriteFile(defaultPath, []byte(withoutWarmupKeepAlive), 0600); err != nil {
		t.Fatal(err)
	}
	defaultConfig, err := Load(defaultPath)
	if err != nil || defaultConfig.TextTransform.WarmupKeepAlive != "60s" {
		t.Fatalf("backward-compatible warmup keep-alive=%v err=%v", defaultConfig.TextTransform, err)
	}
	for name, body := range map[string]string{
		"valid":                     valid,
		"unknown nested field":      strings.Replace(valid, "      enabled: true", "      enabled: true\n      surprise: true", 1),
		"duplicate nested key":      strings.Replace(valid, "  enabled: true", "  enabled: true\n  enabled: true", 1),
		"required enabled":          strings.Replace(valid, "  enabled: true\n", "", 1),
		"required prompt file":      strings.Replace(valid, "  prompt_file: ../configs/prompts/text-transformation-system.txt\n", "", 1),
		"cloud requires https":      strings.Replace(valid, "https://api.groq.com", "http://api.groq.com", 1),
		"invalid output budget":     strings.Replace(valid, "num_predict: 1024", "num_predict: 8192", 1),
		"invalid warmup keep alive": strings.Replace(valid, "warmup_keep_alive: 60s", "warmup_keep_alive: 0s", 1),
		"unknown parameter block":   strings.Replace(valid, "        ollama:", "        unknown:", 1),
	} {
		t.Run(name, func(t *testing.T) {
			path := t.TempDir() + "/config.yaml"
			if err := os.WriteFile(path, []byte(body), 0600); err != nil {
				t.Fatal(err)
			}
			_, err := Load(path)
			if (err == nil) != (name == "valid") {
				t.Fatalf("error=%v", err)
			}
		})
	}
}

func TestCloudCredentialsAreResolvedOnlyForPermittedEnabledModels(t *testing.T) {
	t.Setenv("SPEECH_API_TOKEN", "offline-test-token-0123456789abcdef")
	t.Setenv("GROQ_API_KEY", "secret-test-value")
	c, err := Load("../../configs/gateway-text.example.yaml")
	if err != nil {
		t.Fatal(err)
	}
	if got := c.TextTransform.ResolveCredentials(); len(got) != 0 {
		t.Fatalf("cloud forbidden but credentials resolved: %#v", got)
	}
	c.TextTransform.Selection.AllowCloud = true
	got := c.TextTransform.ResolveCredentials()
	if got["groq"] != "secret-test-value" {
		t.Fatalf("credential not resolved for permitted model: %#v", got)
	}
}

func TestGatewayRequiresStrongTokenRegardlessOfBindAddress(t *testing.T) {
	for _, bind := range []string{"127.0.0.1", "0.0.0.0"} {
		t.Run(bind, func(t *testing.T) {
			t.Setenv("SPEECH_API_TOKEN", "")
			t.Setenv("SPEECH_BIND_IP", bind)
			if _, err := Load("../../configs/gateway.yaml"); err == nil {
				t.Fatal("accepted empty token")
			}
			t.Setenv("SPEECH_API_TOKEN", "short-token")
			if _, err := Load("../../configs/gateway.yaml"); err == nil {
				t.Fatal("accepted short token")
			}
			t.Setenv("SPEECH_API_TOKEN", "offline-test-token-0123456789abcdef")
			if _, err := Load("../../configs/gateway.yaml"); err != nil {
				t.Fatalf("rejected valid token: %v", err)
			}
		})
	}
}
