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
	for name, body := range map[string]string{"valid": string(raw), "unknown": string(raw) + "unknown: true\n", "missing": "listen_port: 80\n", "port": strings.Replace(string(raw), "8080", "65536", 1), "limit": strings.Replace(string(raw), "26214400", "0", 1), "timeout": strings.Replace(string(raw), "30s", "0s", 1), "multiple": string(raw) + "---\n{}\n", "duplicate": string(raw) + "listen_port: 4\n"} {
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
}
