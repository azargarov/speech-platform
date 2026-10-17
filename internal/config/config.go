package config

import (
	"fmt"
	"gopkg.in/yaml.v3"
	"io"
	"net/url"
	"os"
	"strconv"
	"time"
)

type Config struct {
	ListenHost      string `yaml:"listen_host"`
	ListenPort      int    `yaml:"listen_port"`
	MaxHeaderBytes  int    `yaml:"max_header_bytes"`
	MaxRequestBytes int64  `yaml:"max_request_bytes"`
	ReadTimeout     string `yaml:"read_timeout"`
	WriteTimeout    string `yaml:"write_timeout"`
	IdleTimeout     string `yaml:"idle_timeout"`
	ShutdownTimeout string `yaml:"shutdown_timeout"`
	STTURL          string `yaml:"stt_url"`
	TTSURL          string `yaml:"tts_url"`
	AuthMode        string `yaml:"auth_mode"`
}

func Load(path string) (Config, error) {
	var c Config
	f, e := os.Open(path)
	if e != nil {
		return c, e
	}
	defer f.Close()
	d := yaml.NewDecoder(f)
	d.KnownFields(true)
	if e = d.Decode(&c); e != nil {
		return c, e
	}
	var extra any
	if e = d.Decode(&extra); e != io.EOF {
		return c, fmt.Errorf("expected exactly one YAML document")
	}
	return c, c.Validate()
}
func (c Config) Validate() error {
	if c.ListenHost == "" || c.ListenPort < 1 || c.ListenPort > 65535 || c.MaxRequestBytes < 1 || c.MaxHeaderBytes < 1 {
		return fmt.Errorf("listen_host, valid listen_port and positive max_request_bytes required")
	}
	for _, v := range []string{c.ReadTimeout, c.WriteTimeout, c.IdleTimeout, c.ShutdownTimeout} {
		d, e := time.ParseDuration(v)
		if e != nil || d <= 0 {
			return fmt.Errorf("all timeouts must be positive durations")
		}
	}
	for _, v := range []string{c.STTURL, c.TTSURL} {
		u, e := url.Parse(v)
		if e != nil || u.Hostname() == "" || (u.Scheme != "http" && u.Scheme != "https") || u.User != nil || u.RawQuery != "" || u.Fragment != "" || (u.Path != "" && u.Path != "/") {
			return fmt.Errorf("worker URL must be an HTTP origin")
		}
		if p := u.Port(); p != "" {
			n, e := strconv.Atoi(p)
			if e != nil || n < 1 || n > 65535 {
				return fmt.Errorf("invalid worker port")
			}
		}
	}
	if c.AuthMode != "disabled" && c.AuthMode != "bearer" {
		return fmt.Errorf("auth_mode must be disabled or bearer")
	}
	return nil
}
